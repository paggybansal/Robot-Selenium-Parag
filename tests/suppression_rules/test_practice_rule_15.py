import pytest

from action_api_framework.tests.suppression_rules.base_directory_suppression import (
    BaseDirectorySuppression,
)


@pytest.mark.suppression_rules
class TestPracticeRule15Suppression(BaseDirectorySuppression):
    RULE_KEY = "practice_rule_15_claim_hold_reason"
