"""House style: palette, fonts and number formatting shared by deck, charts, Excel and dashboard."""
from __future__ import annotations

import math

NAVY = "003255"
NAVY_TEXT = "003154"
LIGHT_BLUE = "81B0C0"
GREEN = "407061"
GREY = "8F9DA6"
LIGHT_GREY = "EDEDED"
MID_GREY = "BFC5CA"
DARK_GREY = "4A4A4A"
WHITE = "FFFFFF"
BLACK = "000000"
ACCENT_BLUE = "1F6FB2"
PALE_BLUE = "8FC3F0"
RED = "C0392B"
GOLD = "E3B341"
POSITIVE = GREEN
NEGATIVE = RED

CHART_COLORS = [NAVY, LIGHT_BLUE, GREEN, GREY, ACCENT_BLUE, MID_GREY]

FONT_TITLE = "Cambria"
FONT_BODY = "Arial"


def hx(color: str) -> str:
    """'003255' -> '#003255' (matplotlib / HTML)."""
    return color if color.startswith("#") else f"#{color}"


def rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


# ----------------------------------------------------------------------- numbers
def _isnum(v) -> bool:
    try:
        return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    except TypeError:
        return False


def fmt_num(v, decimals: int = 0, dash: str = "–") -> str:
    if not _isnum(v):
        return dash
    v = float(v)
    if decimals == 0:
        s = f"{abs(v):,.0f}"
    else:
        s = f"{abs(v):,.{decimals}f}"
    return f"({s})" if v < 0 else s


def fmt_pct(v, decimals: int = 1, dash: str = "–", sign: bool = False) -> str:
    if not _isnum(v):
        return dash
    v = float(v) * 100
    s = f"{v:+.{decimals}f}%" if sign else f"{v:.{decimals}f}%"
    return s


def fmt_mult(v, decimals: int = 1, dash: str = "–") -> str:
    if not _isnum(v) or float(v) <= 0:
        return dash if not _isnum(v) else "n.m."
    return f"{float(v):.{decimals}f}x"


def fmt_leverage(v, decimals: int = 1, dash: str = "–") -> str:
    """Net debt / EBITDA: a negative ratio means net cash, not 'not meaningful'."""
    if not _isnum(v):
        return dash
    return "net cash" if float(v) < 0 else f"{float(v):.{decimals}f}x"


def fmt_price(v, currency: str = "", decimals: int = 2, dash: str = "–") -> str:
    if not _isnum(v):
        return dash
    s = f"{float(v):,.{decimals}f}"
    return f"{currency} {s}".strip()


def fmt_value(v, value_format: str = "", decimals: int | None = None) -> str:
    """Format according to a config ``value_format`` ('%', 'x' or '')."""
    if not _isnum(v):
        return "–"
    v = float(v)
    if value_format == "%":
        d = decimals if decimals is not None else (0 if abs(v) >= 10 else 1)
        return f"{v:.{d}f}%"
    if value_format == "x":
        return f"{v:.{decimals if decimals is not None else 1}f}x"
    d = decimals if decimals is not None else (0 if abs(v) >= 100 else 1)
    return f"{v:,.{d}f}"
