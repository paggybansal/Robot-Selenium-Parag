"""Environment-driven AWS configuration for PDQA suppression-rule tests.

Resolution order for every value:  os.environ  →  per-env default map.
Side-effect free: importing this module never touches AWS or a DB.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

# AWS documents these as internal Glue parameters. The PDQA job legitimately
# consumes '--mode', so we warn + verify at runtime rather than block.
GLUE_INTERNAL_ARGUMENT_NAMES = {"--conf", "--debug", "--mode", "--JOB_NAME"}

VALID_LOG_SOURCES = ("auto", "api", "manager", "file")


def _env() -> str:
    # Matches settings.py convention: ENVIRONMENT = int | pvs | dev
    return (os.getenv("ENVIRONMENT", os.getenv("ENV", "int"))
            .strip().lower().replace("zilverton", ""))


# ── Per-environment defaults (override any of these via .env) ──────────────
_DEFAULTS: Dict[str, Dict[str, str]] = {
    "int": {
        "GLUE_JOB": "usmg-int-provider-pdqa-automation-practitioner-dir-supp-glue-job",
        "OUTBOUND_BUCKET": "usmg-int-provider-dataloader",
        "OUTBOUND_PREFIX": "home/generic/pdqa/practitioner_update/",
        "PROCESSED_PREFIX": "",
        "LOG_GROUP": "/aws-glue/jobs/output",
        "GLUE_ARG_MODE": "daily",
        "GLUE_ARG_LASTRUNTIME": "9999-12-31 00:00:00",
    },
    "pvs": {
        "GLUE_JOB": "usmg-pvs-provider-pdqa-automation-practitioner-dir-supp-glue-job",
        "OUTBOUND_BUCKET": "usmg-pvs-provider-dataloader",
        "OUTBOUND_PREFIX": "home/generic/pdqa/practitioner_update/",
        "PROCESSED_PREFIX": "",
        "LOG_GROUP": "/aws-glue/jobs/output",
        "GLUE_ARG_MODE": "daily",
        "GLUE_ARG_LASTRUNTIME": "9999-12-31 00:00:00",
    },
}


def _get(key: str, default: str = "") -> str:
    fallback = _DEFAULTS.get(_env(), {}).get(key, default)
    return os.getenv(f"AWS_{key}", fallback).strip()


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    return int(raw) if raw.isdigit() else default


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if raw in ("true", "1", "yes", "y"):
        return True
    if raw in ("false", "0", "no", "n"):
        return False
    return default


def _resolve_glue_arguments() -> dict:
    """Whole-dict override via AWS_GLUE_JOB_ARGUMENTS (JSON), else per-key GLUE_ARG_*."""
    raw = os.getenv("AWS_GLUE_JOB_ARGUMENTS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"AWS_GLUE_JOB_ARGUMENTS is not valid JSON: {exc}. Expected e.g. "
                '{"--mode": "daily", "--lastruntime": "9999-12-31 00:00:00"}'
            ) from None
        if not isinstance(parsed, dict):
            raise RuntimeError("AWS_GLUE_JOB_ARGUMENTS must be a JSON object")
        args = {str(k): str(v) for k, v in parsed.items()}
    else:
        args = {
            "--mode": _get("GLUE_ARG_MODE", "daily"),
            "--lastruntime": _get("GLUE_ARG_LASTRUNTIME", "9999-12-31 00:00:00"),
        }

    bad = [k for k in args if not k.startswith("--")]
    if bad:
        raise RuntimeError(f"Glue argument keys must start with '--': {bad}")
    return {k: v for k, v in args.items() if v != ""}


@dataclass(frozen=True)
class AwsSuppressionConfig:
    environment: str = field(default_factory=_env)
    profile_name: Optional[str] = None
    region_name: str = "us-east-1"

    # Glue
    glue_job_name: str = ""
    glue_job_arguments: dict = field(default_factory=dict)
    verify_glue_arguments: bool = True

    # CloudWatch
    log_group_name: str = ""
    glue_log_source: str = "auto"      # auto | api | manager | file
    glue_log_file: str = ""            # explicit path to a saved output.logs
    glue_log_dir: str = ""             # folder to auto-discover a log file in
    glue_log_url: str = ""             # pasted console URL → proves file ownership

    # S3
    outbound_bucket: str = ""
    outbound_prefix: str = ""
    processed_prefix: str = ""

    # File contract
    outbound_file_pattern: str = r".*\.csv$"
    outbound_delimiter: str = ","
    outbound_has_header: bool = True

    # SLA-driven timeouts (seconds)
    glue_timeout: int = 1800
    s3_timeout: int = 900
    dataloader_timeout: int = 2400
    log_read_timeout: int = 600
    poll_seconds: int = 15

    # Behaviour switches
    trigger_glue_job: bool = True
    restore_state: bool = False
    enforce_rule_count_match: bool = True
    enforce_row_count_match: bool = True
    enforce_outbound_freshness: bool = False

    # ── reporting ─────────────────────────────────────────────────────
    def describe(self) -> dict:
        return {
            "Environment": self.environment,
            "AWS Profile": self.profile_name or "<default credential chain>",
            "Region": self.region_name,
            "Glue Job": self.glue_job_name,
            "Glue Arguments": ", ".join(f"{k} {v}" for k, v in
                                        sorted(self.glue_job_arguments.items())) or "—",
            "Log Group": self.log_group_name,
            "Glue Log Source": self.glue_log_source
                               + (f" (file={self.glue_log_file})" if self.glue_log_file else "")
                               + (" (url set)" if self.glue_log_url else ""),
            "Outbound": f"s3://{self.outbound_bucket}/{self.outbound_prefix}",
            "File Pattern": self.outbound_file_pattern,
            "Trigger Glue": self.trigger_glue_job,
            "Enforce rule_count": self.enforce_rule_count_match,
        }

    # ── CloudWatch URL cross-check ────────────────────────────────────
    def resolve_log_target(self):
        """Parse GLUE_LOG_URL and validate it against configured group/region.

        Returns CloudWatchTarget, or None when GLUE_LOG_URL is unset.
        Imported lazily to keep this module import-light.
        """
        if not self.glue_log_url:
            return None
        from action_api_framework.utils.cloudwatch_links import parse_console_url
        target = parse_console_url(self.glue_log_url)
        if target.log_group.rstrip("/") != self.log_group_name.rstrip("/"):
            raise RuntimeError(
                f"GLUE_LOG_URL points at log group '{target.log_group}' but "
                f"AWS_LOG_GROUP is '{self.log_group_name}'")
        if target.region != self.region_name:
            raise RuntimeError(
                f"GLUE_LOG_URL region '{target.region}' != AWS_REGION '{self.region_name}'")
        return target


def load_aws_suppression_config() -> AwsSuppressionConfig:
    cfg = AwsSuppressionConfig(
        profile_name=(os.getenv("AWS_PROFILE") or os.getenv("AWS_PROFILE_NAME") or None),
        region_name=os.getenv("AWS_REGION", "us-east-1"),

        glue_job_name=_get("GLUE_JOB"),
        glue_job_arguments=_resolve_glue_arguments(),
        verify_glue_arguments=_get_bool("VERIFY_GLUE_ARGUMENTS", True),

        log_group_name=_get("LOG_GROUP"),
        glue_log_source=os.getenv("GLUE_LOG_SOURCE", "auto").strip().lower(),
        glue_log_file=os.getenv("GLUE_LOG_FILE", "").strip(),
        glue_log_dir=os.getenv("GLUE_LOG_DIR", "").strip(),
        glue_log_url=os.getenv("GLUE_LOG_URL", "").strip(),

        outbound_bucket=_get("OUTBOUND_BUCKET"),
        outbound_prefix=_get("OUTBOUND_PREFIX"),
        processed_prefix=_get("PROCESSED_PREFIX"),

        outbound_file_pattern=os.getenv("AWS_OUTBOUND_FILE_PATTERN", r".*\.csv$"),
        outbound_delimiter=os.getenv("AWS_OUTBOUND_DELIMITER", ","),
        outbound_has_header=_get_bool("AWS_OUTBOUND_HAS_HEADER", True),

        glue_timeout=_get_int("GLUE_TIMEOUT_SECONDS", 1800),
        s3_timeout=_get_int("S3_TIMEOUT_SECONDS", 900),
        dataloader_timeout=_get_int("DATALOADER_TIMEOUT_SECONDS", 2400),
        log_read_timeout=_get_int("LOG_READ_TIMEOUT_SECONDS", 600),
        poll_seconds=_get_int("AWS_POLL_SECONDS", 15),

        trigger_glue_job=_get_bool("TRIGGER_GLUE_JOB", True),
        restore_state=_get_bool("SUPPRESSION_RESTORE_STATE", False),
        enforce_rule_count_match=_get_bool("ENFORCE_RULE_COUNT_MATCH", True),
        enforce_row_count_match=_get_bool("ENFORCE_ROW_COUNT_MATCH", True),
        enforce_outbound_freshness=_get_bool("ENFORCE_OUTBOUND_FRESHNESS", False),
    )

    missing = [k for k, v in {
        "glue_job_name": cfg.glue_job_name,
        "log_group_name": cfg.log_group_name,
        "outbound_bucket": cfg.outbound_bucket,
        "outbound_prefix": cfg.outbound_prefix,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"AWS suppression config incomplete for ENVIRONMENT='{cfg.environment}': "
            f"missing {missing}. Set AWS_GLUE_JOB / AWS_LOG_GROUP / AWS_OUTBOUND_BUCKET / "
            f"AWS_OUTBOUND_PREFIX in .env")

    if cfg.glue_log_source not in VALID_LOG_SOURCES:
        raise RuntimeError(f"GLUE_LOG_SOURCE='{cfg.glue_log_source}' invalid; "
                           f"expected one of {VALID_LOG_SOURCES}")
    if cfg.glue_log_source == "file" and not (cfg.glue_log_file or cfg.glue_log_dir):
        raise RuntimeError("GLUE_LOG_SOURCE=file requires GLUE_LOG_FILE or GLUE_LOG_DIR")

    cfg.resolve_log_target()   # fail fast on a mismatched pasted URL
    return cfg
