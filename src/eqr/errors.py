"""Exceptions with messages meant for the analyst, not a stack trace."""
from __future__ import annotations

UNSUPPORTED_SECTORS = {
    "Financial Services": "banks, insurers and asset managers are valued on equity (dividends, excess returns, P/B vs ROE), "
                          "not on enterprise free cash flow: interest is their raw material, not a financing cost",
    "Real Estate": "property companies are valued on net asset value and yields; capex is the business, so FCFF is structurally negative",
}


# Industries the model will run, but where a generic FCFF DCF is known to mislead. Matched as substrings of Yahoo's industry.
CAUTION_INDUSTRIES = {
    "Oil & Gas E&P": "petroleum tax (78% on the Norwegian shelf, with immediate expensing of capex) and reserve depletion are not "
                     "captured by a constant tax rate and a perpetuity; E&P companies are normally valued on a field-by-field NAV",
    "Oil & Gas Integrated": "upstream earnings carry petroleum tax and depletion that a constant tax rate and a perpetuity do not capture",
    "Marine Shipping": "earnings follow freight-rate cycles; extrapolating recent margins capitalises the cycle, so NAV and mid-cycle "
                       "earnings are the usual anchors",
    "Airlines": "aircraft leases and cyclical margins make the lease adjustment and the margin path unusually uncertain",
    "Conglomerates": "holding companies consolidate subsidiaries' debt and minorities; they are valued on a sum-of-the-parts NAV",
    "Asset Management": "holding and investment companies are valued on NAV, not on consolidated free cash flow",
    "Farm Products": "biological assets make working capital and margins swing with spot prices; mid-cycle margins matter more than the last three years",
}


def industry_caution(industry: str | None) -> str | None:
    if not industry:
        return None
    for key, reason in CAUTION_INDUSTRIES.items():
        if key.lower() in industry.lower():
            return f"Industry '{industry}': {reason}."
    return None


class UnsupportedCompanyError(ValueError):
    """The engine's FCFF framework does not apply to this company."""


def check_supported(name: str, sector: str | None, allow: bool = False) -> None:
    if allow or not sector:
        return
    reason = UNSUPPORTED_SECTORS.get(sector)
    if reason:
        raise UnsupportedCompanyError(f"{name} is in '{sector}': {reason}. Set allow_unsupported_sector: true in the config to run it anyway.")
