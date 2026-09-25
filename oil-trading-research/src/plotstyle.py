"""Shared matplotlib style for result charts (light surface, validated categorical palette).

Palette = dataviz reference instance (slots 1-3 validated all-pairs; aqua is < 3:1 on the light
surface, so every chart carries a legend / direct labels and the numbers are in the CSV/markdown tables).
Instrument colours are fixed: WTI = slot 1 blue, Brent = slot 2 orange, NatGas = slot 3 aqua.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL = "#f0efec"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SYM_COLOR = {"XTIUSD": SERIES[0], "XBRUSD": SERIES[1], "XNGUSD": SERIES[2]}
SYM_LABEL = {"XTIUSD": "WTI (XTIUSD)", "XBRUSD": "Brent (XBRUSD)", "XNGUSD": "NatGas (XNGUSD)"}
DE_EMPH = "#b9b8b1"  # gray for context series
CRITICAL = "#d03b3b"  # status: critical (ruin / stop-out markers only)
DIVERGING = LinearSegmentedColormap.from_list("bluered", ["#184f95", "#6da7ec", NEUTRAL, "#ee9493", "#b3302f"])

DPI = 144


def apply():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.7, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "axes.titlesize": 11, "axes.titleweight": "semibold", "axes.titlelocation": "left",
        "axes.labelsize": 9.5, "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "grid.linestyle": "-", "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "legend.fontsize": 8.5, "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"], "lines.linewidth": 1.1,
        "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round", "figure.dpi": DPI,
        "text.color": INK, "xtick.major.size": 0, "ytick.major.size": 0,
    })


def subtitle(fig, text, y=0.955):
    fig.text(0.012, y, text, fontsize=9, color=INK2, ha="left", va="top")


def title(fig, text, y=0.995):
    fig.text(0.012, y, text, fontsize=12.5, color=INK, ha="left", va="top", weight="semibold")


def save(fig, path):
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
