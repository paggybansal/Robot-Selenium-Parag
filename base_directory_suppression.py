from __future__ import annotations

from typing import Any, Dict, Iterable

import pytest

from action_api_framework.utils.console_reporter import ConsoleReporter as R
from action_api_framework.utils.glue_log_parser import parse_glue_log
from action_api_framework.utils.glue_log_source import read_run_log
from action_api_framework.utils.outbound_file_parser import OutboundFile
from action_api_framework.utils.s3_search import wait_for_matching_object


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_s3_prefix(prefix: str) -> str:
    value = _text(prefix).lstrip("/")
    return value if not value or value.endswith("/") else f"{value}/"


def _artifacts_for_prefix(artifacts, prefix: str):
    expected_prefix = _normalise_s3_prefix(prefix)

    return [
        artifact
        for artifact in artifacts
        if artifact.key.lstrip("/").startswith(expected_prefix)
    ]


def _read_s3_text(aws_s3_manager, bucket: str, key: str) -> str:
    """Read an S3 CSV/text object without creating invalid Windows filenames."""
    response = aws_s3_manager.s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )

    stream = response["Body"]
    try:
        data = stream.read()
    finally:
        stream.close()

    return data.decode("utf-8-sig", errors="replace")


def _same_identifier(actual: Any, expected: Any) -> bool:
    """Compare CSV/DB identifiers without breaking leading-zero NPI values."""
    left = _text(actual)
    right = _text(expected)

    if left == right:
        return True

    # Useful for NPI-like numeric identifiers where one side may lose zeros.
    if left.isdigit() and right.isdigit():
        return (left.lstrip("0") or "0") == (right.lstrip("0") or "0")

    return False


class BaseDirectorySuppression:
    """Shared suppression workflow.

    This class is intentionally not collected by pytest because its name does
    not begin with Test. Concrete entity classes set RULE_KEY.
    """

    RULE_KEY: str = ""

    # ── Step 1 ────────────────────────────────────────────────────────
    def test_01_candidate_meets_rule_preconditions(
            self,
            rule,
            candidate,
            symplr_repo,
            scenario,
    ):
        R.header(
            f"STEP 1 — {rule.entity_type.upper()} RULE {rule.rule_id}: "
            "DATABASE PRECONDITIONS"
        )

        actual_trigger = _text(candidate.get(rule.trigger_field)).upper()
        expected_trigger = _text(rule.trigger_value).upper()

        assert actual_trigger == expected_trigger, (
            f"{rule.trigger_field}='{candidate.get(rule.trigger_field)}', "
            f"expected '{rule.trigger_value}'"
        )

        qualifying_value = _text(candidate.get("QualifyingValue"))
        assert qualifying_value in rule.qualifying_udf_values, (
            f"{rule.udf_field_name}='{qualifying_value}' is not in "
            f"{rule.qualifying_udf_values}"
        )

        for column in rule.candidate_identity_columns:
            assert _text(candidate.get(column)), (
                f"Candidate is missing required identity field '{column}': "
                f"{candidate}"
            )

        candidate_count = symplr_repo.count_candidates_for_rule(rule)

        R.field("Entity", rule.entity_type)
        R.field("Qualifying candidate count", candidate_count)
        R.field("Trigger", f"{rule.trigger_field}={rule.trigger_value}")
        R.field(rule.udf_field_name, qualifying_value)

        for column in rule.candidate_identity_columns:
            R.field(column, candidate[column])

        scenario.put("candidate", candidate)
        scenario.put(
            "outbound_search_value",
            _text(candidate[rule.outbound_search_field]),
        )
        scenario.put("expected_rule_count", candidate_count)
        scenario.complete("candidate")

        R.success("Candidate meets suppression-rule preconditions")

    # ── Step 2 ────────────────────────────────────────────────────────
    def test_02_pdqa_glue_job_completes_successfully(
            self,
            aws_cfg,
            scenario,
            glue_run,
            rule,
    ):
        scenario.require("candidate")

        R.header(
            f"STEP 6a — {rule.entity_type.upper()} GLUE JOB "
            f"(RULE {rule.rule_id})"
        )

        if glue_run["state"] == "SKIPPED_TRIGGER":
            R.warning(
                "Glue trigger disabled. S3 fallback mode will be used."
            )
            scenario.complete("glue")
            return

        issues = glue_run.get("argument_issues") or []
        assert not issues, (
            "Glue job parameters were not applied:\n  - "
            + "\n  - ".join(issues)
            + f"\nRequested: {glue_run.get('arguments')}"
        )

        assert glue_run["state"] == "SUCCEEDED", (
            f"Glue job did not succeed: state={glue_run['state']}, "
            f"run_id={glue_run.get('job_run_id')}"
        )

        R.field("Glue Job", glue_run.get("job_name", "—"))
        R.field("JobRunId", glue_run.get("job_run_id", "—"))
        R.success("Glue job SUCCEEDED")

        scenario.complete("glue")

    # ── Step 3 ────────────────────────────────────────────────────────
    def test_03_glue_log_reports_rule_and_entity_output(
            self,
            rule,
            aws_cfg,
            scenario,
            glue_run,
            glue_log_reader,
            glue_log_contract,
            aws_log_manager,
            aws_s3_manager,
    ):
        scenario.require("glue")

        R.header(
            f"STEP 6b — GLUE LOG: {rule.entity_type.upper()} "
            f"RULE {rule.rule_id}"
        )

        # Scheduled-flow fallback. No log/run ID is available.
        if not glue_run.get("job_run_id"):
            search_value = scenario.get("outbound_search_value")

            R.warning(
                "No JobRunId available; locating S3 file using the configured "
                "entity output prefix."
            )

            key = wait_for_matching_object(
                aws_s3_manager,
                bucket=aws_cfg.outbound_bucket,
                prefix=_normalise_s3_prefix(rule.outbound_s3_prefix),
                since=glue_run["started_at"],
                pattern=aws_cfg.outbound_file_pattern,
                timeout_seconds=aws_cfg.s3_timeout,
                poll_seconds=aws_cfg.poll_seconds,
                must_contain=search_value,
            )

            process_id_match = glue_log_contract.process_id_in_filename.search(
                key.rsplit("/", 1)[-1]
            )

            assert process_id_match, (
                f"Could not extract process UUID from outbound filename: {key}"
            )

            scenario.put(
                "outbound_keys",
                [(aws_cfg.outbound_bucket, key)],
            )
            scenario.put("process_id", process_id_match.group(0))
            scenario.put("glue_report", None)
            scenario.put("log_source", "scheduled-flow-fallback")
            scenario.put("run_id_verified", False)
            scenario.complete("glue_log")
            return

        # No GLUE_LOG_URL / resolve_log_target / url_stream approach.
        log = read_run_log(
            mode=aws_cfg.glue_log_source,
            run_id=glue_run["job_run_id"],
            log_group=aws_cfg.log_group_name,
            sentinel=glue_log_contract.completion_sentinel,
            timeout_seconds=aws_cfg.log_read_timeout,
            poll_seconds=aws_cfg.poll_seconds,
            reader=glue_log_reader,
            log_manager=aws_log_manager,
            log_file=aws_cfg.glue_log_file or None,
            log_dir=aws_cfg.glue_log_dir or None,
        )

        R.field("Log Source", log.source)
        R.field("Log Artifact", log.artifact or "—")
        R.field(
            "Run ID Verified",
            "yes" if log.run_id_verified else "no (S3 freshness guard applies)",
        )

        report = parse_glue_log(log.text, glue_log_contract)
        R.table(report.as_table_rows(), headers=["Metric", "Value"])

        actual_rule_count = report.rule_count(rule.rule_id)

        assert actual_rule_count is not None, (
            f"Glue log does not report AppliedRule={rule.rule_id}. "
            f"Applied rules: {report.applied_rules or 'none'}"
        )

        assert actual_rule_count >= 1, (
            f"Glue log reports Rule {rule.rule_id} with "
            f"rule_count={actual_rule_count}"
        )

        assert report.records_to_s3 is not None and report.records_to_s3 >= 1, (
            f"Glue log reports records_to_s3={report.records_to_s3}; "
            "no output records were written."
        )

        expected_population = scenario.get("expected_rule_count")
        if expected_population != actual_rule_count:
            message = (
                f"Glue rule_count={actual_rule_count}, but source DB reports "
                f"{expected_population} qualifying {rule.entity_type} record(s)."
            )
            if aws_cfg.enforce_rule_count_match:
                pytest.fail(message)
            R.warning(message)
        else:
            R.success(
                f"Glue rule_count matches source DB qualifying count "
                f"({expected_population})"
            )

        prefix = _normalise_s3_prefix(rule.outbound_s3_prefix)

        assert report.artifacts, (
            "No S3 output artifacts were found in the Glue log."
        )

        entity_artifacts = _artifacts_for_prefix(report.artifacts, prefix)

        assert entity_artifacts, (
            f"No {rule.entity_type} S3 output file found under prefix "
            f"'{prefix}'.\nAll logged artifacts:\n"
            + "\n".join(
                f"  - s3://{artifact.bucket}/{artifact.key}"
                for artifact in report.artifacts
            )
        )

        process_ids = sorted({
            artifact.process_id
            for artifact in entity_artifacts
            if artifact.process_id
        })

        assert process_ids, (
            f"{rule.entity_type} output file found, but process UUID was not "
            "found in its filename(s):\n"
            + "\n".join(
                f"  - {artifact.filename}"
                for artifact in entity_artifacts
            )
        )

        assert len(process_ids) == 1, (
            f"Expected exactly one process UUID for this {rule.entity_type} "
            f"flow, found {process_ids}.\n"
            + "\n".join(
                f"  - chunk={artifact.chunk}, process_id={artifact.process_id}, "
                f"key={artifact.key}"
                for artifact in entity_artifacts
            )
        )

        for artifact in entity_artifacts:
            assert artifact.bucket == aws_cfg.outbound_bucket, (
                f"Artifact bucket '{artifact.bucket}' does not match configured "
                f"outbound bucket '{aws_cfg.outbound_bucket}'."
            )

            assert artifact.key.startswith(prefix), (
                f"Artifact key '{artifact.key}' is outside '{prefix}'."
            )

        R.sub_section(f"{rule.entity_type.title()} Output Files")
        R.table(
            [
                [
                    artifact.chunk,
                    artifact.bucket,
                    artifact.key,
                    artifact.filename,
                    artifact.process_id,
                ]
                for artifact in entity_artifacts
            ],
            headers=["Chunk", "Bucket", "S3 Key", "Filename", "Process ID"],
        )

        scenario.put("glue_report", report)
        scenario.put("flow_artifacts", entity_artifacts)
        scenario.put("process_id", process_ids[0])
        scenario.put(
            "outbound_keys",
            list(dict.fromkeys(
                (artifact.bucket, artifact.key)
                for artifact in entity_artifacts
            )),
        )
        scenario.put("log_source", log.source)
        scenario.put("run_id_verified", log.run_id_verified)
        scenario.complete("glue_log")

        R.success(
            f"Selected {len(entity_artifacts)} {rule.entity_type} output file(s)"
        )

    # ── Step 4 ────────────────────────────────────────────────────────
    def test_04_outbound_files_exist_in_s3(
            self,
            aws_cfg,
            aws_s3_manager,
            scenario,
            glue_run,
    ):
        scenario.require("glue_log")

        R.header("STEP 6c — OUTBOUND FILE EXISTS IN S3")

        started_at = glue_run["started_at"]
        rows, missing, stale = [], [], []

        for bucket, key in scenario.get("outbound_keys"):
            exists = aws_s3_manager.object_exists(bucket, key)

            size = "—"
            last_modified = "—"

            if exists:
                metadata = aws_s3_manager.s3_client.head_object(
                    Bucket=bucket,
                    Key=key,
                )
                size = metadata.get("ContentLength", 0)
                last_modified = metadata.get("LastModified")

                if not size:
                    missing.append(f"{key} (0 bytes)")

                if last_modified and last_modified < started_at:
                    stale.append(
                        f"{key} (LastModified {last_modified} < run {started_at})"
                    )
            else:
                missing.append(f"{key} (not found)")

            rows.append([
                bucket,
                key,
                "✔" if exists else "✘",
                size,
                last_modified,
            ])

        R.table(
            rows,
            headers=["Bucket", "Key", "Exists", "Bytes", "LastModified"],
        )

        assert not missing, (
            f"Outbound file(s) missing or empty: {missing}"
        )

        if stale:
            message = (
                "Outbound object(s) predate this Glue run: "
                f"{stale}"
            )
            if (
                aws_cfg.enforce_outbound_freshness
                or not scenario.get("run_id_verified", True)
            ):
                pytest.fail(message)
            R.warning(message)
        else:
            R.success("Outbound S3 objects are newer than the Glue run start")

        scenario.complete("outbound_file")

    # ── Step 5 ────────────────────────────────────────────────────────
    def test_05_outbound_file_contains_selected_entity(
            self,
            rule,
            aws_cfg,
            aws_s3_manager,
            scenario,
            candidate,
    ):
        scenario.require("outbound_file")

        R.header(
            f"STEP 6d — {rule.entity_type.upper()} OUTBOUND FILE CONTENT"
        )

        matched_files = 0
        checked_files = 0

        for bucket, key in scenario.get("outbound_keys"):
            body = _read_s3_text(aws_s3_manager, bucket, key)

            outbound = OutboundFile(
                key,
                body,
                delimiter=aws_cfg.outbound_delimiter,
                has_header=aws_cfg.outbound_has_header,
            )

            checked_files += 1
            filename = key.rsplit("/", 1)[-1]

            R.sub_section(f"Outbound File: {filename}")
            R.field("Rows", len(outbound))
            R.field("Headers", ", ".join(outbound.headers))

            # Resolve configured CSV headers once.
            resolved_columns: Dict[str, str] = {}

            for candidate_column, csv_column in rule.outbound_identity_map:
                actual_header = outbound.column(csv_column)

                assert actual_header, (
                    f"Expected CSV column '{csv_column}' is missing from '{key}'. "
                    f"Headers: {outbound.headers}"
                )

                resolved_columns[candidate_column] = actual_header

            matching_rows = [
                row
                for row in outbound.rows
                if all(
                    _same_identifier(
                        row.get(resolved_columns[candidate_column]),
                        candidate.get(candidate_column),
                    )
                    for candidate_column, _ in rule.outbound_identity_map
                )
            ]

            if not matching_rows:
                R.info(
                    f"Selected {rule.entity_type} identity is not in '{filename}'; "
                    "checking the next output chunk."
                )
                continue

            matched_files += 1

            R.success(
                f"Found selected {rule.entity_type} record in '{filename}' "
                f"({len(matching_rows)} matching row(s))"
            )

            # Optional entity-specific outbound value validation.
            if rule.outbound_column:
                actual_header = outbound.column(rule.outbound_column)

                assert actual_header, (
                    f"Expected CSV column '{rule.outbound_column}' is missing "
                    f"from '{key}'. Headers: {outbound.headers}"
                )

                expected_value = _text(
                    rule.outbound_expected_value
                ).casefold()

                actual_values = {
                    _text(row.get(actual_header)).casefold()
                    for row in matching_rows
                }

                assert expected_value in actual_values, (
                    f"Matching {rule.entity_type} row exists in '{filename}', "
                    f"but '{rule.outbound_column}' is not "
                    f"'{rule.outbound_expected_value}'. "
                    f"Actual values: {sorted(actual_values)}"
                )

                R.success(
                    f"Validated {rule.outbound_column}="
                    f"{rule.outbound_expected_value}"
                )

            for row_number, row in enumerate(matching_rows[:3], start=1):
                R.field(
                    f"Matching CSV Row {row_number}",
                    ", ".join(
                        f"{header}={row.get(header, '')}"
                        for header in outbound.headers
                    ),
                )

        assert checked_files > 0, "No outbound files were checked."

        assert matched_files > 0, (
            f"Selected {rule.entity_type} record was not found in any "
            f"outbound file.\nFiles checked:\n"
            + "\n".join(
                f"  - s3://{bucket}/{key}"
                for bucket, key in scenario.get("outbound_keys")
            )
        )

        scenario.complete("outbound_content")

    # ── Step 7 ────────────────────────────────────────────────────────
    def test_07_dataloader_flow_reaches_terminal_state(
            self,
            status_repo,
            aws_cfg,
            scenario,
    ):
        scenario.require("outbound_content")

        process_id = scenario.get("process_id")

        R.header(f"STEP 9 — DATALOADER FLOW (process_id={process_id})")

        retries = max(
            3,
            aws_cfg.dataloader_timeout // max(aws_cfg.poll_seconds, 1),
        )

        # StatusDB must query by process UUID, not Practitioner NPI.
        # This works for Practitioner, Practice, and Facility.
        rows = status_repo.wait_for_rows_by_process_id(
            process_id,
            retries=retries,
            wait_seconds=aws_cfg.poll_seconds,
        )

        status_repo.print_rows("process_status (final)", rows)

        buckets = status_repo.classify(rows)

        R.status_line(
            "Data-Loader-File",
            ", ".join(buckets["Data-Loader-File"]) or "N/A",
        )
        R.status_line(
            "File-Record",
            ", ".join(buckets["File-Record"]) or "N/A",
        )

        assert not buckets["errors"], (
            f"StatusDB reported errors: {buckets['errors']}"
        )

        still_running = [
            row["sub_process_name"]
            for row in rows
            if _text(row.get("status")).upper() == "IN-PROGRESS"
        ]

        assert not still_running, (
            f"Dataloader still IN-PROGRESS after SLA: {still_running}"
        )

        assert buckets["Data-Loader-File"], (
            "No Data-Loader-File process status row found."
        )

        assert any(
            _text(status).upper() in ("COMPLETED", "SUCCESS")
            for status in buckets["Data-Loader-File"]
        ), (
            f"Dataloader did not complete: {buckets['Data-Loader-File']}"
        )

        R.success("Dataloader flow completed")
        scenario.complete("dataloader")

    # ── Step 8 ────────────────────────────────────────────────────────
    def test_08_final_database_state_is_updated(
            self,
            rule,
            candidate,
            scenario,
            symplr_repo,
    ):
        scenario.require("dataloader")

        R.header(
            f"STEP 11 — {rule.entity_type.upper()} FINAL DATABASE STATE"
        )

        row = symplr_repo.get_final_state(rule, candidate)

        assert row, (
            f"Final database row was not found for {rule.entity_type}. "
            f"Expected key columns: {rule.final_key_columns}; "
            f"candidate: {candidate}"
        )

        for key_column in rule.final_key_columns:
            expected = _text(candidate.get(key_column))
            actual = _text(row.get(key_column))

            assert actual == expected, (
                f"Final row {key_column}='{actual}', expected '{expected}'."
            )

            R.field(key_column, actual)

        actual_value = _text(row.get(rule.final_column)).upper()
        expected_values = {
            _text(value).upper()
            for value in rule.final_expected_values
        }

        R.field(rule.final_column, actual_value or "NULL")

        assert actual_value in expected_values, (
            f"{rule.entity_type} suppression did not complete. "
            f"Expected {rule.final_column} in {sorted(expected_values)}, "
            f"but found '{actual_value or 'NULL'}'."
        )

        R.success(
            f"{rule.entity_type.title()} final state validated: "
            f"{rule.final_column}={actual_value}"
        )

        scenario.put(
            f"final_{rule.final_column}",
            actual_value,
        )
        scenario.complete("final_state")
