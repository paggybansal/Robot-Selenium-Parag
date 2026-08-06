"""Signature/attribute contracts between the suppression modules.

Runs in milliseconds with no AWS or DB. Catches caller/callee drift BEFORE a
30-minute Glue run does.
"""
import inspect

import pytest

from action_api_framework.config.aws_config import load_aws_suppression_config
from action_api_framework.utils import cloudwatch_links, glue_log_source, glue_runner
from action_api_framework.utils.glue_log_parser import GlueRunReport, parse_glue_log
from action_api_framework.utils.glue_log_reader import GlueLogReader
from action_api_framework.utils.sql_loader import (
    assert_param_count, bind_in_clause, bind_literal_int, count_placeholders,
)


def _params(func):
    return set(inspect.signature(func).parameters)


@pytest.mark.suppression_rules
class TestModuleContracts:

    def test_read_run_log_accepts_every_kwarg_the_test_passes(self):
        expected = {"mode", "run_id", "log_group", "sentinel", "timeout_seconds",
                    "poll_seconds", "reader", "log_manager", "log_file", "log_dir",
                    "url_stream"}
        missing = expected - _params(glue_log_source.read_run_log)
        assert not missing, f"read_run_log() is missing kwargs: {sorted(missing)}"

    def test_glue_log_text_exposes_expected_fields(self):
        expected = {"text", "messages", "source", "artifact", "run_id_verified"}
        actual = set(glue_log_source.GlueLogText.__dataclass_fields__)
        assert expected <= actual, f"GlueLogText missing: {sorted(expected - actual)}"

    def test_glue_run_report_exposes_expected_api(self):
        for name in ("applied_rules", "records_to_s3", "total_chunks", "chunk_counts",
                     "artifacts", "error_lines"):
            assert name in GlueRunReport.__dataclass_fields__, f"GlueRunReport.{name} missing"
        for name in ("process_id", "process_ids", "rule_count", "as_table_rows"):
            assert hasattr(GlueRunReport, name), f"GlueRunReport.{name} missing"
        assert _params(parse_glue_log) == {"text", "contract"}

    def test_glue_log_reader_exposes_expected_api(self):
        for name in ("find_streams", "read_stream", "wait_for_run_log", "save"):
            assert callable(getattr(GlueLogReader, name, None)), f"GlueLogReader.{name} missing"
        assert {"log_group", "job_run_id", "sentinel", "timeout_seconds", "poll_seconds"} \
            <= _params(GlueLogReader.wait_for_run_log)

    def test_cloudwatch_links_exposes_expected_api(self):
        for name in ("build_stream_url", "build_group_search_url", "parse_console_url",
                     "console_encode", "console_decode", "validate_job_run_id"):
            assert callable(getattr(cloudwatch_links, name, None)), \
                f"cloudwatch_links.{name} missing"

    def test_glue_runner_exposes_expected_api(self):
        for name in ("start_glue_job", "get_job_run", "verify_arguments_applied"):
            assert callable(getattr(glue_runner, name, None)), f"glue_runner.{name} missing"

    def test_sql_loader_exposes_expected_api(self):
        for func in (bind_in_clause, bind_literal_int, count_placeholders, assert_param_count):
            assert callable(func)
        assert {"sql", "token", "value"} <= _params(bind_literal_int)

    def test_config_and_base_scenario_agree(self):
        """Every cfg attribute referenced in the scenario file must exist."""
        import re
        from pathlib import Path

        source = Path(
            inspect.getfile(
                __import__(
                    "action_api_framework.tests.suppression_rules.base_directory_suppression",
                    fromlist=["BaseDirectorySuppression"])
            )
        ).read_text(encoding="utf-8")

        cfg = load_aws_suppression_config()
        referenced = set(re.findall(r"aws_cfg\.([A-Za-z_][A-Za-z0-9_]*)", source))
        missing = {a for a in referenced if not hasattr(cfg, a)}
        assert not missing, f"base_directory_suppression.py uses undefined cfg attrs: {sorted(missing)}"
