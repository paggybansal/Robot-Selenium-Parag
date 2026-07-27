
"""
Scheduler Nightly Remediation — DB Validation Library.

Validates the nightly remediation pipeline by checking:
  1. Symplr query returns expected NPIs
  2. Splits appear in output S3 folder
  3. All sub-processes for each split reach 'Completed' status
  4. If any sub-process is 'Failed':
       - schema-validation-error → look up payload_response table for detailed reason
       - other errors → log the error string as-is
"""

import json
import random
from typing import Any, Dict, List, Optional, Set

from robot.api.deco import keyword

from resources.utils.db_connection import pg_connection, fetch_all_as_dicts
from resources.utils.reporting import R
from resources.utils.exceptions import IntegrationValidationError


# ══════════════════════════════════════════════════════════════════════
# QUERIES
# ══════════════════════════════════════════════════════════════════════

VALIDATE_SPLIT_SUB_PROCESSES = """
    SELECT
        id,
        sub_process_name,
        status,
        entity_name,
        business_key,
        business_value,
        error,
        payload_response_id,
        notes
    FROM process_status
    WHERE process_id = %s
    ORDER BY sub_process_name, id
"""

GET_PAYLOAD_RESPONSE = """
    SELECT response
    FROM payload_response
    WHERE payload_response_id = %s
"""

# ══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════

# The ONLY success status (case-insensitive comparison via .upper())
STATUS_COMPLETED = "COMPLETED"

# Exact error value that triggers payload_response lookup
SCHEMA_VALIDATION_ERROR = "schema-validation-error"


# ══════════════════════════════════════════════════════════════════════
# ERROR INVESTIGATION HELPERS
# ══════════════════════════════════════════════════════════════════════

def _fetch_payload_response(payload_response_id: str) -> str:
    """
    Look up the payload_response table for the detailed schema-validation error.

    Returns:
        Formatted response text (pretty-JSON if applicable),
        OR a "not found / error" message.
    """
    if not payload_response_id:
        return "(no payload_response_id available)"

    try:
        with pg_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(GET_PAYLOAD_RESPONSE, (payload_response_id,))
            result = cursor.fetchone()

        if not result:
            return f"(no payload_response record for id={payload_response_id})"

        # Handle tuple or dict cursor
        response = result[0] if isinstance(result, (tuple, list)) else result.get("response")

        if not response:
            return "(response field is empty)"

        # Pretty-print JSON if applicable
        if isinstance(response, dict):
            return json.dumps(response, indent=2)

        if isinstance(response, str) and response.strip().startswith(("{", "[")):
            try:
                return json.dumps(json.loads(response), indent=2)
            except json.JSONDecodeError:
                return response

        return str(response)

    except Exception as e:
        R.warning(f"⚠️  Failed to fetch payload_response {payload_response_id}: {e}")
        return f"(error fetching payload_response: {e})"


def _build_error_context(row: Dict[str, Any]) -> Dict[str, str]:
    """
    Build error context for a failed sub-process.

    Logic:
      - If error == "schema-validation-error" → fetch payload_response.response
      - Otherwise → use error field as-is
    """
    error_val = (row.get("error") or "").strip()
    pr_id     = row.get("payload_response_id") or ""
    notes_val = row.get("notes") or ""

    # ── Schema validation error → deep lookup ────────────────
    if error_val.lower() == SCHEMA_VALIDATION_ERROR.lower():
        detailed = _fetch_payload_response(str(pr_id))
        return {
            "error_type":          "schema-validation-error",
            "raw_error":           error_val,
            "detailed_reason":     detailed,
            "payload_response_id": str(pr_id),
            "notes":               str(notes_val),
        }

    # ── Any other error → use error string as reason ─────────
    return {
        "error_type":          error_val or "unknown",
        "raw_error":           error_val,
        "detailed_reason":     error_val if error_val else "(error field is empty)",
        "payload_response_id": str(pr_id),
        "notes":               str(notes_val),
    }


# ══════════════════════════════════════════════════════════════════════
# CORE VALIDATION — PER SPLIT
# ══════════════════════════════════════════════════════════════════════

@keyword("Validate Split Sub Processes")
def validate_split_sub_processes(split_process_id: str) -> Dict[str, Any]:
    """
    Validate all sub-processes for one split.

    Rules:
      - status = Completed  → ✅ pass
      - status = Failed/Error → 🔍 investigate error → FAIL test
      - status = anything else → ⏳ stuck → FAIL test

    Returns:
        {
            "split_process_id":     str,
            "total_sub_processes":  int,
            "completed":            int,
            "errored":              int,
            "stuck":                int,
            "error_details":        [{sub_process, business_value, error_type,
                                     raw_error, detailed_reason, payload_response_id, notes}, ...],
            "stuck_details":        [{sub_process, business_value, status}, ...],
            "status":               "PASS" | "FAIL",
        }
    """
    R.header(f"VALIDATE SPLIT process_id={split_process_id}", char="-")

    with pg_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(VALIDATE_SPLIT_SUB_PROCESSES, (split_process_id,))
        rows = fetch_all_as_dicts(cursor)

    if not rows:
        R.warning(f"⚠️  No sub-process records for split={split_process_id}")
        return {
            "split_process_id":    split_process_id,
            "total_sub_processes": 0,
            "completed":           0,
            "errored":             0,
            "stuck":               0,
            "error_details":       [],
            "stuck_details":       [],
            "status":              "FAIL",
            "reason":              "No records in process_status",
        }

    completed = errored = stuck = 0
    error_details: List[Dict[str, Any]] = []
    stuck_details: List[Dict[str, Any]] = []

    for row in rows:
        sub_name       = row.get("sub_process_name") or "unknown"
        raw_status     = (row.get("status") or "").strip()
        status_upper   = raw_status.upper()
        business_value = row.get("business_value") or ""

        if status_upper == STATUS_COMPLETED:
            completed += 1

        elif status_upper in {"FAILED", "ERROR"}:
            errored += 1
            ctx = _build_error_context(row)
            error_details.append({
                "sub_process":    sub_name,
                "business_value": business_value,
                "status":         raw_status,
                **ctx,
            })

        else:
            stuck += 1
            stuck_details.append({
                "sub_process":    sub_name,
                "business_value": business_value,
                "status":         raw_status or "(null)",
            })

    overall_status = "PASS" if (errored == 0 and stuck == 0) else "FAIL"

    # ── Summary Table ────────────────────────────────────────
    R.table(
        [
            ["Total sub-processes", len(rows)],
            ["Completed ✅",         completed],
            ["Errored ❌",           errored],
            ["Stuck ⏳",             stuck],
            ["Overall",              overall_status],
        ],
        headers=["Metric", "Value"],
    )

    # ── Detailed Error Report ────────────────────────────────
    if error_details:
        R.sub_section(f"❌ ERRORED sub-processes ({len(error_details)})")
        for idx, err in enumerate(error_details, start=1):
            R.warning(f"\n  [{idx}] {err['sub_process']}")
            R.info(f"       business_value:  {err['business_value']}")
            R.info(f"       status:          {err['status']}")
            R.info(f"       error:           {err['raw_error']}")

            # Only show payload_response_id when it matters (schema errors)
            if err["error_type"] == "schema-validation-error":
                R.info(f"       payload_response_id: {err['payload_response_id']}")
                R.info(f"       ─── payload_response.response ───")
                for line in str(err["detailed_reason"]).splitlines()[:20]:
                    R.info(f"       {line}")

            if err.get("notes"):
                R.info(f"       notes: {err['notes']}")

    # ── Stuck Records Report ─────────────────────────────────
    if stuck_details:
        R.sub_section(f"⏳ STUCK sub-processes ({len(stuck_details)})")
        for d in stuck_details[:10]:
            R.warning(
                f"  {d['sub_process']:30s} | status={d['status']:15s} | "
                f"business_value={d['business_value']}"
            )

    return {
        "split_process_id":    split_process_id,
        "total_sub_processes": len(rows),
        "completed":           completed,
        "errored":             errored,
        "stuck":               stuck,
        "error_details":       error_details,
        "stuck_details":       stuck_details,
        "status":              overall_status,
    }


# ══════════════════════════════════════════════════════════════════════
# AGGREGATE — VALIDATE ALL SPLITS
# ══════════════════════════════════════════════════════════════════════

@keyword("Validate All Splits")
def validate_all_splits(splits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate sub-processes for every split file.

    Args:
        splits: List of split dicts (from list_split_files_in_output_folder).
                Each must have "SplitProcessId" key.

    Returns:
        Aggregated result with per-split details and executive summary.
    """
    R.header("VALIDATE ALL SPLITS", char="=")
    R.field("Total splits", len(splits))

    results: List[Dict[str, Any]] = []
    splits_passed = splits_failed = 0
    tot_completed = tot_errored = tot_stuck = tot_sub = 0

    for idx, split in enumerate(splits, start=1):
        split_id = split["SplitProcessId"]
        R.info(f"\n[{idx}/{len(splits)}] Split {split_id}")

        result = validate_split_sub_processes(split_id)
        results.append(result)

        if result["status"] == "PASS":
            splits_passed += 1
        else:
            splits_failed += 1

        tot_completed += result["completed"]
        tot_errored   += result["errored"]
        tot_stuck     += result["stuck"]
        tot_sub       += result["total_sub_processes"]

    overall = "PASS" if splits_failed == 0 else "FAIL"

    # ── Overall Summary ──────────────────────────────────────
    R.header("SPLIT VALIDATION SUMMARY", char="=")
    R.table(
        [
            ["Total Splits",           len(splits)],
            ["Splits Passed ✅",        splits_passed],
            ["Splits Failed ❌",        splits_failed],
            ["",                       ""],
            ["Total Sub-processes",    tot_sub],
            ["Total Completed ✅",      tot_completed],
            ["Total Errored ❌",        tot_errored],
            ["Total Stuck ⏳",          tot_stuck],
            ["",                       ""],
            ["Overall Status",         overall],
        ],
        headers=["Metric", "Value"],
    )

    # ── Executive Summary: Group failures by error type ──────
    if splits_failed > 0:
        R.header("🚨 FAILURE BREAKDOWN BY ERROR TYPE", char="!")

        error_type_counts: Dict[str, int] = {}
        error_type_samples: Dict[str, Dict[str, Any]] = {}

        for r in results:
            for err in r["error_details"]:
                et = err["error_type"]
                error_type_counts[et] = error_type_counts.get(et, 0) + 1
                if et not in error_type_samples:
                    error_type_samples[et] = err

        for etype, count in sorted(error_type_counts.items(), key=lambda x: -x[1]):
            sample = error_type_samples[etype]
            R.warning(f"\n  📋 {etype}: {count} occurrence(s)")
            R.info(f"     sample sub_process:    {sample['sub_process']}")
            R.info(f"     sample business_value: {sample['business_value']}")
            reason_preview = str(sample["detailed_reason"])[:300]
            R.info(f"     sample reason:         {reason_preview}")

        # Report total stuck records
        total_stuck_records = sum(len(r["stuck_details"]) for r in results)
        if total_stuck_records:
            R.warning(f"\n  ⏳ STUCK sub-processes across all splits: {total_stuck_records}")

    return {
        "total_splits":        len(splits),
        "splits_passed":       splits_passed,
        "splits_failed":       splits_failed,
        "total_sub_processes": tot_sub,
        "total_completed":     tot_completed,
        "total_errored":       tot_errored,
        "total_stuck":         tot_stuck,
        "results":             results,
        "overall_status":      overall,
    }


# ══════════════════════════════════════════════════════════════════════
# FINAL AGGREGATION — RAISE IF FAILED
# ══════════════════════════════════════════════════════════════════════

@keyword("Raise If Scheduler Validation Failed")
def raise_if_scheduler_validation_failed(
    comparison_result: Optional[Dict[str, Any]] = None,
    split_validation_result: Optional[Dict[str, Any]] = None,
) -> None:
    """Aggregate all failure signals into ONE consolidated error."""
    problems: List[str] = []

    # Data integrity check
    if comparison_result and comparison_result.get("status") == "FAIL":
        problems.append(
            f"Symplr↔S3 count mismatch — "
            f"overlap {comparison_result.get('overlap_pct', 0):.1f}%, "
            f"diff {comparison_result.get('diff_pct', 0):.1f}%"
        )

    # Split sub-process validation
    if split_validation_result and split_validation_result.get("overall_status") == "FAIL":
        splits_failed = split_validation_result.get("splits_failed", 0)
        total_splits  = split_validation_result.get("total_splits", 0)
        tot_errored   = split_validation_result.get("total_errored", 0)
        tot_stuck     = split_validation_result.get("total_stuck", 0)

        details = []
        if tot_errored:
            details.append(f"{tot_errored} errored")
        if tot_stuck:
            details.append(f"{tot_stuck} stuck")

        problems.append(
            f"{splits_failed}/{total_splits} split(s) FAILED — "
            f"{', '.join(details)} sub-process(es). "
            f"See detailed reasons in log above."
        )

    if problems:
        raise IntegrationValidationError(
            "Scheduler remediation validation FAILED:\n  " + "\n  ".join(problems)
        )
