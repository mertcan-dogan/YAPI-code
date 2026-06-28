"""CR-036 PDF design toolkit — matplotlib (Agg) chart factory.

Ported from the proven Heneka reference build (``heneka_report_reference_build.py``).
Renders the reusable chart family used by the management report as PNG files into
a caller-supplied directory. The caller passes ``dest_dir`` (typically a
``tempfile.mkdtemp()``) and is responsible for cleaning it up — these helpers
NEVER write to ``/tmp`` and never raise on empty/zero data.

Colour palette is imported from ``report_theme`` so the two modules stay in sync.
"""
import os
import itertools

import matplotlib
matplotlib.use("Agg")  # headless backend — MUST precede pyplot import
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.ticker import FuncFormatter

from app.services.report_theme import (
    FONTS_DIR,
    NAVY, PETROL, GOLD, INK, MUT, HAIR, RED, AMBER, GREEN,
)

_fonts_setup = False

# Per-process counter so repeated same-type calls into one dest_dir never collide.
_seq = itertools.count(1)


def _uname(base):
    """Unique-per-call PNG basename so callers can render N charts of one type."""
    return f"{base}_{next(_seq)}"

# Lato weights matplotlib should know about (family resolves to "Lato").
_MPL_LATO_FILES = ["Lato-Regular.ttf", "Lato-Medium.ttf", "Lato-Semibold.ttf", "Lato-Bold.ttf"]

# Default categorical palette (reference grouped/stacked charts).
_PALETTE = [NAVY, PETROL, GOLD]
# Default donut palette (reference h5).
_DONUT_PALETTE = [NAVY, PETROL, GOLD, GREEN, "#A9B2AC"]


def setup_matplotlib_fonts():
    """Register bundled Lato weights with matplotlib and set rcParams (idempotent)."""
    global _fonts_setup
    if _fonts_setup:
        return
    lato_dir = os.path.join(FONTS_DIR, "lato")
    for fn in _MPL_LATO_FILES:
        fm.fontManager.addfont(os.path.join(lato_dir, fn))
    # text.parse_math=False: never treat a '$' in a user-controlled label (vendor /
    # project / supplier name) as a mathtext expression — an unbalanced '$...$' would
    # otherwise raise during savefig and 500 the whole report.
    plt.rcParams.update({"font.family": "Lato", "font.size": 8, "text.color": INK,
                         "text.parse_math": False})
    _fonts_setup = True


# ---------------------------------------------------------------------------
# Internal helpers (reference axl() / save()).
# ---------------------------------------------------------------------------
def _axl(w, h):
    """Themed (fig, ax): white face, hidden top/right/left spines, y-grid only."""
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_facecolor("white")
    for sp in ["top", "right", "left"]:
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#C9D0C8")
    ax.tick_params(colors=MUT, length=0)
    ax.grid(axis="y", color="#E7EAE4", linewidth=0.9)
    ax.grid(axis="x", visible=False)
    return fig, ax


def _save(fig, dest_dir, name):
    """Tight-layout, save <dest_dir>/<name>.png at 150 dpi, close, return path."""
    fig.tight_layout(pad=0.3)
    path = os.path.join(dest_dir, name + ".png")
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    return path


def _mute_legend(lg):
    """Recolour legend text to the muted palette colour."""
    if lg is None:
        return
    for t in lg.get_texts():
        t.set_color(MUT)


def _placeholder(dest_dir, name):
    """A valid 'veri yok' PNG used when there is no data to plot."""
    fig, ax = plt.subplots(figsize=(7.0, 2.0))
    ax.set_facecolor("white")
    ax.axis("off")
    ax.text(0.5, 0.5, "veri yok", ha="center", va="center", fontsize=10, color=MUT)
    return _save(fig, dest_dir, name)


def _empty(*seqs):
    """True when every sequence is empty or sums to ~0 (guards no-data charts)."""
    for sq in seqs:
        if sq and any(abs(float(v)) > 1e-12 for v in sq):
            return False
    return True


# ---------------------------------------------------------------------------
# Reusable chart functions.
# ---------------------------------------------------------------------------
def chart_line(labels, values, dest_dir, *, color=NAVY, fill=False, value_suffix=""):
    """Line / area chart (reference h4)."""
    setup_matplotlib_fonts()
    name = _uname("chart_line")
    if not labels or _empty(values):
        return _placeholder(dest_dir, name)
    fig, ax = _axl(7.0, 2.2)
    x = range(len(values))
    ax.plot(labels, values, color=color, lw=2.2)
    if fill:
        ax.fill_between(x, values, min(values), color=color, alpha=0.07)
    if value_suffix:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}{value_suffix}"))
    return _save(fig, dest_dir, name)


def chart_combo(labels, bar_values, line_values, dest_dir, *,
                bar_label, line_label, bar_color=NAVY, line_color=GOLD):
    """Dual-axis bars + line (reference h1)."""
    setup_matplotlib_fonts()
    name = _uname("chart_combo")
    if not labels or _empty(bar_values, line_values):
        return _placeholder(dest_dir, name)
    fig, ax = _axl(7.0, 2.2)
    ax.bar(labels, bar_values, 0.55, color=bar_color, label=bar_label)
    ax.tick_params(colors=MUT, length=0)
    ax2 = ax.twinx()
    ax2.plot(labels, line_values, color=line_color, lw=2.4, marker="o", ms=4, label=line_label)
    ax2.tick_params(colors=MUT, length=0)
    for sp in ["top", "right", "left"]:
        ax2.spines[sp].set_visible(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    lg = ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left", ncol=2, fontsize=7.5)
    _mute_legend(lg)
    return _save(fig, dest_dir, name)


def chart_grouped_bar(labels, series, dest_dir, *, colors=None, value_labels=False, y_label=""):
    """Side-by-side grouped bars (reference h9). Single-series with
    ``value_labels=True`` covers AR-aging-style bars (reference h3).

    ``series`` is a list of ``(label, [values])`` tuples. ``colors`` indexes the
    series for multi-series; for a single series a per-bar colour list is honoured.
    """
    setup_matplotlib_fonts()
    name = _uname("chart_grouped_bar")
    if not labels or not series or _empty(*[vals for _, vals in series]):
        return _placeholder(dest_dir, name)
    colors = colors or _PALETTE
    fig, ax = _axl(7.0, 2.2)
    x = list(range(len(labels)))
    n = len(series)
    if n == 1:
        lbl, vals = series[0]
        bar_colors = colors if len(colors) == len(vals) else colors[0]
        b = ax.bar(x, vals, 0.6, color=bar_colors, label=lbl)
        if value_labels:
            ax.bar_label(b, padding=3, fontsize=7.5, color=INK, fontweight="bold")
    else:
        w = 0.8 / n
        for i, (lbl, vals) in enumerate(series):
            off = (i - (n - 1) / 2) * w
            b = ax.bar([xi + off for xi in x], vals, w, color=colors[i % len(colors)], label=lbl)
            if value_labels:
                ax.bar_label(b, padding=3, fontsize=7.5, color=INK, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    if y_label:
        ax.set_ylabel(y_label, fontsize=7, color=MUT)
    if n > 1:
        lg = ax.legend(frameon=False, fontsize=7.5, loc="upper left", ncol=min(n, 3))
        _mute_legend(lg)
    return _save(fig, dest_dir, name)


def chart_stacked_bar(labels, base_values, top_values, dest_dir, *,
                      base_label, top_label, base_color=NAVY, top_color=GOLD):
    """Stacked bars: top stacked on base (reference h6)."""
    setup_matplotlib_fonts()
    name = _uname("chart_stacked_bar")
    if not labels or _empty(base_values, top_values):
        return _placeholder(dest_dir, name)
    fig, ax = _axl(7.0, 2.2)
    x = list(range(len(labels)))
    ax.bar(x, base_values, 0.6, color=base_color, label=base_label)
    ax.bar(x, top_values, 0.6, bottom=base_values, color=top_color, label=top_label)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    # Headroom above the tallest stacked bar so the upper-right legend never overlaps it.
    totals = [b + t for b, t in zip(base_values, top_values)]
    top = max(totals) if totals else 0
    if top > 0:
        ax.set_ylim(0, top * 1.25)
    lg = ax.legend(frameon=False, fontsize=7.5, loc="upper right", ncol=2)
    _mute_legend(lg)
    return _save(fig, dest_dir, name)


def chart_hbar(labels, values, dest_dir, *, colors=None, value_fmt="₺{:.1f}"):
    """Horizontal bars with value labels, inverted y, x-grid only (ref h8/h10).

    ``colors`` may be a single colour or a per-bar list (e.g. RAG).
    """
    setup_matplotlib_fonts()
    name = _uname("chart_hbar")
    if not labels or _empty(values):
        return _placeholder(dest_dir, name)
    bar_colors = colors if colors else NAVY
    fig, ax = _axl(7.0, 2.0)
    y = range(len(labels))
    ax.barh(y, values, color=bar_colors, height=0.6)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#E7EAE4", linewidth=0.9)
    vmax = max(values)
    pad = (vmax * 0.02) if vmax else 0.02
    for i, v in enumerate(values):
        ax.text(v + pad, i, value_fmt.format(v), va="center", fontsize=7.5,
                color=INK, fontweight="bold")
    ax.set_xlim(0, vmax * 1.18 if vmax else 1)
    return _save(fig, dest_dir, name)


def chart_donut(labels, values, dest_dir, *, colors=None, center_top="", center_sub=""):
    """Donut chart with centre annotation and outside frameless legend (ref h5/h7)."""
    setup_matplotlib_fonts()
    name = _uname("chart_donut")
    if not labels or _empty(values):
        return _placeholder(dest_dir, name)
    colors = colors or _DONUT_PALETTE
    fig, ax = plt.subplots(figsize=(3.4, 2.1))
    ax.set_facecolor("white")
    ax.pie(values, colors=colors[:len(values)], startangle=90, counterclock=False,
           wedgeprops=dict(width=0.36, edgecolor="white", linewidth=2))
    if center_top:
        ax.text(0, 0.06, center_top, ha="center", va="center", fontsize=12,
                fontweight="bold", color=INK)
    if center_sub:
        ax.text(0, -0.16, center_sub, ha="center", va="center", fontsize=7.5, color=MUT)
    lg = ax.legend(labels, loc="center left", bbox_to_anchor=(0.94, 0.5), frameon=False,
                   fontsize=7, handlelength=1, labelspacing=0.5)
    _mute_legend(lg)
    return _save(fig, dest_dir, name)
