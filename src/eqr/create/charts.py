"""Matplotlib charts in the house style (rendered to PNG for the deck).

Design rules: one axis per chart (a margin line is drawn as labels, never as a
second y-axis), fixed categorical colour order, thin marks, direct data labels
instead of gridlines, recessive axes.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .style import (  # noqa: E402
    ACCENT_BLUE,
    CHART_COLORS,
    DARK_GREY,
    GOLD,
    GREEN,
    GREY,
    LIGHT_BLUE,
    LIGHT_GREY,
    MID_GREY,
    NAVY,
    RED,
    fmt_value,
    hx,
)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans"],
    "font.size": 7.5,
    "axes.edgecolor": hx(MID_GREY),
    "axes.linewidth": 0.6,
    "axes.titlesize": 8,
    "axes.titleweight": "bold",
    "axes.titlecolor": hx(NAVY),
    "xtick.color": hx(DARK_GREY),
    "ytick.color": hx(DARK_GREY),
    "legend.frameon": False,
    "legend.fontsize": 7,
})

DEFAULT_SIZE = (4.0, 2.25)


def _fig(size: tuple[float, float] = DEFAULT_SIZE):
    fig, ax = plt.subplots(figsize=size)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0, labelleft=False)
    ax.tick_params(axis="x", length=0)
    return fig, ax


def _save(fig, path: str | Path, dpi: int = 220) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.04, facecolor="white")
    plt.close(fig)
    return path


def _label(ax, x, y, text, above: bool = True, color: str = DARK_GREY, size: float = 6.5, weight: str = "normal"):
    ax.annotate(text, (x, y), xytext=(0, 3 if above else -3), textcoords="offset points", ha="center",
                va="bottom" if above else "top", fontsize=size, color=hx(color), fontweight=weight)


def _headroom(ax, values: Sequence[float], top: float = 1.28, bottom_pad: float = 0.12):
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if not vals:
        return
    hi, lo = max(vals + [0]), min(vals + [0])
    span = hi - lo if hi != lo else abs(hi) or 1.0
    ax.set_ylim(lo - span * bottom_pad if lo < 0 else 0, hi + span * (top - 1))


# ------------------------------------------------------------------- charts
def grouped_bars(categories: Sequence, series: Sequence[tuple[str, Sequence[float]]], path: str | Path, *,
                 value_format: str = "", title: str | None = None, size=DEFAULT_SIZE, colors=None, labels: bool = True,
                 legend: bool = True, decimals: int | None = None, highlight: dict[str, str] | None = None) -> Path:
    """Vertical grouped bar chart with direct labels."""
    fig, ax = _fig(size)
    n = len(series)
    x = np.arange(len(categories))
    width = min(0.8 / max(n, 1), 0.38)
    colors = colors or CHART_COLORS
    allvals: list[float] = []
    for i, (name, values) in enumerate(series):
        vals = [np.nan if v is None else float(v) for v in values]
        offs = (i - (n - 1) / 2) * width
        cols = [hx(highlight.get(str(c), colors[i % len(colors)])) if highlight else hx(colors[i % len(colors)]) for c in categories]
        bars = ax.bar(x + offs, np.nan_to_num(vals), width * 0.92, color=cols, label=name, zorder=3)
        allvals += [v for v in vals if np.isfinite(v)]
        if labels:
            for b, v in zip(bars, vals):
                if np.isfinite(v):
                    _label(ax, b.get_x() + b.get_width() / 2, v if v >= 0 else 0, fmt_value(v, value_format, decimals), above=True)
    ax.set_xticks(x)
    ax.set_xticklabels([str(c) for c in categories], fontsize=7)
    ax.axhline(0, color=hx(MID_GREY), linewidth=0.6, zorder=2)
    _headroom(ax, allvals)
    if title:
        ax.set_title(title, loc="left", pad=6)
    if legend and n > 1:
        ax.legend(loc="upper left", ncol=min(n, 3), bbox_to_anchor=(0, 1.02), handlelength=0.8, columnspacing=0.8)
    return _save(fig, path)


def horizontal_bars(names: Sequence[str], values: Sequence[float], path: str | Path, *, value_format: str = "",
                    title: str | None = None, highlight_name: str | None = None, size=DEFAULT_SIZE,
                    reference: float | None = None, reference_label: str = "") -> Path:
    fig, ax = _fig(size)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(hx(MID_GREY))
    ax.tick_params(axis="x", labelbottom=False)
    ax.tick_params(axis="y", labelleft=True, length=0)
    vals = [np.nan if v is None else float(v) for v in values]
    order = np.argsort([-v if np.isfinite(v) else np.inf for v in vals])
    names_o = [names[i] for i in order][::-1]
    vals_o = [vals[i] for i in order][::-1]
    cols = [hx(GREEN if n == highlight_name else NAVY) for n in names_o]
    y = np.arange(len(names_o))
    ax.barh(y, np.nan_to_num(vals_o), color=cols, height=0.62, zorder=3)
    for yi, v in zip(y, vals_o):
        if np.isfinite(v):
            ax.annotate(fmt_value(v, value_format), (max(v, 0), yi), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.5,
                        color=hx(DARK_GREY))
    ax.set_yticks(y)
    ax.set_yticklabels(names_o, fontsize=6.5)
    if reference is not None and np.isfinite(reference):
        ax.axvline(reference, color=hx(GOLD), linestyle="--", linewidth=1, zorder=4)
        ax.annotate(reference_label or fmt_value(reference, value_format), (reference, len(names_o) - 0.4), xytext=(2, 0),
                    textcoords="offset points", fontsize=6.5, color=hx(GOLD), va="bottom")
    finite = [v for v in vals_o if np.isfinite(v)]
    if finite:
        ax.set_xlim(min(0, min(finite)), max(finite) * 1.22)
    if title:
        ax.set_title(title, loc="left", pad=6)
    return _save(fig, path)


def revenue_margin_chart(labels: Sequence[str], revenue: Sequence[float], profit: Sequence[float], margin: Sequence[float],
                         path: str | Path, *, profit_label: str = "EBIT", margin_label: str = "EBIT margin",
                         size=(4.0, 2.3), actual_count: int | None = None, bar_label: str = "Revenue") -> Path:
    """Revenue + profit bars with the margin written above each pair (no second axis)."""
    from matplotlib.lines import Line2D

    fig, ax = _fig(size)
    x = np.arange(len(labels))
    w = 0.36
    rev = np.array([float(v) for v in revenue])
    prof = np.array([float(v) for v in profit])
    rev_cols = [hx(NAVY) if (actual_count is None or i < actual_count) else hx(LIGHT_BLUE) for i in range(len(labels))]
    ax.bar(x - w / 2, rev, w, color=rev_cols, label="Revenue", zorder=3)
    ax.bar(x + w / 2, prof, w, color=hx(MID_GREY), label=profit_label, zorder=3)
    for i in range(len(labels)):
        _label(ax, x[i] - w / 2, rev[i], fmt_value(rev[i], "", 0), size=5.8)
        _label(ax, x[i] + w / 2, max(prof[i], 0), fmt_value(prof[i], "", 0), size=5.8)
    peak = max(np.nanmax(rev), np.nanmax(prof), 1e-9)
    top = peak * 1.42
    ax.set_ylim(min(0, np.nanmin(prof) * 1.2, np.nanmin(rev) * 1.2), top)
    for i, m in enumerate(margin):
        if m is not None and np.isfinite(m):
            ax.text(x[i], peak * 1.27, fmt_value(m * 100, "%", 0), ha="center", fontsize=6.5, color=hx(GREEN), fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6)
    handles = [plt.Rectangle((0, 0), 1, 1, color=hx(NAVY)), plt.Rectangle((0, 0), 1, 1, color=hx(LIGHT_BLUE)),
               plt.Rectangle((0, 0), 1, 1, color=hx(MID_GREY)), Line2D([0], [0], marker="s", color="none", markerfacecolor=hx(GREEN), markersize=5)]
    names = [f"{bar_label} (actual)", f"{bar_label} (estimate)", profit_label, margin_label]
    if actual_count is None or actual_count >= len(labels):
        handles, names = [handles[0], handles[2], handles[3]], [bar_label, profit_label, margin_label]
    ax.legend(handles, names, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, handlelength=0.8, columnspacing=0.7, fontsize=6)
    return _save(fig, path)


def line_chart(x: Sequence, series: Sequence[tuple[str, Sequence[float]]], path: str | Path, *, value_format: str = "",
               title: str | None = None, size=DEFAULT_SIZE, end_labels: bool = True, colors=None, ylabel: str | None = None,
               show_y: bool = False) -> Path:
    fig, ax = _fig(size)
    colors = colors or CHART_COLORS
    if show_y:
        ax.tick_params(axis="y", labelleft=True)
        ax.yaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
        ax.set_axisbelow(True)
    for i, (name, values) in enumerate(series):
        vals = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
        ax.plot(list(x), vals, color=hx(colors[i % len(colors)]), linewidth=1.6, label=name, zorder=3)
        if end_labels and np.isfinite(vals[-1]):
            ax.annotate(fmt_value(vals[-1], value_format), (list(x)[-1], vals[-1]), xytext=(3, 0), textcoords="offset points",
                        fontsize=6.5, color=hx(colors[i % len(colors)]), va="center")
    if len(series) > 1:
        ax.legend(loc="upper left", ncol=min(len(series), 2), handlelength=1.2)
    ax.tick_params(axis="x", labelsize=6.5)
    if isinstance(list(x)[0], (pd.Timestamp, np.datetime64)):
        fig.autofmt_xdate(rotation=0, ha="center")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=6.5, color=hx(DARK_GREY))
    if title:
        ax.set_title(title, loc="left", pad=6)
    ax.margins(x=0.02)
    return _save(fig, path)


def donut_chart(labels: Sequence[str], values: Sequence[float], path: str | Path, *, center_text: str = "",
                size=(2.2, 2.0), colors=None, value_format: str = "%") -> Path:
    fig, ax = plt.subplots(figsize=size)
    fig.patch.set_facecolor("white")
    colors = colors or [NAVY, LIGHT_BLUE, GREY, GREEN, MID_GREY, ACCENT_BLUE]
    vals = [max(float(v), 0) for v in values]
    total = sum(vals) or 1.0
    wedges, _ = ax.pie(vals, colors=[hx(c) for c in colors[: len(vals)]], startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.38, edgecolor="white", linewidth=1.5))
    for w, v in zip(wedges, vals):
        ang = np.deg2rad((w.theta2 + w.theta1) / 2)
        r = 0.81
        share = v / total * 100
        if share >= 6:
            ax.text(r * np.cos(ang), r * np.sin(ang), f"{share:.0f}%", ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
    if center_text and len(center_text) <= 10:
        ax.text(0, 0, center_text, ha="center", va="center", fontsize=7.5, fontweight="bold", color=hx(NAVY))
    elif center_text:
        ax.set_title(center_text, fontsize=7.5, color=hx(NAVY), fontweight="bold", pad=4)
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(0.98, 0.5), fontsize=6.5, handlelength=0.8)
    ax.set_aspect("equal")
    return _save(fig, path)


def relative_performance_chart(rel: pd.DataFrame, path: str | Path, *, stock_name: str, index_name: str, size=DEFAULT_SIZE) -> Path:
    fig, ax = _fig(size)
    ax.tick_params(axis="y", labelleft=True)
    ax.yaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
    ax.set_axisbelow(True)
    ax.plot(rel.index, rel["stock"], color=hx(NAVY), linewidth=1.6, label=stock_name, zorder=3)
    ax.plot(rel.index, rel["index"], color=hx(GREY), linewidth=1.3, label=index_name, zorder=3)
    for col, color in (("stock", NAVY), ("index", GREY)):
        ax.annotate(f"{rel[col].iloc[-1]:.0f}", (rel.index[-1], rel[col].iloc[-1]), xytext=(3, 0), textcoords="offset points",
                    fontsize=6.5, color=hx(color), va="center")
    ax.legend(loc="upper left", ncol=2, handlelength=1.2)
    ax.tick_params(axis="x", labelsize=6.5)
    ax.text(0.0, 1.02, "Rebased to 100", transform=ax.transAxes, fontsize=6, color=hx(DARK_GREY))
    ax.margins(x=0.02)
    return _save(fig, path)


def multiples_panel(label: str, values: dict[str, float | None], path: str | Path, *, size=(2.6, 1.9), highlight: str | None = None) -> Path:
    """Small bar chart: peer average / peer median / company for one multiple."""
    fig, ax = _fig(size)
    names = list(values.keys())
    vals = [np.nan if v is None else float(v) for v in values.values()]
    cols = [hx(GREEN if n == highlight else (NAVY if i == 0 else LIGHT_BLUE)) for i, n in enumerate(names)]
    bars = ax.bar(np.arange(len(names)), np.nan_to_num(vals), 0.62, color=cols, zorder=3)
    for b, v in zip(bars, vals):
        if np.isfinite(v):
            _label(ax, b.get_x() + b.get_width() / 2, v, fmt_value(v, "x"), size=7, weight="bold")
    ax.set_xticks(np.arange(len(names)))
    ax.set_xticklabels(names, fontsize=6.5)
    _headroom(ax, vals, top=1.3)
    ax.set_title(label, loc="center", pad=4, fontsize=9)
    return _save(fig, path)


def football_field_chart(bars: Sequence, price: float | None, target: float | None, path: str | Path, *,
                         currency: str = "", size=(4.3, 2.4)) -> Path:
    """Horizontal floating bars (valuation ranges) with current price and target price lines."""
    fig, ax = _fig(size)
    ax.spines["bottom"].set_visible(True)
    ax.tick_params(axis="y", labelleft=True, length=0)
    ax.tick_params(axis="x", labelsize=6.5, length=2)
    ax.xaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
    ax.set_axisbelow(True)
    labels = [b.label for b in bars][::-1]
    lows = [float(b.low) for b in bars][::-1]
    highs = [float(b.high) for b in bars][::-1]
    y = np.arange(len(labels))
    ax.barh(y, [hi - lo for lo, hi in zip(lows, highs)], left=lows, height=0.5, color=hx(NAVY), zorder=3)
    # white pads and a high zorder keep the range labels readable where they cross the price lines
    pad = {"boxstyle": "square,pad=0.12", "facecolor": "white", "edgecolor": "none"}
    for yi, l_, h in zip(y, lows, highs):
        ax.annotate(f"{l_:,.0f}", (l_, yi), xytext=(-3, 0), textcoords="offset points", ha="right", va="center", fontsize=6.5,
                    color=hx(DARK_GREY), bbox=pad, zorder=6)
        ax.annotate(f"{h:,.0f}", (h, yi), xytext=(3, 0), textcoords="offset points", ha="left", va="center", fontsize=6.5,
                    color=hx(DARK_GREY), bbox=pad, zorder=6)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=6.5)
    handles = []
    if price is not None:
        h1 = ax.axvline(price, color=hx(RED), linestyle="--", linewidth=1.2, zorder=4, label=f"Current price {price:,.2f}")
        handles.append(h1)
    if target is not None:
        h2 = ax.axvline(target, color=hx(GOLD), linestyle="-", linewidth=1.4, zorder=4, label=f"Target price {target:,.2f}")
        handles.append(h2)
    if handles:
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, fontsize=6.5, handlelength=1.2, columnspacing=1.0)
    lo = min(lows + ([price] if price else []) + ([target] if target else []))
    hi = max(highs + ([price] if price else []) + ([target] if target else []))
    span = hi - lo or 1.0
    ax.set_xlim(max(0, lo - span * 0.18), hi + span * 0.18)
    if currency:
        ax.set_xlabel(f"{currency} per share", fontsize=6.5, color=hx(DARK_GREY))
    return _save(fig, path)


def scatter_regression_chart(points: Sequence[dict], target: dict, path: str | Path, *, line: tuple[float, float] | None = None,
                             fitted_target: float | None = None, x_label: str = "Expected revenue growth", y_label: str = "EV/EBITDA (x)",
                             line_label: str = "Regression", size=(4.6, 2.9)) -> Path:
    """Peers as points (``name``, ``x`` in %, ``y``), the target highlighted, an optional fitted line (intercept, slope per %)."""
    fig, ax = _fig(size)
    ax.spines["bottom"].set_visible(True)
    ax.spines["left"].set_visible(True)
    ax.tick_params(axis="y", labelleft=True, length=2, labelsize=6.5)
    ax.tick_params(axis="x", labelsize=6.5, length=2)
    ax.yaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
    ax.set_axisbelow(True)
    xs = [float(p["x"]) for p in points]
    ys = [float(p["y"]) for p in points]
    ax.scatter(xs, ys, s=22, color=hx(LIGHT_BLUE), zorder=3, label="Peers")
    for p in points:
        ax.annotate(str(p["name"]), (float(p["x"]), float(p["y"])), xytext=(4, 3), textcoords="offset points", fontsize=5.8, color=hx(DARK_GREY))
    tx, ty = float(target["x"]), float(target["y"])
    ax.scatter([tx], [ty], s=48, color=hx(GREEN), zorder=5, label=str(target.get("name", "Target")))
    ax.annotate(str(target.get("name", "")), (tx, ty), xytext=(6, -11), textcoords="offset points", fontsize=6.5, color=hx(GREEN), fontweight="bold",
                bbox={"boxstyle": "square,pad=0.1", "facecolor": "white", "edgecolor": "none"}, zorder=7)
    all_x = xs + [tx]
    lo, hi = min(all_x), max(all_x)
    pad = (hi - lo) * 0.12 or 1.0
    if line is not None:
        a, b = line
        gx = np.array([lo - pad, hi + pad])
        ax.plot(gx, a + b * gx, color=hx(GREY), linestyle="--", linewidth=1.1, zorder=2, label=line_label)
    if fitted_target is not None:
        ax.scatter([tx], [fitted_target], s=60, facecolors="white", edgecolors=hx(GREEN), linewidths=1.4, zorder=6, label="Fitted for target")
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_xlabel(f"{x_label} (%)", fontsize=6.5, color=hx(DARK_GREY))
    ax.set_ylabel(y_label, fontsize=6.5, color=hx(DARK_GREY))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=4, fontsize=6.3, handlelength=1.4, columnspacing=1.0, markerscale=0.8)
    return _save(fig, path)


def tornado_chart(items: Sequence, base: float, price: float | None, path: str | Path, *, currency: str = "",
                  size=(4.6, 3.0)) -> Path:
    """One-at-a-time value sensitivities: bars from the base value to the value with each driver lowered / raised.

    ``items`` need ``driver``, ``shock``, ``value_down`` and ``value_up`` (largest swing first).
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig, ax = _fig(size)
    ax.spines["bottom"].set_visible(True)
    ax.tick_params(axis="y", labelleft=True, length=0)
    ax.tick_params(axis="x", labelsize=6.5, length=2)
    ax.xaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
    ax.set_axisbelow(True)
    rows = [it for it in items if np.isfinite(it.value_down) and np.isfinite(it.value_up)][::-1]
    y = np.arange(len(rows))
    pad = {"boxstyle": "square,pad=0.12", "facecolor": "white", "edgecolor": "none"}
    vals = [base] + ([price] if price else [])
    for yi, it in zip(y, rows):
        for val, colour in ((it.value_down, LIGHT_BLUE), (it.value_up, NAVY)):
            ax.barh(yi, val - base, left=base, height=0.55, color=hx(colour), zorder=3)
            right = val >= base
            ax.annotate(f"{val:,.1f}", (val, yi), xytext=(3 if right else -3, 0), textcoords="offset points", ha="left" if right else "right",
                        va="center", fontsize=6.5, color=hx(DARK_GREY), bbox=pad, zorder=6)
            vals.append(val)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{it.driver} {it.shock}" for it in rows], fontsize=6.5)
    ax.axvline(base, color=hx(NAVY), linewidth=1.0, zorder=4)
    handles = [Patch(color=hx(LIGHT_BLUE), label="Driver lowered"), Patch(color=hx(NAVY), label="Driver raised"),
               Line2D([0], [0], color=hx(NAVY), lw=1.0, label=f"Base {base:,.2f}")]
    if price:
        ax.axvline(price, color=hx(RED), linestyle="--", linewidth=1.1, zorder=4)
        handles.append(Line2D([0], [0], color=hx(RED), ls="--", lw=1.1, label=f"Current price {price:,.2f}"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=4, fontsize=6.5, handlelength=1.2, columnspacing=1.0)
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1.0
    ax.set_xlim(lo - span * 0.14, hi + span * 0.14)
    if currency:
        ax.set_xlabel(f"{currency} per share (fair value today)", fontsize=6.5, color=hx(DARK_GREY))
    return _save(fig, path)


def value_bars_chart(items: Sequence[tuple[str, float | None]], path: str | Path, *, size=(2.2, 2.2), base_index: int = 0,
                     colors: Sequence[str] | None = None, decimals: int = 2, title: str | None = None) -> Path:
    """Small bars (e.g. current price vs DCF value) annotated with % difference vs the base bar."""
    fig, ax = _fig(size)
    names = [i[0] for i in items]
    vals = [np.nan if i[1] is None else float(i[1]) for i in items]
    colors = list(colors or [DARK_GREY, NAVY, LIGHT_BLUE, GREEN, GREY])
    while len(colors) < len(names):
        colors.append(GREY)
    bars = ax.bar(np.arange(len(names)), np.nan_to_num(vals), 0.6, color=[hx(c) for c in colors[: len(names)]], zorder=3)
    base = vals[base_index]
    if title:
        ax.set_title(title, loc="center", pad=4, fontsize=7.5)
    lab_size = 7 if len(names) <= 3 else 6.2
    for i, (b, v) in enumerate(zip(bars, vals)):
        if not np.isfinite(v):
            continue
        _label(ax, b.get_x() + b.get_width() / 2, v, f"{v:,.{decimals}f}", size=lab_size, weight="bold")
        if i != base_index and np.isfinite(base) and base:
            pct = v / base - 1
            pct = 0.0 if abs(pct) < 0.005 else pct  # avoid "-0%"
            ax.annotate(f"{pct:+.0%}" if pct else "0%", (b.get_x() + b.get_width() / 2, v), xytext=(0, 13), textcoords="offset points",
                        ha="center", fontsize=lab_size, color=hx(GREEN if pct >= 0 else RED), fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=hx(GREEN if pct >= 0 else RED), lw=0.6))
    ax.set_xticks(np.arange(len(names)))
    ax.set_xticklabels(names, fontsize=6.5 if len(names) <= 3 else 6)
    _headroom(ax, vals, top=1.5)
    return _save(fig, path)


def stacked_bars(categories: Sequence, series: Sequence[tuple[str, Sequence[float]]], path: str | Path, *, value_format: str = "",
                 title: str | None = None, size=DEFAULT_SIZE, colors=None, total_labels: bool = True) -> Path:
    fig, ax = _fig(size)
    colors = colors or CHART_COLORS
    x = np.arange(len(categories))
    bottom = np.zeros(len(categories))
    for i, (name, values) in enumerate(series):
        vals = np.array([0.0 if v is None else float(v) for v in values])
        ax.bar(x, vals, 0.6, bottom=bottom, color=hx(colors[i % len(colors)]), label=name, zorder=3, edgecolor="white", linewidth=0.8)
        bottom += vals
    if total_labels:
        for xi, t in zip(x, bottom):
            _label(ax, xi, t, fmt_value(t, value_format), size=6.5)
    ax.set_xticks(x)
    ax.set_xticklabels([str(c) for c in categories], fontsize=7)
    _headroom(ax, list(bottom))
    ax.legend(loc="upper left", ncol=min(len(series), 3), bbox_to_anchor=(0, 1.02), handlelength=0.8, columnspacing=0.8)
    if title:
        ax.set_title(title, loc="left", pad=6)
    return _save(fig, path)


def band_chart(series: pd.Series, stats: dict, path: str | Path, *, label: str, size=(5.6, 2.9)) -> Path:
    """A multiple through time with its median and interquartile band (one axis, direct labels)."""
    fig, ax = _fig(size)
    ax.tick_params(axis="y", labelleft=True)
    ax.yaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.5)
    ax.set_axisbelow(True)
    s = series.dropna()
    ax.axhspan(stats["p25"], stats["p75"], color=hx(LIGHT_BLUE), alpha=0.28, zorder=1, label="25th–75th percentile")
    ax.axhline(stats["median"], color=hx(GREY), linestyle="--", linewidth=1.1, zorder=2, label=f"Median {stats['median']:.1f}x")
    ax.plot(s.index, s.values, color=hx(NAVY), linewidth=1.6, zorder=3, label=label)
    ax.scatter([s.index[-1]], [s.iloc[-1]], color=hx(GREEN), s=22, zorder=4)
    ax.annotate(f"{s.iloc[-1]:.1f}x", (s.index[-1], s.iloc[-1]), xytext=(5, 0), textcoords="offset points", fontsize=7, color=hx(GREEN),
                fontweight="bold", va="center")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}x"))
    ax.tick_params(axis="both", labelsize=6.5)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, handlelength=1.4, fontsize=6.5)
    ax.margins(x=0.03)
    return _save(fig, path)


def config_chart(chart, path: str | Path, size=DEFAULT_SIZE) -> Path:
    """Render a ``MarketChart`` from the YAML config."""
    series = [(s.get("name", ""), s.get("values", [])) for s in chart.series]
    if chart.type == "pie":
        return donut_chart(chart.categories, series[0][1] if series else [], path, center_text=series[0][0] if series else "",
                           size=(size[0] * 0.75, size[1]), value_format=chart.value_format)
    if chart.type == "line":
        return line_chart(chart.categories, series, path, value_format=chart.value_format, size=size, show_y=True)
    if chart.type == "stacked":
        return stacked_bars(chart.categories, series, path, value_format=chart.value_format, size=size)
    return grouped_bars(chart.categories, series, path, value_format=chart.value_format, size=size)
