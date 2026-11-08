"""Italian tax rules, Italian net pay, the cross-border estimate and the exchange rate."""

import pytest

import fx_rates
import italian_tax
from salary_calculator import calculate_net_salary
from salary_italy import calculate_italy_net

ECB_SAMPLE = (
    "<Cube time='2026-11-06'><Cube currency='USD' rate='1.1165'/>"
    "<Cube currency='CHF' rate='0.9143'/></Cube>"
)


def test_irpef_brackets_follow_the_2026_rates() -> None:
    assert italian_tax.annual_irpef(20_000) == pytest.approx(4_600)
    assert italian_tax.annual_irpef(28_000) == pytest.approx(6_440)
    assert italian_tax.annual_irpef(40_000) == pytest.approx(6_440 + 12_000 * 0.33)
    assert italian_tax.annual_irpef(60_000) == pytest.approx(6_440 + 22_000 * 0.33 + 10_000 * 0.43)
    assert italian_tax.annual_irpef(0) == 0


def test_employee_deduction_by_income_band() -> None:
    assert italian_tax.employee_deduction(12_000) == 1_955
    assert italian_tax.employee_deduction(15_000) == 1_955
    assert italian_tax.employee_deduction(28_000) == pytest.approx(1_910)
    assert italian_tax.employee_deduction(39_000) == pytest.approx(1_910 * 11_000 / 22_000)
    assert italian_tax.employee_deduction(50_000) == pytest.approx(0)
    assert italian_tax.employee_deduction(60_000) == 0


def test_italy_net_for_28000_matches_the_hand_calculation() -> None:
    # INPS 9.19% = 2573.2; taxable 25426.8; IRPEF 5848.16;
    # deduction 1910 + 1190 * (28000 - 25426.8) / 13000 = 2145.54; tax 3702.62.
    result = calculate_italy_net(28_000)
    assert result["inps_eur"] == 2573
    assert result["income_tax_eur"] == 3703
    assert result["net_annual_eur"] == 21_724
    assert result["net_monthly_eur"] == 1_671
    assert result["tax_year"] == italian_tax.TAX_YEAR
    assert result["not_included"]


def test_italy_net_with_other_payment_counts_and_invalid_input() -> None:
    assert calculate_italy_net(28_000, monthly_payments=12)["net_monthly_eur"] == 1_810
    assert calculate_italy_net(28_000, monthly_payments=99)["monthly_payments"] == 13
    assert calculate_italy_net(None) == {}
    assert calculate_italy_net(0) == {}


def test_higher_salary_never_gives_a_lower_net() -> None:
    nets = [calculate_italy_net(gross)["net_annual_eur"] for gross in range(12_000, 90_000, 2_000)]
    assert nets == sorted(nets)


def test_cross_border_estimate_uses_the_rate_it_is_given() -> None:
    low_rate = calculate_net_salary(4_500, eur_per_chf=1.0)
    high_rate = calculate_net_salary(4_500, eur_per_chf=1.1)
    assert high_rate["net_eur"] > low_rate["net_eur"]
    assert 0 < low_rate["net_chf"] < 4_500


def test_ecb_rate_is_inverted_to_eur_per_chf() -> None:
    rate = fx_rates.parse_ecb_xml(ECB_SAMPLE)
    assert rate.eur_per_chf == pytest.approx(1 / 0.9143, abs=0.0001)
    assert rate.date == "2026-11-06"
    assert rate.source == "ECB reference rate"


def test_malformed_ecb_data_is_rejected() -> None:
    assert fx_rates.parse_ecb_xml("<html>nope</html>") is None
    assert fx_rates.parse_ecb_xml("<Cube time='2026-11-06'><Cube currency='CHF' rate='0'/>") is None


def test_manual_mode_never_uses_the_network(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("network used in manual mode")

    monkeypatch.setattr(fx_rates.urllib.request, "urlopen", forbidden)
    rate = fx_rates.get_fx_rate("manual", 1.05, tmp_path / "fx.json")
    assert rate.eur_per_chf == 1.05
    assert rate.source == "manual rate"


def test_unreachable_ecb_falls_back_to_the_manual_rate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(fx_rates.urllib.request, "urlopen", offline)
    rate = fx_rates.get_fx_rate("ecb", 1.07, tmp_path / "fx.json")
    assert rate.eur_per_chf == 1.07
    assert rate.source == "manual rate"


def test_implausible_manual_rate_is_replaced_by_the_default() -> None:
    assert fx_rates.manual_rate(50).eur_per_chf == fx_rates.DEFAULT_MANUAL_EUR_PER_CHF
