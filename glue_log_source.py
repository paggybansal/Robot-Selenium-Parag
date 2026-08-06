"""Source-agnostic retrieval of a PDQA Glue run's log text.

Parsing (glue_log_parser) is deliberately decoupled from transport: the CloudWatch
API, the framework's AwsLogManager, or a saved 'output.logs' file all yield the
same string. Sources are tried in order and the one used is always reported.

  api     — strict stream lookup (logStreamNamePrefix == JobRunId)  → ownership PROVEN
  manager — framework AwsLogManager.log_events()                    → ownership WEAK
  file    — saved output.logs (+ GLUE_LOG_URL)                      → PROVEN if URL given
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Pattern, Sequence

from action_api_framework.utils.console_reporter import ConsoleReporter as R

_TRANSPORT_ERRORS = (
    "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError",
    "SSLError", "ProxyConnectionError", "ConnectionClosedError", "ConnectionError",
)

VALID_SOURCES = ("auto", "api", "manager", "file")


@dataclass
class GlueLogText:
    text: str
    messages: List[str]
    source: str                  # 'api' | 'manager' | 'file'
    artifact: Optional[Path]     # local file parsed / saved
    run_id_verified: bool        # True only when run ownership was proven


# ════════════════════════════════════════════════════════════
# helpers
# ════════════════════════════════════════════════════════════
def _normalise_events(events) -> List[str]:
    """log_events() may return list[str], list[dict], or one big str."""
    if events is None:
        return []
    if isinstance(events, str):
        return events.splitlines()
    out: List[str] = []
    for event in events:
        out.append(str(event.get("message", event)) if isinstance(event, dict) else str(event))
    return out


def _is_transport_error(exc: Exception) -> bool:
    return type(exc).__name__ in _TRANSPORT_ERRORS or any(
        name in repr(exc) for name in _TRANSPORT_ERRORS)


def _candidate_dirs(extra: Optional[str]) -> List[Path]:
    dirs: List[Path] = []
    if extra:
        dirs.append(Path(extra))
    cwd = Path.cwd()
    dirs += [cwd, cwd / "logs", cwd / "results", cwd / "results" / "logs",
             cwd / "test_logs", cwd / "reports",
             Path(__file__).resolve().parent.parent / "logs"]
    seen, unique = set(), []
    for directory in dirs:
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if directory.is_dir() and resolved not in seen:
            seen.add(resolved)
            unique.append(directory)
    return unique


def _find_log_file(run_id: Optional[str], explicit: Optional[str],
                   search_dir: Optional[str]) -> Optional[Path]:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise AssertionError(f"GLUE_LOG_FILE does not exist: {path}")

    patterns: List[str] = []
    if run_id:
        patterns.append(f"*{run_id}*")
    patterns += ["output*.log", "output.logs", "*glue*output*.log", "*.log"]

    for directory in _candidate_dirs(search_dir):
        for pattern in patterns:
            try:
                hits = [h for h in directory.rglob(pattern)
                        if h.is_file() and h.stat().st_size > 0]
            except OSError:
                continue
            if hits:
                return max(hits, key=lambda p: p.stat().st_mtime)
    return None


# ════════════════════════════════════════════════════════════
# individual sources
# ════════════════════════════════════════════════════════════
def _from_api(reader, log_group: str, run_id: str, sentinel: Pattern,
              timeout_seconds: int, poll_seconds: int) -> GlueLogText:
    text, messages = reader.wait_for_run_log(
        log_group, run_id, sentinel=sentinel,
        timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
    artifact = None
    try:
        artifact = Path(str(reader.save(messages, run_id)))
    except Exception as exc:                                  # noqa: BLE001
        R.warning(f"Could not persist log artifact: {exc}")
    return GlueLogText(text, messages, "api", artifact, run_id_verified=True)


def _from_manager(log_manager, log_group: str, run_id: str, sentinel: Pattern,
                  timeout_seconds: int, poll_seconds: int) -> GlueLogText:
    deadline = time.time() + timeout_seconds
    while True:
        messages = _normalise_events(log_manager.log_events(run_id, log_group))
        text = "\n".join(messages)
        if messages and sentinel.search(text):
            artifact = None
            try:
                artifact = Path(str(log_manager.write_log_to_test_dir(messages, run_id)))
            except Exception as exc:                          # noqa: BLE001
                R.warning(f"Could not persist log artifact: {exc}")
            # AwsLogManager.log_events() falls back to the most recent stream,
            # so stream identity is NOT guaranteed here.
            return GlueLogText(text, messages, "manager", artifact, run_id in text)
        if time.time() >= deadline:
            raise AssertionError(
                f"AwsLogManager returned {len(messages)} event(s) for run {run_id} but the "
                f"completion line never appeared within {timeout_seconds}s.")
        R.info(f"[manager] {len(messages)} event(s), sentinel not yet present …")
        time.sleep(poll_seconds)


def _from_file(run_id: Optional[str], explicit: Optional[str], search_dir: Optional[str],
               sentinel: Pattern, url_stream: Optional[str] = None) -> GlueLogText:
    path = _find_log_file(run_id, explicit, search_dir)
    if path is None:
        raise AssertionError(
            "No local Glue log file found. Set GLUE_LOG_FILE=<path to output.logs> "
            "and (recommended) GLUE_LOG_URL=<console URL you downloaded it from>.")

    text = path.read_text(encoding="utf-8", errors="replace")
    if not sentinel.search(text):
        raise AssertionError(
            f"Local log file '{path}' has no 'Chunk N written to s3://…' line — "
            f"wrong file or truncated download.\nLast 500 chars:\n{text[-500:]}")

    # Ownership evidence, strongest first:
    #   1. console URL's stream == our JobRunId  (definitive)
    #   2. run id appears in the text or the filename
    verified = False
    if url_stream and run_id:
        if str(url_stream).strip() == str(run_id).strip():
            R.success(f"GLUE_LOG_URL stream matches JobRunId ({run_id}) — ownership proven")
            verified = True
        else:
            raise AssertionError(
                f"GLUE_LOG_URL is for stream '{url_stream}' but this run is '{run_id}'. "
                f"You are about to validate the WRONG job run — re-download the log.")
    elif run_id and (run_id in text or run_id in path.name):
        verified = True

    return GlueLogText(text, text.splitlines(), "file", path, verified)


# ════════════════════════════════════════════════════════════
# public entry point
# ════════════════════════════════════════════════════════════
def read_run_log(*, mode: str, run_id: Optional[str], log_group: str,
                 sentinel: Pattern, timeout_seconds: int, poll_seconds: int,
                 reader=None, log_manager=None,
                 log_file: Optional[str] = None,
                 log_dir: Optional[str] = None,
                 url_stream: Optional[str] = None) -> GlueLogText:
    """Return the Glue run's log text from the first available source.

    url_stream: log-stream name parsed from GLUE_LOG_URL. When supplied it is
    used to PROVE that a locally saved log file belongs to this JobRunId.
    """
    mode = (mode or "auto").strip().lower()
    if mode not in VALID_SOURCES:
        raise AssertionError(f"Unknown log source '{mode}'; expected one of {VALID_SOURCES}")

    order: Sequence[str] = (("api", "manager", "file") if run_id else ("file",)) \
        if mode == "auto" else (mode,)

    failures: List[str] = []
    for source in order:
        try:
            R.info(f"Reading Glue log via source='{source}' …")
            if source == "api":
                if not (reader and run_id):
                    raise AssertionError("api source requires a reader and a run_id")
                result = _from_api(reader, log_group, run_id, sentinel,
                                   timeout_seconds, poll_seconds)
            elif source == "manager":
                if not (log_manager and run_id):
                    raise AssertionError("manager source requires a log_manager and a run_id")
                result = _from_manager(log_manager, log_group, run_id, sentinel,
                                       timeout_seconds, poll_seconds)
            else:                                             # file
                result = _from_file(run_id, log_file, log_dir, sentinel, url_stream)

            R.success(f"Glue log obtained from source='{result.source}' "
                      f"({len(result.messages)} line(s))"
                      + (f", artifact={result.artifact}" if result.artifact else ""))
            if not result.run_id_verified:
                R.warning(f"Source '{result.source}' could not prove the log belongs to "
                          f"run_id={run_id}. Ownership will be enforced via the S3 object "
                          f"referenced inside the log (step 6c).")
            return result

        except Exception as exc:                              # noqa: BLE001
            hint = " (network/TLS — 'logs.' endpoint likely blocked or proxied)" \
                if _is_transport_error(exc) else ""
            failures.append(f"{source}: {type(exc).__name__}: {exc}{hint}")
            R.warning(f"Source '{source}' unavailable{hint} → {type(exc).__name__}")

    raise AssertionError(
        "Could not obtain the Glue run log from any source.\n  - "
        + "\n  - ".join(failures)
        + "\nQuick unblock: download the log stream from the CloudWatch console, then set "
          "GLUE_LOG_SOURCE=file, GLUE_LOG_FILE=<path>, GLUE_LOG_URL=<console URL>."
    )
