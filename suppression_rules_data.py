"""Suppression-rule business metadata.

Business values belong here only. Tests must not hardcode:
- rule identifiers
- qualifying Claim Hold Reason values
- S3 prefixes
- CSV identity columns
- final database flags
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class DirectorySuppressionRule:
    key: str
    entity_type: str                 # practitioner / practice / facility
    flow_name: str                   # used to select Glue job configuration
    rule_id: int
    description: str

    # Candidate SQL resources.
    candidate_sql: str
    candidate_count_sql: str

    # Candidate qualification.
    trigger_field: str
    trigger_value: str
    udf_field_name: str
    qualifying_udf_values: Tuple[str, ...]

    # Candidate identity in the source database.
    candidate_identity_columns: Tuple[str, ...]

    # Outbound file matching:
    # (candidate-column-name, outbound-CSV-column-name)
    outbound_identity_map: Tuple[Tuple[str, str], ...]

    # Optional expected outbound CSV value.
    outbound_column: Optional[str]
    outbound_expected_value: Optional[str]

    # Used only when Glue was not triggered and S3 fallback search is required.
    outbound_search_field: str

    # Exact S3 object prefix for this entity flow.
    outbound_s3_prefix: str

    # Final-state SQL and assertion.
    final_state_sql: str
    final_key_columns: Tuple[str, ...]
    final_column: str
    final_expected_values: Tuple[str, ...]

    expected_modified_by: str = "dataloader"
    enforce_modified_by: bool = False

    @property
    def rule_ids_accepted(self) -> set[str]:
        """Accept common formats emitted by Glue logs."""
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
RULE_15_ACTIVE_MILITARY = DirectorySuppressionRule(
    key="rule_15_active_military",
    entity_type="practitioner",
    flow_name="practitioner",
    rule_id=15,
    description=(
        "Practitioner with ActiveMilitaryOrReserve='Y' and a qualifying "
        "Claim Hold Reason is processed by the Practitioner suppression flow."
    ),

    candidate_sql="symplr/suppression_rule_candidates.sql",
    candidate_count_sql="symplr/suppression_rule_candidate_count.sql",

    trigger_field="ActiveMilitaryOrReserve",
    trigger_value="Y",
    udf_field_name="Claim Hold Reason",
    qualifying_udf_values=("00001", "00002", "00003", "00007", "00009"),

    candidate_identity_columns=("PractitionerID", "NationalProviderID"),

    outbound_identity_map=(
        ("NationalProviderID", "NationalProviderID"),
    ),

    # Practitioner CSV contains ActiveMilitaryOrReserve=Y.
    # The final DB value becomes N after Dataloader.
    outbound_column="ActiveMilitaryOrReserve",
    outbound_expected_value="Y",

    outbound_search_field="NationalProviderID",
    outbound_s3_prefix="home/generic/pdqa/practitioner_update/",

    final_state_sql="symplr/practitioner_by_id.sql",
    final_key_columns=("PractitionerID",),
    final_column="ActiveMilitaryOrReserve",
    final_expected_values=("N",),
)


# ── Practice Rule 15 ──────────────────────────────────────────────────
RULE_15_PRACTICE_CLAIM_HOLD = DirectorySuppressionRule(
    key="practice_rule_15_claim_hold_reason",
    entity_type="practice",
    flow_name="practice",
    rule_id=15,
    description=(
        "Service PracticeLocation with InDirectory='Y' and Claim Hold Reason "
        "00001 or 00002 must be suppressed from the provider directory."
    ),

    candidate_sql="symplr/practice_suppression_rule_candidates.sql",
    candidate_count_sql="symplr/practice_suppression_rule_candidate_count.sql",

    trigger_field="InDirectory",
    trigger_value="Y",
    udf_field_name="Claim Hold Reason",
    qualifying_udf_values=("00001", "00002"),

    # LocationID is the actual record that is suppressed.
    candidate_identity_columns=("PracticeID", "LocationID"),

    # Practice output file uses BillingLocationID, which must map to LocationID.
    outbound_identity_map=(
        ("PracticeID", "PracticeID"),
        ("LocationID", "BillingLocationID"),
    ),

    # Actual Practice outbound CSV contains DataSource.
    outbound_column="DataSource",
    outbound_expected_value="pdqa-pdm-auto",

    outbound_search_field="PracticeID",
    outbound_s3_prefix="home/generic/pdqa/practice_update/",

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
    try:
        return DIRECTORY_SUPPRESSION_RULES[key]
    except KeyError:
        raise KeyError(
            f"Unknown suppression rule '{key}'. "
            f"Known: {list(DIRECTORY_SUPPRESSION_RULES)}"
        ) from None
