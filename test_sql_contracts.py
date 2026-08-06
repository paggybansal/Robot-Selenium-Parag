"""Static contracts — SQL resources, rule test data, environment config, Glue args.

No DB, no AWS, no fixtures. Runs in ~1s anywhere (dev laptop, PR gate, air-gapped).
Catches the classes of defect that otherwise surface 20+ minutes into a Glue run:
  • SQL placeholder / parameter count mismatches   (the 'TOP (?)' defect)
  • drift between the candidate query and the count query
  • malformed rule test data                        (the '00007''00009' defect)
  • missing config attributes                       (the 'glue_log_url' defect)
  • Glue job parameters that would invalidate rule_count assertions
"""
from __future__ import annotations

import pytest

from action_api_framework.config.aws_config import (
    GLUE_INTERNAL_ARGUMENT_NAMES,
    VALID_LOG_SOURCES,
    load_aws_suppression_config,
)
from action_api_framework.testdata.suppression_rules_data import (
    DIRECTORY_SUPPRESSION_RULES,
    get_rule,
)
from action_api_framework.utils.sql_loader import (
    assert_param_count,
    bind_in_clause,
    bind_literal_int,
    count_placeholders,
    load_sql,
)

RULE_KEY = "rule_15_active_military"
RULE = DIRECTORY_SUPPRESSION_RULES[RULE_KEY]


def _candidate_sql(top_n: int = 5) -> str:
    sql = load_sql("symplr/suppression_rule_candidates.sql")
    sql = bind_literal_int(sql, "top_n", top_n)
    return bind_in_clause(sql, "qualifying_value_placeholders",
                          RULE.qualifying_udf_values, "?")


def _count_sql() -> str:
    return bind_in_clause(load_sql("symplr/suppression_rule_candidate_count.sql"),
                          "qualifying_value_placeholders",
                          RULE.qualifying_udf_values, "?")


# ════════════════════════════════════════════════════════════
# SQL resources
# ════════════════════════════════════════════════════════════
class TestSqlResourceContracts:

    def test_candidate_query_marker_count_matches_params(self):
        """udf_field_name + trigger_value + N codes. TOP is a bound literal, not a marker."""
        sql = _candidate_sql()
        assert count_placeholders(sql, "?") == 2 + len(RULE.qualifying_udf_values)

    def test_candidate_query_has_no_unbound_tokens(self):
        sql = _candidate_sql()
        assert "{" not in sql and "}" not in sql, f"Unbound token left in SQL:\n{sql}"

    def test_candidate_query_top_is_a_literal_not_a_marker(self):
        """Regression: 'TOP (?)' is not counted by ODBC → off-by-one at execute time."""
        raw = load_sql("symplr/suppression_rule_candidates.sql")
        assert "TOP (?)" not in raw.upper().replace(" ", "").replace("TOP(?)", "TOP (?)")
        assert "{top_n}" in raw, "TOP must use the {top_n} bound-literal token"
        assert "TOP (5)" in bind_literal_int(raw, "top_n", 5)

    def test_candidate_count_query_marker_count_matches_params(self):
        assert count_placeholders(_count_sql(), "?") == 2 + len(RULE.qualifying_udf_values)

    def test_directory_state_query_takes_one_param(self):
        assert count_placeholders(
            load_sql("symplr/practitioner_directory_state.sql"), "?") == 1

    @pytest.mark.parametrize("resource,expected", [
        ("statusdb/process_status_by_process_id.sql", 1),
        ("statusdb/process_status_by_business_value.sql", 2),
    ])
    def test_statusdb_queries_take_expected_params(self, resource, expected):
        assert count_placeholders(load_sql(resource), "%s") == expected

    def test_count_and_candidate_queries_share_predicates(self):
        """The rule_count assertion is only meaningful while these agree."""
        def predicates(text: str) -> str:
            body = text.split("FROM", 1)[1].split("ORDER BY")[0]
            return " ".join(line.split("--")[0].strip()
                            for line in body.splitlines() if line.split("--")[0].strip())
        assert predicates(load_sql("symplr/suppression_rule_candidates.sql")) == \
               predicates(load_sql("symplr/suppression_rule_candidate_count.sql")), (
            "suppression_rule_candidates.sql and suppression_rule_candidate_count.sql "
            "have drifted — rule_count == candidate_count would be comparing "
            "different populations")

    def test_count_query_uses_count_distinct(self):
        assert "COUNT(DISTINCT" in _count_sql().upper(), \
            "Must not multiply-count practitioners with several locations / UDF values"

    def test_queries_only_read(self):
        forbidden = ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "DROP ", "TRUNCATE ", "ALTER ")
        for resource in ("symplr/suppression_rule_candidates.sql",
                         "symplr/suppression_rule_candidate_count.sql",
                         "symplr/practitioner_directory_state.sql",
                         "statusdb/process_status_by_process_id.sql",
                         "statusdb/process_status_by_business_value.sql"):
            upper = load_sql(resource).upper()
            found = [kw.strip() for kw in forbidden if kw in upper]
            assert not found, f"{resource} contains write statement(s): {found}"

    def test_candidate_query_filters_on_directory_visibility(self):
        """Step 1's precondition (InDirectory='Y') must be in the query, not just asserted."""
        upper = load_sql("symplr/suppression_rule_candidates.sql").upper()
        assert "INDIRECTORY" in upper and "'Y'" in upper


# ════════════════════════════════════════════════════════════
# sql_loader behaviour
# ════════════════════════════════════════════════════════════
class TestSqlLoaderBehaviour:

    def test_count_placeholders_ignores_comments_and_literals(self):
        sql = ("-- ? in a line comment\n"
               "SELECT '?' AS literal /* ? in a block */\n"
               "FROM t WHERE a = ? AND b = ?")
        assert count_placeholders(sql, "?") == 2

    def test_count_placeholders_handles_escaped_quotes(self):
        assert count_placeholders("SELECT 'it''s ?' WHERE a = ?", "?") == 1

    def test_count_placeholders_supports_pyformat(self):
        assert count_placeholders("SELECT 1 WHERE a = %s AND b = %s", "%s") == 2

    def test_bind_literal_int_rejects_non_integer(self):
        with pytest.raises(ValueError):
            bind_literal_int("SELECT TOP ({top_n}) 1", "top_n", "5; DROP TABLE x")

    def test_bind_literal_int_enforces_range(self):
        with pytest.raises(ValueError):
            bind_literal_int("SELECT TOP ({top_n}) 1", "top_n", 0, minimum=1)
        with pytest.raises(ValueError):
            bind_literal_int("SELECT TOP ({top_n}) 1", "top_n", 99999, maximum=1000)

    def test_bind_literal_int_requires_the_token(self):
        with pytest.raises(ValueError):
            bind_literal_int("SELECT TOP 5 1", "top_n", 5)

    def test_bind_in_clause_rejects_empty_values(self):
        with pytest.raises(ValueError):
            bind_in_clause("SELECT 1 WHERE v IN ({vals})", "vals", [])

    def test_bind_in_clause_requires_the_token(self):
        with pytest.raises(ValueError):
            bind_in_clause("SELECT 1", "vals", ["a"])

    def test_bind_in_clause_emits_only_placeholders(self):
        out = bind_in_clause("SELECT 1 WHERE v IN ({vals})", "vals", ["a", "b", "c"])
        assert out.endswith("(?, ?, ?)")
        assert "a" not in out, "Values must bind, never be inlined"

    def test_assert_param_count_reports_actionable_message(self):
        with pytest.raises(ValueError) as exc:
            assert_param_count("SELECT 1 WHERE a = ?", ("x", "y"), label="demo")
        message = str(exc.value)
        assert "demo" in message and "1 '?'" in message and "2 parameter" in message

    def test_load_sql_rejects_path_traversal(self):
        with pytest.raises((ValueError, FileNotFoundError)):
            load_sql("../../../../etc/passwd")

    def test_load_sql_raises_for_missing_resource(self):
        with pytest.raises(FileNotFoundError):
            load_sql("symplr/does_not_exist.sql")


# ════════════════════════════════════════════════════════════
# rule test data
# ════════════════════════════════════════════════════════════
class TestRuleRegistry:

    def test_registry_is_not_empty(self):
        assert DIRECTORY_SUPPRESSION_RULES

    def test_claim_hold_reason_codes_are_distinct_and_well_formed(self):
        """Regression: the source doc rendered '00007''00009' as one token."""
        codes = RULE.qualifying_udf_values
        assert len(codes) == len(set(codes)), f"Duplicate codes: {codes}"
        for code in codes:
            assert isinstance(code, str) and code.isdigit() and len(code) == 5, \
                f"Malformed claim-hold code: {code!r}"

    @pytest.mark.parametrize("key", sorted(DIRECTORY_SUPPRESSION_RULES))
    def test_every_rule_is_completely_specified(self, key):
        rule = DIRECTORY_SUPPRESSION_RULES[key]
        assert rule.key == key, f"Registry key '{key}' != rule.key '{rule.key}'"
        assert int(rule.rule_id) > 0
        assert rule.description.strip()
        assert rule.trigger_field and rule.trigger_value
        assert rule.udf_field_name and rule.qualifying_udf_values
        assert rule.indirectory_column
        assert rule.outbound_column and rule.outbound_expected_value
        assert rule.outbound_key_columns, "Need at least one key column to locate the row"
        assert rule.expected_indirectory_values

    @pytest.mark.parametrize("key", sorted(DIRECTORY_SUPPRESSION_RULES))
    def test_expected_values_are_upper_case_normalised(self, key):
        rule = DIRECTORY_SUPPRESSION_RULES[key]
        assert all(v == v.strip().upper() for v in rule.expected_indirectory_values), \
            "expected_indirectory_values must be pre-normalised (compared upper-cased)"

    @pytest.mark.parametrize("key", sorted(DIRECTORY_SUPPRESSION_RULES))
    def test_accepted_rule_ids_cover_str_and_int(self, key):
        rule = DIRECTORY_SUPPRESSION_RULES[key]
        assert str(rule.rule_id) in rule.rule_ids_accepted
        assert int(rule.rule_id) in rule.rule_ids_accepted, \
            "StatusDB payloads may carry the rule id as int or str"

    def test_get_rule_error_names_the_available_keys(self):
        with pytest.raises((KeyError, ValueError)) as exc:
            get_rule("rule_99_not_real")
        assert RULE_KEY in str(exc.value), \
            "Unknown-rule error should list the available keys"


# ════════════════════════════════════════════════════════════
# environment configuration
# ════════════════════════════════════════════════════════════
class TestConfigContract:

    REQUIRED_ATTRIBUTES = (
        "environment", "profile_name", "region_name",
        "glue_job_name", "glue_job_arguments", "verify_glue_arguments",
        "log_group_name", "glue_log_source", "glue_log_file", "glue_log_dir",
        "glue_log_url",
        "outbound_bucket", "outbound_prefix", "processed_prefix",
        "outbound_file_pattern", "outbound_delimiter", "outbound_has_header",
        "glue_timeout", "s3_timeout", "dataloader_timeout", "log_read_timeout",
        "poll_seconds",
        "trigger_glue_job", "restore_state", "enforce_rule_count_match",
        "enforce_row_count_match", "enforce_outbound_freshness",
    )
    REQUIRED_METHODS = ("describe", "resolve_log_target")

    def test_config_exposes_every_attribute_the_tests_use(self):
        cfg = load_aws_suppression_config()
        missing = [a for a in self.REQUIRED_ATTRIBUTES if not hasattr(cfg, a)]
        assert not missing, f"AwsSuppressionConfig is missing: {missing}"

    def test_config_exposes_required_methods(self):
        cfg = load_aws_suppression_config()
        missing = [m for m in self.REQUIRED_METHODS if not callable(getattr(cfg, m, None))]
        assert not missing, f"AwsSuppressionConfig is missing method(s): {missing}"

    def test_describe_has_no_none_values(self):
        assert all(v is not None for v in load_aws_suppression_config().describe().values())

    def test_log_source_is_valid(self):
        assert load_aws_suppression_config().glue_log_source in VALID_LOG_SOURCES

    def test_bucket_and_prefix_are_well_formed(self):
        cfg = load_aws_suppression_config()
        assert not cfg.outbound_bucket.startswith("s3://"), \
            "outbound_bucket must be a bare bucket name"
        assert "/" not in cfg.outbound_bucket
        assert cfg.outbound_prefix.endswith("/"), \
            "outbound_prefix must end with '/' so prefix matching cannot span keys"
        assert not cfg.outbound_prefix.startswith("/")

    def test_timeouts_are_sane(self):
        cfg = load_aws_suppression_config()
        for name in ("glue_timeout", "s3_timeout", "dataloader_timeout",
                     "log_read_timeout", "poll_seconds"):
            assert getattr(cfg, name) > 0, f"{name} must be positive"
        assert cfg.poll_seconds < min(cfg.glue_timeout, cfg.s3_timeout,
                                      cfg.dataloader_timeout, cfg.log_read_timeout), \
            "poll interval must be shorter than every timeout it drives"

    def test_file_source_requires_a_path(self):
        cfg = load_aws_suppression_config()
        if cfg.glue_log_source == "file":
            assert cfg.glue_log_file or cfg.glue_log_dir, \
                "GLUE_LOG_SOURCE=file needs GLUE_LOG_FILE or GLUE_LOG_DIR"

    def test_pasted_log_url_matches_configured_group_and_region(self):
        load_aws_suppression_config().resolve_log_target()   # raises on mismatch


# ════════════════════════════════════════════════════════════
# Glue job parameters
# ════════════════════════════════════════════════════════════
class TestGlueArgumentContract:

    def test_required_parameters_present(self):
        args = load_aws_suppression_config().glue_job_arguments
        assert args.get("--mode") == "daily", f"--mode must be 'daily', got {args.get('--mode')}"
        assert args.get("--lastruntime"), "--lastruntime is required"

    def test_lastruntime_forces_full_scan_when_rule_count_is_enforced(self):
        """A real watermark emits only deltas, which invalidates
        rule_count == Symplr candidate count."""
        cfg = load_aws_suppression_config()
        lastruntime = cfg.glue_job_arguments.get("--lastruntime", "")
        if cfg.enforce_rule_count_match and not lastruntime.startswith("9999"):
            pytest.fail(
                f"--lastruntime='{lastruntime}' is not a full-scan watermark, so "
                f"ENFORCE_RULE_COUNT_MATCH must be false")

    def test_argument_keys_are_well_formed(self):
        args = load_aws_suppression_config().glue_job_arguments
        assert all(k.startswith("--") for k in args), f"Malformed keys: {list(args)}"
        assert all(isinstance(v, str) for v in args.values()), \
            "start_job_run requires string values"

    def test_internal_glue_parameter_usage_is_visible(self):
        args = load_aws_suppression_config().glue_job_arguments
        internal = set(args) & GLUE_INTERNAL_ARGUMENT_NAMES
        if internal:
            print(f"NOTE: {sorted(internal)} are documented as internal Glue parameters; "
                  f"runtime echo verification (test_02) guards against them being stripped.")
