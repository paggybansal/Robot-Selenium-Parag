"""Suppression-rule business metadata.

This is the only place business-specific suppression metadata lives.

Adding a new Practitioner, Practice, or Facility rule should normally require:
    1. SQL files for candidate, count, and final state
    2. One DirectorySuppressionRule entry in this file
    3. A small pytest class setting RULE_KEY

Tests should not hardcode:
    - Rule IDs
    - Claim Hold Reason values
    - S3 output prefixes
    - CSV identity columns
    - StatusDB business values
    - Final expected database flags
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class DirectorySuppressionRule:
    # ── Rule identity ──────────────────────────────────────────────────
    key: str
    rule_id: int
    description: str

    # Used to dynamically create the Glue job name:
    #
    # usmg-{ENV}-provider-pdqa-automation-{flow_name}-dir-supp-glue-job
    #
    # Valid examples:
    # practitioner / practice / facility
    flow_name: str

    # Display/reporting entity name.
    entity_type: str

    # ── Candidate SQL resources ────────────────────────────────────────
    #
    # These paths are passed to load_sql(...).
    #
    # Example:
    # candidate_sql="symplr/practice_suppression_rule_candidates.sql"
    candidate_sql: str
    candidate_count_sql: str

    # ── Symplr candidate qualification ─────────────────────────────────
    trigger_field: str
    trigger_value: str
    udf_field_name: str
    qualifying_udf_values: Tuple[str, ...]

    # Required fields on the candidate returned by candidate SQL.
    #
    # Practitioner:
    #   ("PractitionerID", "NationalProviderID")
    #
    # Practice:
    #   ("PracticeID", "LocationID", "TaxIDNumber")
    candidate_identity_columns: Tuple[str, ...]

    # ── Outbound CSV validation ────────────────────────────────────────
    #
    # Candidate DB field -> outbound CSV header.
    #
    # Practitioner:
    #   ("NationalProviderID", "NationalProviderID")
    #
    # Practice:
    #   ("PracticeID", "PracticeID")
    #   ("LocationID", "BillingLocationID")
    outbound_identity_map: Tuple[Tuple[str, str], ...]

    # Used only for scheduled-flow / no-JobRunId S3 fallback lookup.
    #
    # Practitioner: NationalProviderID
    # Practice:     PracticeID
    outbound_search_field: str

    # Optional value assertion inside the outbound CSV.
    #
    # Practice:
    #   DataSource = pdqa-pdm-auto
    #
    # Practitioner:
    #   ActiveMilitaryOrReserve = Y or N based on actual file contract.
    outbound_column: Optional[str]
    outbound_expected_value: Optional[str]

    # Example:
    # home/generic/pdqa/practitioner_update/
    # home/generic/pdqa/practice_update/
    outbound_s3_prefix: str

    # ── StatusDB record filter ─────────────────────────────────────────
    #
    # StatusDB should use:
    #   process_id + status_business_value
    #
    # Practitioner: NationalProviderID
    # Practice:     TaxIDNumber
    # Facility:     future facility identifier
    status_business_value_field: str

    # ── Final database assertion ───────────────────────────────────────
    #
    # Practitioner:
    #   practitioner_by_id.sql, PractitionerID,
    #   ActiveMilitaryOrReserve = N
    #
    # Practice:
    #   practice_location_by_id.sql, LocationID,
    #   InDirectory = N
    final_state_sql: str
    final_key_columns: Tuple[str, ...]
    final_column: str
    final_expected_values: Tuple[str, ...]

    # Optional audit metadata for future use.
    expected_modified_by: str = "dataloader"
    enforce_modified_by: bool = False

    # Candidate SQL values for non-Rule-15/non-Claim-Hold-Reason rules.
    #
    # Rule 15 keeps this empty and uses the existing UDF binding logic.
    candidate_query_params: Tuple[str, ...] = ()

    # Additional candidate validations performed by test_01.
    #
    # Example:
    # (
    #     ("ServiceLocationTypeName", "Service"),
    #     ("BillingLocationTypeName", "Billing"),
    # )
    candidate_preconditions: Tuple[Tuple[str, str], ...] = ()

    # Rule 15 candidate SQL returns QualifyingValue.
    # Rule 9 does not use Claim Hold Reason and must set this to False.
    requires_qualifying_udf: bool = True

    # ── Legacy compatibility properties ────────────────────────────────
    #
    # These let existing code that still references rule.outbound_key_columns
    # continue to work while migration to outbound_identity_map is completed.

    @property
    def outbound_key_columns(self) -> Tuple[str, ...]:
        """Outbound CSV identity headers, retained for compatibility."""
        return tuple(
            outbound_column
            for _, outbound_column in self.outbound_identity_map
        )

    @property
    def rule_ids_accepted(self) -> set[str]:
        """Tolerant Glue-rule matching for common log representations."""
        value = str(self.rule_id)

        return {
            value,
            f"rule-{value}",
            f"rule_{value}",
            f"prac-{value}",
            f"practice-{value}",
            f"facility-{value}",
        }


# ── Practitioner Rule 15 ──────────────────────────────────────────────
#
# Pre-job:
#   dbo.Practitioners.ActiveMilitaryOrReserve = Y
#   Claim Hold Reason is one of qualifying_udf_values
#
# Post-Dataloader:
#   dbo.Practitioners.ActiveMilitaryOrReserve = N
#
RULE_15_ACTIVE_MILITARY = DirectorySuppressionRule(
    key="rule_15_active_military",
    rule_id=15,
    description=(
        "Practitioner with ActiveMilitaryOrReserve='Y' and a qualifying "
        "Claim Hold Reason must be processed by Practitioner directory "
        "suppression."
    ),

    flow_name="practitioner",
    entity_type="practitioner",

    candidate_sql="symplr/suppression_rule_candidates.sql",
    candidate_count_sql="symplr/suppression_rule_candidate_count.sql",

    trigger_field="ActiveMilitaryOrReserve",
    trigger_value="Y",
    udf_field_name="Claim Hold Reason",

    # Includes the intended 00009 value.
    qualifying_udf_values=(
        "00001",
        "00002",
        "00003",
        "00007",
        "00009",
    ),

    candidate_identity_columns=(
        "PractitionerID",
        "NationalProviderID",
    ),

    outbound_identity_map=(
        ("NationalProviderID", "NationalProviderID"),
    ),

    outbound_search_field="NationalProviderID",

    # IMPORTANT:
    # Set this to the actual value found in a real Practitioner outbound CSV.
    #
    # If Glue writes the original event state, use "Y".
    # If Glue writes the update instruction consumed by Dataloader, use "N".
    #
    # Your existing metadata used "N", so this preserves that setting.
    outbound_column="ActiveMilitaryOrReserve",
    outbound_expected_value="N",

    outbound_s3_prefix="home/generic/pdqa/practitioner_update/",

    # StatusDB lookup uses:
    # process_id + NationalProviderID
    status_business_value_field="NationalProviderID",

    final_state_sql="symplr/practitioner_by_id.sql",
    final_key_columns=("PractitionerID",),
    final_column="ActiveMilitaryOrReserve",
    final_expected_values=("N",),
)


# ── Practice Rule 15 ──────────────────────────────────────────────────
#
# Pre-job:
#   dbo.PracticeLocations.InDirectory = Y
#   Location Type = Service
#   Claim Hold Reason = 00001 or 00002
#
# Post-Dataloader:
#   dbo.PracticeLocations.InDirectory = N
#
RULE_15_PRACTICE_CLAIM_HOLD = DirectorySuppressionRule(
    key="practice_rule_15_claim_hold_reason",
    rule_id=15,
    description=(
        "Service PracticeLocation with InDirectory='Y' and Claim Hold Reason "
        "00001 or 00002 must be processed by Practice directory suppression."
    ),

    flow_name="practice",
    entity_type="practice",

    candidate_sql="symplr/practice_suppression_rule_candidates.sql",
    candidate_count_sql="symplr/practice_suppression_rule_candidate_count.sql",

    trigger_field="InDirectory",
    trigger_value="Y",
    udf_field_name="Claim Hold Reason",
    qualifying_udf_values=(
        "00001",
        "00002",
    ),

    # LocationID is the actual record whose InDirectory flag changes.
    candidate_identity_columns=(
        "PracticeID",
        "LocationID",
        "TaxIDNumber",
    ),

    # Practice output CSV:
    #
    # PracticeID
    # TaxIDNumber
    # BillingLocationServiceRecID
    # BillingLocationID
    # BillingServiceTypeName
    # BillingServiceCategoryTypeName
    # DataSource
    #
    # LocationID maps to BillingLocationID.
    outbound_identity_map=(
        ("PracticeID", "PracticeID"),
        ("LocationID", "BillingLocationID"),
    ),

    # Used only if test did not trigger Glue and must locate a new S3 object.
    outbound_search_field="PracticeID",

    outbound_column="DataSource",
    outbound_expected_value="pdqa-pdm-auto",

    outbound_s3_prefix="home/generic/pdqa/practice_update/",

    # StatusDB lookup uses:
    # process_id + TaxIDNumber
    #
    # Do not use TaxIDNumber as the CSV identity because it may appear in
    # scientific notation in CSV output, e.g. 8.41E+08.
    status_business_value_field="TaxIDNumber",

    final_state_sql="symplr/practice_location_by_id.sql",
    final_key_columns=("LocationID",),
    final_column="InDirectory",
    final_expected_values=("N",),
)


DIRECTORY_SUPPRESSION_RULES = {
    RULE_15_ACTIVE_MILITARY.key: RULE_15_ACTIVE_MILITARY,
    RULE_15_PRACTICE_CLAIM_HOLD.key: RULE_15_PRACTICE_CLAIM_HOLD,
}


def get_rule(key: str) -> DirectorySuppressionRule:
    """Return configured business metadata for one suppression rule."""
    try:
        return DIRECTORY_SUPPRESSION_RULES[key]
    except KeyError:
        raise KeyError(
            f"Unknown suppression rule '{key}'. "
            f"Known rules: {list(DIRECTORY_SUPPRESSION_RULES)}"
        ) from None
