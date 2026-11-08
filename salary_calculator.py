"""Estimate monthly net pay for a new Italian cross-border worker in Ticino.

The Swiss side (social contributions and withholding tax) uses simplified rates that
are assumptions, not official tables. The Italian side uses the shared rules in
italian_tax.py. The result is indicative and never a guaranteed net pay.
"""

from fx_rates import DEFAULT_MANUAL_EUR_PER_CHF
from italian_tax import annual_irpef, employee_deduction

ITALIAN_TAX_FREE_CHF = 10_000
SWISS_SOCIAL_RATE = 0.0955
MONTHS_PER_YEAR = 12

# Simplified Ticino withholding tax: (annual gross upper limit in CHF, rate).
WITHHOLDING_BRACKETS = (
    (18_000, 0.030), (21_000, 0.045), (24_000, 0.060),
    (27_000, 0.075), (30_000, 0.090), (35_000, 0.100),
    (40_000, 0.110), (45_000, 0.115), (50_000, 0.120),
    (60_000, 0.130), (80_000, 0.145), (100_000, 0.155),
)
WITHHOLDING_TOP_RATE = 0.170


def calculate_net_salary(gross_chf: float | int | None, eur_per_chf: float | None = None) -> dict[str, int]:
    """Return a rough monthly net salary estimate from a monthly gross CHF amount."""
    if gross_chf is None or gross_chf <= 0:
        return {}
    rate = eur_per_chf
    if rate is None or rate <= 0:
        rate = DEFAULT_MANUAL_EUR_PER_CHF
    return _calculate_valid_salary(float(gross_chf), rate)


def _calculate_valid_salary(gross_value: float, eur_per_chf: float) -> dict[str, int]:
    social_chf = gross_value * SWISS_SOCIAL_RATE
    withholding_chf = _monthly_withholding_tax(gross_value, social_chf)
    net_before_italy_chf = gross_value - social_chf - withholding_chf
    extra_italian_tax_eur = _monthly_italian_tax(gross_value, withholding_chf, eur_per_chf)
    final_net_chf = net_before_italy_chf - (extra_italian_tax_eur / eur_per_chf)
    return {
        "gross_chf": int(gross_value),
        "social_chf": int(round(social_chf)),
        "withholding_chf": int(round(withholding_chf)),
        "extra_italian_tax_eur": int(round(extra_italian_tax_eur)),
        "net_chf": int(round(final_net_chf)),
        "net_eur": int(round(final_net_chf * eur_per_chf)),
    }


def _monthly_withholding_tax(gross_chf: float, social_chf: float) -> float:
    taxable_chf = gross_chf - social_chf
    return taxable_chf * _withholding_tax_rate(gross_chf * MONTHS_PER_YEAR)


def _withholding_tax_rate(annual_gross_chf: float) -> float:
    for threshold, rate in WITHHOLDING_BRACKETS:
        if annual_gross_chf <= threshold:
            return rate
    return WITHHOLDING_TOP_RATE


def _monthly_italian_tax(gross_chf: float, withholding_chf: float, eur_per_chf: float) -> float:
    annual_gross_chf = gross_chf * MONTHS_PER_YEAR
    taxable_chf = max(0.0, annual_gross_chf - ITALIAN_TAX_FREE_CHF)
    taxable_eur = taxable_chf * eur_per_chf
    if taxable_eur <= 0:
        return 0.0
    gross_tax_eur = annual_irpef(taxable_eur)
    deduction_eur = employee_deduction(annual_gross_chf * eur_per_chf)
    net_tax_eur = max(0.0, gross_tax_eur - deduction_eur)
    tax_credit_eur = _withholding_tax_credit(withholding_chf, taxable_chf, annual_gross_chf, eur_per_chf)
    return max(0.0, net_tax_eur - tax_credit_eur) / MONTHS_PER_YEAR


def _withholding_tax_credit(
    withholding_chf: float,
    taxable_chf: float,
    annual_gross_chf: float,
    eur_per_chf: float,
) -> float:
    if annual_gross_chf <= 0:
        return 0.0
    taxable_share = taxable_chf / annual_gross_chf
    return (withholding_chf * MONTHS_PER_YEAR) * eur_per_chf * taxable_share
