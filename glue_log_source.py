"""Source-agnostic retrieval of a PDQA Glue run's log text.

Parsing (glue_log_parser) is deliberately decoupled from transport: CloudWatch
API, the framework's AwsLogManager, or a saved 'output.logs' file all produce the
same string. Falls back gracefully and always reports which source was used.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Pattern, Sequence, Tuple

from action_api_framework.utils.console_reporter import ConsoleReporter as R

_TRANSPORT_ERRORS = (
    "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError",
    "SSLError", "ProxyConnectionError", "ConnectionClosedError",
)


@dataclass
class GlueLogText:
    text: str
    messages: List[str]
    source: str                 # 'api' | 'manager' | 'file'
    artifact: Optional[Path]    # local file we parsed / saved
    run_id_verified: bool       # True only when stream identity was proven


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
    for e in events:
        if isinstance(e, dict):
            out.append(str(e.get("message", e)))
        else:
            out.append(str(e))
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
             cwd / "test_logs", Path(__file__).resolve().parent.parent / "logs"]
    seen, unique = set(), []
    for d in dirs:
        if d.is_dir() and d.resolve() not in seen:
            seen.add(d.resolve())
            unique.append(d)
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
            hits = sorted(directory.rglob(pattern),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            hits = [h for h in hits if h.is_file() and h.stat().st_size > 0]
            if hits:
                return hits[0]
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
        artifact = reader.save(messages, run_id)
    except Exception as exc:
        R.warning(f"Could not persist log artifact: {exc}")
    return GlueLogText(text, messages, "api", artifact, run_id_verified=True)


def _from_manager(log_manager, log_group: str, run_id: str, sentinel: Pattern,
                  timeout_seconds: int, poll_seconds: int) -> GlueLogText:
    deadline = time.time() + timeout_seconds
    messages: List[str] = []
    while True:
        messages = _normalise_events(log_manager.log_events(run_id, log_group))
        text = "\n".join(messages)
        if messages and sentinel.search(text):
            artifact = None
            try:
                artifact = Path(str(log_manager.write_log_to_test_dir(messages, run_id)))
            except Exception as exc:
                R.warning(f"Could not persist log artifact: {exc}")
            # AwsLogManager.log_events() falls back to the most recent stream,
            # so stream identity is NOT proven here.
            verified = run_id in text
            return GlueLogText(text, messages, "manager", artifact, verified)
        if time.time() >= deadline:
            raise AssertionError(
                f"AwsLogManager returned {len(messages)} event(s) for run {run_id} but the "
                f"completion line never appeared within {timeout_seconds}s.")
        R.info(f"[manager] {len(messages)} event(s), sentinel not yet present …")
        time.sleep(poll_seconds)


def _from_file(run_id: Optional[str], explicit: Optional[str], search_dir: Optional[str],
               sentinel: Pattern) -> GlueLogText:
    path = _find_log_file(run_id, explicit, search_dir)
    if path is None:
        raise AssertionError(
            "No local Glue log file found. Set GLUE_LOG_FILE=<path to output.logs> "
            "(CloudWatch console → log stream → Download/copy) or GLUE_LOG_DIR=<folder>.")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not sentinel.search(text):
        raise AssertionError(
            f"Local log file '{path}' does not contain the expected "
            f"'Chunk N written to s3://…' line — wrong file or truncated download.\n"
            f"Last 500 chars:\n{text[-500:]}")
    verified = bool(run_id and run_id in text) or bool(run_id and run_id in path.name)
    return GlueLogText(text, text.splitlines(), "file", path, verified)


# ════════════════════════════════════════════════════════════
# public entry point
# ════════════════════════════════════════════════════════════
def read_run_log(*, mode: str, run_id: Optional[str], log_group: str,
                 sentinel: Pattern, timeout_seconds: int, poll_seconds: int,
                 reader=None, log_manager=None,
                 log_file: Optional[str] = None,
                 log_dir: Optional[str] = None) -> GlueLogText:
    mode = (mode or "auto").strip().lower()
    order: Sequence[str]
    if mode == "auto":
        order = ("api", "manager", "file") if run_id else ("file",)
    else:
        order = (mode,)

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
                    raise AssertionError("manager source requires a log_manager and run_id")
                result = _from_manager(log_manager, log_group, run_id, sentinel,
                                       timeout_seconds, poll_seconds)
            elif source == "file":
                result = _from_file(run_id, log_file, log_dir, sentinel)
            else:
                raise AssertionError(f"Unknown GLUE_LOG_SOURCE '{source}' "
                                     f"(expected auto|api|manager|file)")

            R.success(f"Glue log obtained from source='{result.source}' "
                      f"({len(result.messages)} line(s))"
                      + (f", artifact={result.artifact}" if result.artifact else ""))
            if not result.run_id_verified:
                R.warning(f"Log source '{result.source}' could not prove the log belongs to "
                          f"run_id={run_id}. Ownership will be enforced via the S3 object "
                          f"referenced inside the log.")
            return result

        except Exception as exc:               # noqa: BLE001 — fall through to next source
            hint = " (network/TLS — 'logs.' endpoint likely blocked or proxied)" \
                if _is_transport_error(exc) else ""
            failures.append(f"{source}: {type(exc).__name__}: {exc}{hint}")
            R.warning(f"Source '{source}' unavailable{hint} → {type(exc).__name__}")

    raise AssertionError(
        "Could not obtain the Glue run log from any source.\n  - "
        + "\n  - ".join(failures)
        + "\nQuick unblock: download the log stream to a file and set "
          "GLUE_LOG_SOURCE=file GLUE_LOG_FILE=<path>."
    )
