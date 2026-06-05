"""
Chart rendering for Telegram — returns PNG bytes to send as photos.

Uses matplotlib's headless Agg backend (no display needed). Dark palette to
match the bot/dashboard aesthetic. Kept dependency-light: only matplotlib.
"""

import io
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
