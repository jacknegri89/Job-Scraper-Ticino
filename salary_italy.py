"""Indicative net pay for an employee working in Italy (Lombardy).

Starts from the annual gross salary (RAL) in EUR. The result is an estimate for a
permanent private-sector contract and is never a guaranteed take-home pay.
"""

from italian_tax import (
    INPS_EMPLOYEE_RATE,
    NOT_INCLUDED,
    TAX_YEAR,
    annual_irpef,
    employee_deduction,
)

DEFAULT_MONTHLY_PAYMENTS = 13
ALLOWED_MONTHLY_PAYMENTS = (12, 13, 14)


def calculate_italy_net(annual_gross_eur: float | int | None,
                        monthly_payments: int = DEFAULT_MONTHLY_PAYMENTS) -> dict:
    """Return annual and monthly net pay from an annual gross amount in EUR."""
    if annual_gross_eur is None or annual_gross_eur <= 0:
        return {}
    if monthly_payments not in ALLOWED_MONTHLY_PAYMENTS:
        monthly_payments = DEFAULT_MONTHLY_PAYMENTS
    gross_eur = float(annual_gross_eur)
    inps_eur = gross_eur * INPS_EMPLOYEE_RATE
    taxable_eur = gross_eur - inps_eur
    gross_tax_eur = annual_irpef(taxable_eur)
    deduction_eur = employee_deduction(taxable_eur)
    income_tax_eur = max(0.0, gross_tax_eur - deduction_eur)
    net_annual_eur = gross_eur - inps_eur - income_tax_eur
    return {
        "tax_year": TAX_YEAR,
        "gross_annual_eur": round(gross_eur),
        "inps_eur": round(inps_eur),
        "income_tax_eur": round(income_tax_eur),
        "net_annual_eur": round(net_annual_eur),
        "monthly_payments": monthly_payments,
        "net_monthly_eur": round(net_annual_eur / monthly_payments),
        "not_included": list(NOT_INCLUDED),
    }
