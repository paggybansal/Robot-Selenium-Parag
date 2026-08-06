"""Offline validation of a manually downloaded Glue CloudWatch output log."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from action_api_framework.testdata.glue_log_contract import (
    PRACTITIONER_SUPPRESSION_LOG_CONTRACT,
)
from action_api_framework.utils.glue_log_parser import parse_glue_log


def test_downloaded_glue_log_contains_suppression_output():
    log_file = os.getenv("GLUE_LOG_FILE", "").strip()

    if not log_file:
        pytest.skip("Set GLUE_LOG_FILE to a downloaded Glue CloudWatch output log.")

    path = Path(log_file)
    assert path.is_file(), f"GLUE_LOG_FILE does not exist: {path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    report = parse_glue_log(text, PRACTITIONER_SUPPRESSION_LOG_CONTRACT)

    assert report.artifacts, (
        f"{path} does not appear to be the Glue output stream. "
        "Expected a line like: 'Chunk 1 written to s3://...'."
    )

    assert report.records_to_s3 and report.records_to_s3 > 0, (
        f"Glue log says records_to_s3={report.records_to_s3}"
    )

    assert report.process_id, (
        f"No single process UUID found in artifacts: "
        f"{[artifact.filename for artifact in report.artifacts]}"
    )

    print(f"\nGlue log file : {path}")
    print(f"Rules         : {report.applied_rules}")
    print(f"Records to S3 : {report.records_to_s3}")
    print(f"Process ID    : {report.process_id}")
    print("Artifacts:")
    for artifact in report.artifacts:
        print(f"  s3://{artifact.bucket}/{artifact.key}")
