"""Smoke tests for cross-border net salary estimates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from salary_calculator import calculate_net_salary


def test_invalid_input_returns_empty_dict() -> None:
    assert calculate_net_salary(0) == {}
    assert calculate_net_salary(-100) == {}
    assert calculate_net_salary(None) == {}


def test_net_is_lower_than_gross() -> None:
    result = calculate_net_salary(4000)
    assert 0 < result["net_chf"] < 4000
    assert 0 < result["net_eur"] < result["net_chf"] / 0.9


def test_deductions_are_positive() -> None:
    result = calculate_net_salary(3500)
    assert result["social_chf"] > 0
    assert result["withholding_chf"] > 0
    assert result["extra_italian_tax_eur"] >= 0


def test_higher_gross_salary_has_higher_net_salary() -> None:
    assert calculate_net_salary(5000)["net_eur"] > calculate_net_salary(3000)["net_eur"]


def test_all_fields_are_present_and_integer() -> None:
    result = calculate_net_salary(4200)
    expected_fields = (
        "gross_chf",
        "social_chf",
        "withholding_chf",
        "extra_italian_tax_eur",
        "net_chf",
        "net_eur",
    )
    for field in expected_fields:
        assert field in result
        assert isinstance(result[field], int)
