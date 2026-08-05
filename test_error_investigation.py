"""Reusable directory-suppression scenario, correlated end-to-end via the
Glue job's own CloudWatch log:

  run_id → log → AppliedRule + record counts + s3:// key → process_id
        → S3 file content → StatusDB(process_id) → Dataloader → InDirectory
"""
from __future__ import annotations

import pytest

from action_api_framework.utils.console_reporter import ConsoleReporter as R
from action_api_framework.utils.glue_log_parser import parse_glue_log
from action_api_framework.utils.outbound_file_parser import OutboundFile
from action_api_framework.utils.s3_search import wait_for_matching_object


class BaseDirectorySuppression:
    """NOT collected (name doesn't start with 'Test'). Subclass + set RULE_KEY."""

    RULE_KEY: str = ""

    # ── QTest Step 1 ──────────────────────────────────────────────────
    def test_01_candidate_is_currently_visible_in_directory(self, rule, candidate,
                                                            symplr_repo, scenario):
        R.header(f"STEP 1 — RULE {rule.rule_id}: SYMPLR PRECONDITIONS")

        assert str(candidate.get(rule.trigger_field, "")).strip().upper() == rule.trigger_value, \
            (f"{rule.trigger_field}='{candidate.get(rule.trigger_field)}', "
             f"expected '{rule.trigger_value}'")
        assert str(candidate.get("QualifyingValue", "")).strip() in rule.qualifying_udf_values, \
            (f"{rule.udf_field_name}='{candidate.get('QualifyingValue')}' "
             f"not in {rule.qualifying_udf_values}")

        baseline = scenario.get("baseline_directory_state") or []
        assert baseline, f"No active PractitionerLocations for {candidate['PractitionerID']}"
        visible = [b for b in baseline
                   if symplr_repo.normalise_flag(b.get(rule.indirectory_column)) == "Y"]
        assert visible, (f"No location with {rule.indirectory_column}='Y'. Observed: "
                         f"{[symplr_repo.normalise_flag(b.get(rule.indirectory_column)) for b in baseline]}")

        expected_rule_count = symplr_repo.count_candidates(
            udf_field_name=rule.udf_field_name,
            trigger_value=rule.trigger_value,
            qualifying_values=rule.qualifying_udf_values,
        )
        R.field("Qualifying Practitioners (DB)", expected_rule_count)
        R.success(f"Candidate PractitionerID={candidate['PractitionerID']} "
                  f"NPI={candidate['NationalProviderID']} visible in directory "
                  f"({len(visible)}/{len(baseline)} locations)")

        scenario.put("npi", str(candidate["NationalProviderID"]).strip())
        scenario.put("expected_rule_count", expected_rule_count)
        scenario.complete("candidate")

    # ── QTest Step 6 (job) ────────────────────────────────────────────
    def test_02_pdqa_glue_job_completes_successfully(self, scenario, glue_run):
        scenario.require("candidate")
        R.header("STEP 6a — PDQA PRACTITIONER GLUE JOB")

        if glue_run["state"] == "SKIPPED_TRIGGER":
            R.warning("Glue trigger disabled — using scheduled flow output")
            scenario.complete("glue")
            return
        assert glue_run["state"] == "SUCCEEDED", \
            f"Glue job did not succeed: state={glue_run['state']} run_id={glue_run['job_run_id']}"
        R.success(f"Glue job SUCCEEDED (run_id={glue_run['job_run_id']})")
        scenario.complete("glue")

    # ── QTest Step 6 (log = rule + counts + S3 path + process_id) ─────
    def test_03_glue_log_reports_rule_applied_and_outbound_path(
            self, rule, aws_cfg, scenario, glue_run, glue_log_reader,
            glue_log_contract, aws_s3_manager):
        scenario.require("glue")
        R.header(f"STEP 6b — GLUE LOG: RULE {rule.rule_id}, RECORD COUNTS, S3 PATH")

        # Fallback path when we didn't trigger the job (no run id → no stream)
        if not glue_run.get("job_run_id"):
            key = wait_for_matching_object(
                aws_s3_manager, bucket=aws_cfg.outbound_bucket,
                prefix=aws_cfg.outbound_prefix, since=glue_run["started_at"],
                pattern=aws_cfg.outbound_file_pattern,
                timeout_seconds=aws_cfg.s3_timeout, poll_seconds=aws_cfg.poll_seconds,
                must_contain=scenario.get("npi"))
            pid = glue_log_contract.process_id_in_filename.search(key.rsplit("/", 1)[-1])
            assert pid, f"Could not extract process_id from filename: {key}"
            scenario.put("outbound_keys", [(aws_cfg.outbound_bucket, key)])
            scenario.put("process_id", pid.group(0))
            R.warning("Scheduled-flow fallback used (no Glue log correlation)")
            scenario.complete("glue_log")
            return

        text, messages = glue_log_reader.wait_for_run_log(
            aws_cfg.log_group_name, glue_run["job_run_id"],
            sentinel=glue_log_contract.completion_sentinel,
            timeout_seconds=aws_cfg.log_read_timeout, poll_seconds=aws_cfg.poll_seconds)
        log_path = glue_log_reader.save(messages, glue_run["job_run_id"])
        R.field("Log Artifact", log_path)

        report = parse_glue_log(text, glue_log_contract)
        R.table(report.as_table_rows(), headers=["Metric", "Value"])

        # 1) Rule applied — asserted at the source
        actual = report.rule_count(rule.rule_id)
        assert actual is not None, (
            f"Rule {rule.rule_id} not reported in the Glue log. "
            f"AppliedRules found: {report.applied_rules or 'none'}. Log: {log_path}")
        assert actual >= 1, f"Rule {rule.rule_id} reported with rule_count={actual}"
        R.success(f"Glue log reports AppliedRule={rule.rule_id}, rule_count={actual}")

        # 2) rule_count vs Symplr qualifying count
        expected = scenario.get("expected_rule_count")
        if actual == expected:
            R.success(f"rule_count matches Symplr qualifying practitioners ({expected})")
        else:
            msg = (f"rule_count={actual} but Symplr reported {expected} qualifying "
                   f"practitioner(s) — possible data race or rule-logic gap")
            if aws_cfg.enforce_rule_count_match:
                pytest.fail(msg)
            R.warning(msg)

        # 3) Rows written to S3
        assert report.records_to_s3 and report.records_to_s3 >= 1, \
            f"Glue log reports records_to_s3={report.records_to_s3}. Log: {log_path}"

        # 4) Outbound artifacts + single process_id
        assert report.artifacts, f"No 'Chunk N written to s3://…' line found. Log: {log_path}"
        assert report.process_ids, f"No process_id (UUID) in outbound filename(s): " \
                                   f"{[a.filename for a in report.artifacts]}"
        assert len(report.process_ids) == 1, \
            f"Expected one process_id, got {report.process_ids}"

        R.table([[a.chunk, a.bucket, a.key, a.process_id] for a in report.artifacts],
                headers=["Chunk", "Bucket", "Key", "Process ID"])
        for a in report.artifacts:
            assert a.bucket == aws_cfg.outbound_bucket, \
                f"Unexpected bucket '{a.bucket}', expected '{aws_cfg.outbound_bucket}'"
            assert a.key.startswith(aws_cfg.outbound_prefix.rstrip("/")), \
                f"Key '{a.key}' is outside configured prefix '{aws_cfg.outbound_prefix}'"

        if report.error_lines:
            R.warning(f"{len(report.error_lines)} error/exception line(s) in log "
                      f"(first: {report.error_lines[0][:160]})")

        scenario.put("glue_report", report)
        scenario.put("process_id", report.process_id)
        scenario.put("outbound_keys", [(a.bucket, a.key) for a in report.artifacts])
        scenario.complete("glue_log")

    # ── QTest Step 6 (file exists) ────────────────────────────────────
    def test_04_outbound_file_exists_in_dataloader_bucket(self, aws_s3_manager, scenario):
        scenario.require("glue_log")
        R.header("STEP 6c — OUTBOUND FILE EXISTS IN S3")

        rows, missing = [], []
        for bucket, key in scenario.get("outbound_keys"):
            exists = aws_s3_manager.object_exists(bucket, key)
            size = "—"
            if exists:
                meta = aws_s3_manager.s3_client.head_object(Bucket=bucket, Key=key)
                size = meta.get("ContentLength", 0)
                if not size:
                    missing.append(f"{key} (0 bytes)")
            else:
                missing.append(f"{key} (not found)")
            rows.append([bucket, key, "✔" if exists else "✘", size])

        R.table(rows, headers=["Bucket", "Key", "Exists", "Bytes"])
        assert not missing, f"Outbound file(s) missing/empty in S3: {missing}"
        R.success(f"All {len(rows)} outbound file(s) present and non-empty")
        scenario.complete("outbound_file")

    # ── QTest Step 7 ──────────────────────────────────────────────────
    def test_05_outbound_row_reports_suppressed_value(self, rule, aws_cfg,
                                                      aws_s3_manager, scenario):
        scenario.require("outbound_file")
        R.header("STEP 7 — OUTBOUND FILE CONTENT VALIDATION")

        npi = scenario.get("npi")
        report = scenario.get("glue_report")
        matched, total_rows = [], 0

        for bucket, key in scenario.get("outbound_keys"):
            # NOTE: read via get_object — filenames contain ':' which is illegal
            # in Windows local paths, so download_file() would fail on agents.
            outbound = OutboundFile(
                key, aws_s3_manager.read_file_content(bucket, key),
                delimiter=aws_cfg.outbound_delimiter,
                has_header=aws_cfg.outbound_has_header)
            total_rows += len(outbound)
            R.field(f"Rows in {outbound.key.rsplit('/', 1)[-1]}", len(outbound))
            R.field("Headers", ", ".join(outbound.headers))

            column = outbound.column(rule.outbound_column)
            assert column, (f"Column '{rule.outbound_column}' missing from outbound file. "
                            f"Headers: {outbound.headers} (schema drift?)")

            for row in outbound.find_rows(rule.outbound_key_columns, npi):
                matched.append((outbound, column, row))

        assert matched, (f"NPI={npi} not present in outbound file(s) "
                         f"{[k for _, k in scenario.get('outbound_keys')]}; "
                         f"searched {rule.outbound_key_columns}")

        R.table([[o.value(r, kc) for kc in rule.outbound_key_columns if o.column(kc)]
                 + [r.get(c)] for o, c, r in matched],
                headers=[kc for kc in rule.outbound_key_columns
                         if matched[0][0].column(kc)] + [rule.outbound_column])

        expected = rule.outbound_expected_value.strip().upper()
        bad = [r.get(c) for o, c, r in matched if str(r.get(c, "")).strip().upper() != expected]
        assert not bad, (f"{len(bad)}/{len(matched)} row(s) for NPI={npi} have "
                         f"{rule.outbound_column} != '{expected}': {bad}")
        R.success(f"All {len(matched)} outbound row(s) report "
                  f"{rule.outbound_column}='{expected}'")

        # File rows must equal what the log said it wrote
        if report and report.records_to_s3 is not None:
            msg = (f"Outbound row total {total_rows} != Glue-reported "
                   f"records_to_s3 {report.records_to_s3}")
            if total_rows == report.records_to_s3:
                R.success(f"Row count matches Glue log ({total_rows})")
            elif aws_cfg.enforce_row_count_match:
                pytest.fail(msg)
            else:
                R.warning(msg)

        scenario.complete("outbound_row")

    # ── QTest Step 8 ──────────────────────────────────────────────────
    def test_06_statusdb_payload_recorded_for_process_id(self, rule, status_repo,
                                                        aws_cfg, scenario):
        scenario.require("outbound_row")
        process_id = scenario.get("process_id")
        R.header(f"STEP 8 — STATUSDB (process_id={process_id})")

        retries = max(3, aws_cfg.dataloader_timeout // max(aws_cfg.poll_seconds, 1) // 4)
        rows = status_repo.wait_for_rows_by_process_id(
            process_id, retries=retries, wait_seconds=aws_cfg.poll_seconds)
        status_repo.print_rows("process_status", rows)
        assert rows, (f"No process_status rows for process_id={process_id} "
                      f"(parsed from outbound filename)")

        # Identity guard: the process must be about OUR practitioner
        npi = scenario.get("npi")
        business_values = {str(r.get("business_value", "")).strip() for r in rows}
        if npi in business_values:
            R.success(f"business_value confirms NPI={npi}")
        else:
            R.warning(f"NPI={npi} not in business_value {sorted(business_values)} — "
                      f"batch-level process row (verify granularity with dev team)")

        payload_ids = list(dict.fromkeys(
            r["payload_response_id"] for r in rows if r.get("payload_response_id")))
        assert payload_ids, f"No payload_response_id for process_id={process_id}"

        rule_ids, payloads = set(), []
        for pid in payload_ids:
            pr = status_repo.get_payload_response(pid)
            payloads.append(pr)
            assert pr.get("payload"), f"payload empty for payload_response_id={pid}"
            rule_ids |= status_repo.applied_rule_ids(pr.get("payload"))
            rule_ids |= status_repo.applied_rule_ids(pr.get("response"))

        R.field("Payload Response IDs", payload_ids)
        R.field("Rule IDs in payload", sorted(rule_ids) or "—")
        if rule_ids & rule.rule_ids_accepted:
            R.success(f"Rule {rule.rule_id} echoed in StatusDB payload")
        else:
            R.warning(f"Rule {rule.rule_id} not in StatusDB payload "
                      f"(already asserted from the Glue log in step 3)")

        blob = str(payloads).lower()
        if rule.indirectory_column.lower() in blob:
            R.success(f"'{rule.indirectory_column}' present in persisted payload")
        else:
            R.warning(f"'{rule.indirectory_column}' not visible in payload — "
                      f"confirm field naming with dev team")

        scenario.put("status_rows", rows)
        scenario.complete("statusdb")

    # ── QTest Step 9 ──────────────────────────────────────────────────
    def test_07_dataloader_flow_reaches_terminal_state(self, status_repo, aws_cfg,
                                                       scenario):
        scenario.require("statusdb")
        process_id = scenario.get("process_id")
        R.header(f"STEP 9 — DATALOADER FLOW (process_id={process_id})")

        retries = max(3, aws_cfg.dataloader_timeout // max(aws_cfg.poll_seconds, 1))
        rows = status_repo.wait_for_terminal_state_by_process_id(
            process_id, retries=retries, wait_seconds=aws_cfg.poll_seconds)
        status_repo.print_rows("process_status (final)", rows)

        buckets = status_repo.classify(rows)
        R.status_line("Validation", ", ".join(buckets["validation"]) or "N/A")
        R.status_line("DL-Integration", ", ".join(buckets["dl_integration"]) or "N/A")
        R.status_line("Dataloader", ", ".join(buckets["dataloader"]) or "N/A")

        assert not buckets["errors"], f"StatusDB reported errors: {buckets['errors']}"
        stuck = [r["sub_process_name"] for r in rows
                 if str(r.get("status", "")).strip().upper() == "IN-PROGRESS"]
        assert not stuck, f"Still IN-PROGRESS after SLA: {stuck}"
        assert buckets["dataloader"], "No dataloader sub-process recorded"
        assert any(s.strip().upper() in ("COMPLETED", "SUCCESS")
                   for s in buckets["dataloader"]), \
            f"Dataloader did not complete: {buckets['dataloader']}"

        R.success("Dataloader flow completed")
        scenario.complete("dataloader")

    # ── QTest Step 10 ─────────────────────────────────────────────────
    def test_08_directory_flag_suppressed_by_dataloader(self, rule, symplr_repo,
                                                        aws_cfg, scenario, candidate):
        scenario.require("dataloader")
        R.header("STEP 10 — SYMPLR DIRECTORY FLAG SUPPRESSED")

        rows = symplr_repo.wait_for_directory_flag(
            candidate["PractitionerID"], column=rule.indirectory_column,
            expected_values=rule.expected_indirectory_values,
            timeout_seconds=aws_cfg.dataloader_timeout, poll_seconds=aws_cfg.poll_seconds)
        assert rows, f"No active locations for PractitionerID={candidate['PractitionerID']}"

        baseline = {b.get("PractitionerLocationRecID"):
                    symplr_repo.normalise_flag(b.get(rule.indirectory_column))
                    for b in (scenario.get("baseline_directory_state") or [])}
        R.table([[r.get("PractitionerLocationRecID"), r.get("LocationID"),
                  baseline.get(r.get("PractitionerLocationRecID"), "—"),
                  symplr_repo.normalise_flag(r.get(rule.indirectory_column)),
                  symplr_repo.audit_user(r) or "—", symplr_repo.audit_time(r) or "—"]
                 for r in rows],
                headers=["LocationRecID", "LocationID", "Before", "After",
                         "Audit User", "Audit Time"])

        expected = {v.strip().upper() for v in rule.expected_indirectory_values}
        offenders = [(r.get("PractitionerLocationRecID"),
                      symplr_repo.normalise_flag(r.get(rule.indirectory_column)))
                     for r in rows
                     if symplr_repo.normalise_flag(r.get(rule.indirectory_column)) not in expected]
        assert not offenders, (f"{rule.indirectory_column} not suppressed for "
                              f"PractitionerID={candidate['PractitionerID']}. "
                              f"Expected {sorted(expected)}, got {offenders}")

        users = [symplr_repo.audit_user(r) or "" for r in rows]
        by_loader = [u for u in users if rule.expected_modified_by.lower() in u.lower()]
        if by_loader:
            R.success(f"Change attributed to dataloader: {sorted(set(by_loader))}")
        elif rule.enforce_modified_by:
            pytest.fail(f"Expected audit user '{rule.expected_modified_by}', got {users}")
        else:
            R.warning(f"Could not confirm '{rule.expected_modified_by}' in {users}")

        R.success(f"RULE {rule.rule_id} VERIFIED END-TO-END | "
                  f"PractitionerID={candidate['PractitionerID']} "
                  f"NPI={scenario.get('npi')} process_id={scenario.get('process_id')}")
        scenario.complete("verified")