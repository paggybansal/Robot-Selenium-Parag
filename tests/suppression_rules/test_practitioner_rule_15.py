import pytest

from action_api_framework.tests.suppression_rules.base_directory_suppression import (
    BaseDirectorySuppression,
)


@pytest.mark.suppression_rules
class TestPractitionerRule15Suppression(BaseDirectorySuppression):
    RULE_KEY = "rule_15_active_military"
