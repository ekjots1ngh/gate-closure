"""Figures for the README, drawn from data/out/results.json so they reproduce like every number.

Each figure is written twice, for GitHub's light and dark themes; the README picks one with
<picture>. gclose.report calls this; it has no entry point of its own.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt
import numpy as np

from . import DOCS

THEMES = {
    "light": {"ink": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "series": "#2a78d6"},
    "dark": {"ink": "#f0efec", "muted": "#c3c2b7", "grid": "#383835", "series": "#3987e5"},
}
COIN_FLIP_BRIER = 0.25


def _style(ax: plt.Axes, colors: dict) -> None:
    """Recessive axes: no box, light horizontal grid, muted tick labels."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(colors["grid"])
    ax.tick_params(colors=colors["muted"], length=0, labelsize=9)
    ax.grid(axis="y", color=colors["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def value_of_skill(results: dict, theme: str) -> plt.Figure:
    """Money against Brier score, with the real forecasts placed on the same axes.

    Left: the whole curve, from our errors scaled up to coin-flip accuracy down to none.
    Right: the narrow band where real forecasts live, against the no-forecast schedule.
    """
    colors = THEMES[theme]
    curve = sorted(results["value_of_skill"]["chain"], key=lambda point: point["brier"])
    brier = np.array([point["brier"] for point in curve])
    gbp = np.array([point["gbp"] for point in curve])
    money = {name: m["value"] for name, m in results["money"].items()}
    score = {s["model"]: s["brier"]["value"] for s in results["forecasts"]}
    schedule = money["chain/schedule"]
    forecasts = [
        (label, score[name], money[f"chain/{name}"])
        for name, label in (
            ("ours", "ours"),
            ("persistence_cal", "calibrated persistence"),
            ("indicated", "NESO indicated imbalance"),
        )
    ]

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "svg.fonttype": "none"})
    fig, (whole, zoom) = plt.subplots(1, 2, figsize=(10, 3.9), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.patch.set_alpha(0)

    for ax in (whole, zoom):
        _style(ax, colors)
        ax.patch.set_alpha(0)
        ax.plot(brier, gbp, color=colors["series"], linewidth=2, solid_capstyle="round", zorder=2)
        ax.axhline(schedule, color=colors["muted"], linewidth=1, linestyle=(0, (4, 3)), zorder=1)
        ax.axvline(COIN_FLIP_BRIER, color=colors["grid"], linewidth=1, zorder=1)
        ax.set_xlabel("Brier score  (better →)", color=colors["muted"], fontsize=9)
        ax.invert_xaxis()

    whole.set_xlim(0.30, -0.005)
    whole.set_ylim(-20, 240)
    whole.set_ylabel("£ per day", color=colors["muted"], fontsize=9)
    whole.scatter(
        [0], [money["chain/side_oracle"]], s=40, color=colors["series"], zorder=3, edgecolors=colors["series"]
    )
    whole.annotate(
        "knowing the side\nan hour early",
        (0, money["chain/side_oracle"]),
        xytext=(-8, -4),
        textcoords="offset points",
        ha="right",
        va="top",
        color=colors["ink"],
        fontsize=9,
    )
    whole.text(
        0.297, schedule - 5, f"no forecast, fixed schedule £{schedule:.0f}", color=colors["muted"], fontsize=9, va="top"
    )
    whole.text(COIN_FLIP_BRIER - 0.003, 200, "coin-flip\naccuracy", color=colors["muted"], fontsize=9, va="top")
    whole.set_title(
        "Money rises in a nearly straight line with accuracy", loc="left", color=colors["ink"], fontsize=11, pad=10
    )

    zoom.set_xlim(0.255, 0.224)
    zoom.set_ylim(22, 56)
    zoom.set_ylabel("£ per day", color=colors["muted"], fontsize=9)
    zoom.set_title("Where real forecasts sit", loc="left", color=colors["ink"], fontsize=11, pad=10)
    for name, x, y in forecasts:
        zoom.scatter([x], [y], s=48, color=colors["series"], edgecolors=colors["series"], zorder=3)
        zoom.annotate(
            f"{name}\n£{y:.1f}",
            (x, y),
            xytext=(7, -2),
            textcoords="offset points",
            ha="left",
            va="top",
            color=colors["ink"],
            fontsize=9,
        )
    zoom.text(
        COIN_FLIP_BRIER - 0.0005,
        54.5,
        "coin-flip accuracy,\nstill trading",
        color=colors["muted"],
        fontsize=9,
        va="top",
    )
    zoom.text(0.2545, schedule + 0.8, "no-forecast schedule", color=colors["muted"], fontsize=9)

    fig.tight_layout(w_pad=3)
    return fig


def reliability(results: dict, theme: str) -> plt.Figure:
    """Our forecast's reliability diagram, and how often it ventures far from a coin flip.

    Points on the diagonal mean a forecast of p comes true a share p of the time (calibration).
    The lower panel shows how rarely the forecast is confident, which is what limits resolution.
    """
    colors = THEMES[theme]
    ours = next(s for s in results["forecasts"] if s["model"] == "ours")["decomposition"]
    bins = ours["bins"]
    forecast = np.array([b["forecast"] for b in bins])
    observed = np.array([b["observed"] for b in bins])
    share = np.array([b["count"] for b in bins]) / sum(b["count"] for b in bins)

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "svg.fonttype": "none"})
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(5.2, 5.4), sharex=True, gridspec_kw={"height_ratios": [3, 1]}, layout="constrained"
    )
    fig.patch.set_alpha(0)
    for ax in (top, bottom):
        _style(ax, colors)
        ax.patch.set_alpha(0)
    top.plot([0, 1], [0, 1], color=colors["muted"], linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    top.plot(forecast, observed, color=colors["series"], linewidth=2, marker="o", markersize=5, zorder=2)
    top.set_xlim(0, 1)
    top.set_ylim(0, 1)
    top.set_ylabel("share that came true", color=colors["muted"], fontsize=9)
    top.text(0.04, 0.9, "dashed line: perfect calibration", color=colors["muted"], fontsize=9)
    top.set_title("Well calibrated, rarely confident", loc="left", color=colors["ink"], fontsize=11, pad=10)
    bottom.bar(forecast, share, width=0.07, color=colors["series"], alpha=0.85)
    bottom.set_ylabel("share of\nforecasts", color=colors["muted"], fontsize=9)
    bottom.set_xlabel("forecast probability that the grid is short", color=colors["muted"], fontsize=9)
    return fig


FIGURES = {"value_of_skill": value_of_skill, "reliability": reliability}


def write_all(results: dict) -> None:
    """Every README figure, in both themes, into docs/."""
    DOCS.mkdir(exist_ok=True)
    for name, draw in FIGURES.items():
        for theme in THEMES:
            fig = draw(results, theme)
            fig.savefig(DOCS / f"{name}_{theme}.svg", transparent=True, metadata={"Date": None})
            plt.close(fig)
