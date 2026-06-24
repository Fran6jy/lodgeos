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


# ── Premium "Wrapped" poster (Pillow) ──────────────────────────────────────
# A curated, tonal green/teal/sage palette — cohesive, not stark primaries.
_W_BG = (13, 17, 23)        # near-black canvas
_W_CARD = (22, 28, 36)      # highlight card / track base (lighter than canvas)
_W_BORDER = (38, 46, 58)
_W_TEXT = (240, 244, 248)
_W_MUTED = (140, 150, 162)
_W_ACCENT = (52, 211, 153)  # emerald
_W_GLOW = (59, 130, 246)    # soft blue ambient
_W_CURATED = {
    "Food & Drink": "#34D399", "Groceries": "#10B981", "Transport": "#86B8A1",
    "Shopping": "#6EE7C7", "Utilities": "#5EAAD8", "Entertainment": "#7FB3D5",
    "Health": "#9AE6B4", "Rent": "#A3B8CC", "Education": "#5EC8C0",
    "Marketing": "#B5C99A", "Salary": "#34D399", "Freelance": "#6EE7C7",
    "Investment": "#5EAAD8", "Income": "#34D399", "Other": "#8FA3AD",
}

_FONT_DIR = __import__("os").path.join(__import__("os").path.dirname(__file__), "assets", "fonts")


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _blend(bg, fg, t):
    return tuple(round(bg[i] + (fg[i] - bg[i]) * t) for i in range(3))


def _wfont(size, kind="regular"):
    """Load a premium font (Clash Display / Inter dropped into assets/fonts) if
    present, else fall back to bundled DejaVu — keeping a real weight hierarchy."""
    import os
    from PIL import ImageFont
    names = {
        "display": ["ClashDisplay-Bold.ttf", "ClashDisplay-Semibold.ttf", "Inter-Bold.ttf"],
        "bold": ["Inter-Bold.ttf", "Inter-SemiBold.ttf"],
        "medium": ["Inter-Medium.ttf", "Inter-Regular.ttf"],
        "regular": ["Inter-Regular.ttf"],
    }[kind]
    for n in names:
        p = os.path.join(_FONT_DIR, n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    import matplotlib.font_manager as fm
    weight = "bold" if kind in ("display", "bold") else "normal"
    return ImageFont.truetype(fm.findfont(fm.FontProperties(weight=weight)), size)


def monthly_wrapped(recap: dict, brand: str = "LodgeOS", currency_symbol: str = "£",
                    bot_username: str = "LodgeOS_bot") -> bytes:
    """Render a premium, shareable 'Wrapped' recap poster. Returns PNG bytes."""
    from PIL import Image, ImageDraw, ImageFilter
    W, H, M = 1080, 1350, 88
    base = Image.new("RGB", (W, H), _W_BG)

    # Ambient lighting: a soft radial blue glow behind the hero number.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx, gy, gr = W // 2, 430, 300
    gd.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=_W_GLOW + (46,))
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(base)

    def text(xy, s, font, fill, anchor="la"):
        d.text(xy, s, font=font, fill=fill, anchor=anchor)

    # Header (kicker + brand)
    text((W // 2, 86), f"{recap['label'].upper()}   ·   WRAPPED", _wfont(40, "bold"), _W_TEXT, "ma")
    text((W // 2, 140), f"{_plain(recap['space'])} · {brand}", _wfont(28, "regular"), _W_MUTED, "ma")

    if recap.get("empty"):
        text((W // 2, H // 2 - 20), "Nothing logged yet", _wfont(46, "display"), _W_TEXT, "mm")
        text((W // 2, H // 2 + 40), "start, and your Wrapped fills up.", _wfont(30, "regular"), _W_MUTED, "mm")
        text((W // 2, H - 70), f"Tracked effortlessly via Telegram @{bot_username}",
             _wfont(27, "medium"), _W_MUTED, "ma")
        return _png(base)

    # Hero
    text((W // 2, 300), "YOU SPENT", _wfont(32, "medium"), _W_MUTED, "ma")
    text((W // 2, 360), f"{currency_symbol}{recap['spent']:,.0f}", _wfont(150, "display"), _W_TEXT, "ma")

    # Category rows — strict grid: labels locked left, values locked right.
    cats = list(recap["by_category"].items())[:5]
    top_val = max((v for _, v in cats), default=1) or 1
    y = 600
    bar_h, step = 22, 96
    for cat, amt in cats:
        color = _hex(_W_CURATED.get(cat, "#8FA3AD"))
        track = _blend(_W_BG, color, 0.13)              # ~10–13% tint track
        text((M, y), _plain(cat), _wfont(38, "medium"), _W_TEXT, "lm")
        text((W - M, y), f"{currency_symbol}{amt:,.0f}", _wfont(38, "bold"), _W_TEXT, "rm")
        by = y + 34
        d.rounded_rectangle([M, by, W - M, by + bar_h], radius=bar_h // 2, fill=track)
        fw = max(bar_h, int((W - 2 * M) * (amt / top_val)))
        d.rounded_rectangle([M, by, M + fw, by + bar_h], radius=bar_h // 2, fill=color)
        y += step

    # Highlight card — isolate the key insight in its own rounded container.
    big = recap.get("biggest")
    if big:
        cy0 = y + 18
        cy1 = cy0 + 150
        d.rounded_rectangle([M, cy0, W - M, cy1], radius=28, fill=_W_CARD, outline=_W_BORDER, width=2)
        text((M + 40, cy0 + 36), "BIGGEST SINGLE", _wfont(26, "bold"), _W_ACCENT, "lm")
        text((M + 40, cy0 + 100), _plain(big.get("description") or "")[:30], _wfont(34, "medium"), _W_TEXT, "lm")
        text((W - M - 40, cy0 + 100), f"{currency_symbol}{(big.get('amount') or 0):,.0f}",
             _wfont(44, "display"), _W_TEXT, "rm")
        y = cy1

    # Badges — one cohesive centered line (emerald), no boxes-as-glyphs.
    badges = [_plain(b) for b in recap.get("badges", []) if _plain(b)]
    if badges:
        text((W // 2, y + 70), "   ·   ".join(badges[:3]), _wfont(30, "medium"), _W_ACCENT, "ma")

    # Footer — organic growth: where to find the app.
    text((W // 2, H - 64), f"Tracked effortlessly via Telegram @{bot_username}",
         _wfont(28, "medium"), _W_MUTED, "ma")
    return _png(base)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
