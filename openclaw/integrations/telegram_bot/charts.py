"""
Chart rendering for Telegram — returns PNG bytes to send as photos.

Uses matplotlib's headless Agg backend (no display needed). Dark palette to
match the bot/dashboard aesthetic. Kept dependency-light: only matplotlib.
"""

import io
import re
from typing import Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Cohesive categorical palette (GitHub-dark-ish), reused across charts.
PALETTE = ["#388bfd", "#3fb950", "#db61a2", "#f0883e", "#a371f7",
           "#e3b341", "#39c5cf", "#f85149", "#8b949e", "#6e7681"]

_BG = "#0f1419"
_FG = "#e6edf3"
_MUTED = "#8b949e"


def category_donut(by_category: Dict[str, float], title: str, currency_symbol: str = "£") -> bytes:
    """Render a donut of spending by category. Returns PNG bytes."""
    items = [(k, v) for k, v in by_category.items() if v > 0]
    if not items:
        return _empty_card(title)

    # Collapse a long tail into "Other" so the donut stays legible.
    items.sort(key=lambda x: -x[1])
    if len(items) > 7:
        head, tail = items[:6], items[6:]
        items = head + [("Other", sum(v for _, v in tail))]

    labels = [k for k, _ in items]
    values = [v for _, v in items]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(6, 6), dpi=160)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)

    wedges, _ = ax.pie(
        values, startangle=90, counterclock=False,
        colors=PALETTE[:len(values)],
        wedgeprops=dict(width=0.42, edgecolor=_BG, linewidth=3),
    )

    # Centre total.
    ax.text(0, 0.08, f"{currency_symbol}{total:,.0f}", ha="center", va="center",
            color=_FG, fontsize=26, fontweight="bold")
    ax.text(0, -0.16, title, ha="center", va="center", color=_MUTED, fontsize=11)

    # Legend with amounts + share.
    legend_labels = [f"{lab}  {currency_symbol}{val:,.0f}  ({val / total * 100:.0f}%)"
                     for lab, val in zip(labels, values)]
    ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
              frameon=False, labelcolor=_FG, fontsize=11)
    ax.set_aspect("equal")

    return _save(fig)


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF️]")


def _plain(s: str) -> str:
    """Drop emoji/symbols matplotlib's font can't draw (they'd render as boxes)."""
    return _EMOJI_RE.sub("", s or "").strip(" ·-")


def monthly_wrapped(recap: dict, brand: str = "LodgeOS", currency_symbol: str = "£") -> bytes:
    """Render a shareable 'Wrapped'-style recap poster. Returns PNG bytes."""
    fig, ax = plt.subplots(figsize=(6, 8), dpi=160)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def t(x, y, s, **kw):
        ax.text(x, y, s, transform=ax.transAxes, **kw)

    # Header
    t(0.5, 0.95, f"{recap['label']}  ·  WRAPPED", ha="center", color=_FG, fontsize=21, fontweight="bold")
    t(0.5, 0.905, f"{_plain(recap['space'])} · {brand}", ha="center", color=_MUTED, fontsize=12)

    if recap.get("empty"):
        t(0.5, 0.5, "Nothing logged yet —\nstart and your Wrapped fills up ✨",
          ha="center", va="center", color=_MUTED, fontsize=15)
        return _save(fig)

    # Hero number
    t(0.5, 0.82, "you spent", ha="center", color=_MUTED, fontsize=13)
    t(0.5, 0.745, f"{currency_symbol}{recap['spent']:,.0f}", ha="center", color="#388bfd",
      fontsize=44, fontweight="bold")

    # Category bars
    y = 0.62
    cats = list(recap["by_category"].items())[:5]
    top_val = cats[0][1] if cats else 1
    for i, (cat, amt) in enumerate(cats):
        frac = (amt / top_val) if top_val else 0
        ax.add_patch(plt.Rectangle((0.08, y - 0.018), 0.84 * frac, 0.03,
                                   transform=ax.transAxes, color=PALETTE[i % len(PALETTE)], zorder=2))
        ax.add_patch(plt.Rectangle((0.08, y - 0.018), 0.84, 0.03,
                                   transform=ax.transAxes, color="#1c2230", zorder=1))
        t(0.08, y + 0.022, _plain(cat), color=_FG, fontsize=11)
        t(0.92, y + 0.022, f"{currency_symbol}{amt:,.0f}", ha="right", color=_MUTED, fontsize=11)
        y -= 0.075

    # Biggest single + badges
    big = recap.get("biggest")
    if big:
        t(0.08, 0.215, "biggest single", color=_MUTED, fontsize=11)
        t(0.92, 0.215, f"{currency_symbol}{(big.get('amount') or 0):,.0f} · {_plain(big.get('description') or '')[:22]}",
          ha="right", color=_FG, fontsize=11)
    for i, badge in enumerate(recap.get("badges", [])[:3]):
        t(0.5, 0.15 - i * 0.045, _plain(badge), ha="center", color="#3fb950", fontsize=12.5, fontweight="bold")

    return _save(fig)


def _empty_card(title: str) -> bytes:
    fig, ax = plt.subplots(figsize=(6, 3), dpi=160)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.axis("off")
    ax.text(0.5, 0.5, f"No spending yet\n{title}", ha="center", va="center",
            color=_MUTED, fontsize=14)
    return _save(fig)


def _save(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    return buf.getvalue()
