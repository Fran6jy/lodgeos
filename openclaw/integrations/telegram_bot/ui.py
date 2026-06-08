"""
Telegram UI kit — keyboards, card formatting, and copy.

Telegram has no CSS; the design vocabulary is: HTML text (<b>/<i>/<code>/<pre>),
inline keyboards (tap targets), emoji as iconography, and monospace blocks for
aligned tables. This module centralises that so every screen feels consistent.
"""

import os

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

# Public-facing brand. "OpenClaw" is the internal working name; override with
# BRAND_NAME so the user-facing UI shows the real product name.
BRAND = os.environ.get("BRAND_NAME", "LodgeOS")


def main_menu_kb() -> InlineKeyboardMarkup:
    """The home screen — a 2-column grid of the primary actions."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 This Week", callback_data="menu|summary"),
         InlineKeyboardButton("🗓 This Month", callback_data="menu|month")],
        [InlineKeyboardButton("🎯 Budgets", callback_data="menu|budget"),
         InlineKeyboardButton("💰 Income", callback_data="menu|income")],
        [InlineKeyboardButton("📉 Spending Chart", callback_data="menu|chart"),
         InlineKeyboardButton("🗂 Spaces", callback_data="menu|spaces")],
        [InlineKeyboardButton("🧾 History", callback_data="menu|history"),
         InlineKeyboardButton("📈 Dashboard", callback_data="menu|dashboard")],
        [InlineKeyboardButton("➕ Add entry", callback_data="menu|add"),
         InlineKeyboardButton("❓ Help", callback_data="menu|help")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    """A single 'back to menu' affordance shown on every sub-screen."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")]])


def category_kb(categories, timeframe: str = "month") -> InlineKeyboardMarkup:
    """Tappable category chips (drill-down) + a menu button."""
    rows, row = [], []
    for cat in categories[:8]:
        row.append(InlineKeyboardButton(cat, callback_data=f"cat|{cat}|{timeframe}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")])
    return InlineKeyboardMarkup(rows)


def spaces_kb(spaces, active: str) -> InlineKeyboardMarkup:
    """Switch the active Budget Space; the current one is marked."""
    rows, row = [], []
    for sp in spaces:
        mark = "✅ " if sp == active else ""
        row.append(InlineKeyboardButton(f"{mark}{sp}", callback_data=f"space|{sp}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")])
    return InlineKeyboardMarkup(rows)


def spaces_card(active: str) -> str:
    return card("🗂 Budget Spaces", (
        f"Active space: <b>{active}</b>\n\n"
        "Everything you log goes here. Switch below, or override per entry:\n"
        "<i>Business: spent £30 on Facebook ads</i>\n\n"
        "Create a new one with <code>/space &lt;name&gt;</code>."
    ))


def history_kb(offset: int, has_more: bool) -> InlineKeyboardMarkup:
    """Prev/Next pagination for the history list."""
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"hist|{max(offset - 10, 0)}"))
    if has_more:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"hist|{offset + 10}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")])
    return InlineKeyboardMarkup(rows)


def card(title: str, body: str = "", *, mono: bool = False) -> str:
    """A consistent 'card': bold title, divider, body (optionally monospaced)."""
    head = f"<b>{title}</b>\n────────────────────"
    if not body:
        return head
    body = f"<pre>{_esc(body)}</pre>" if mono else body
    return f"{head}\n{body}"


def welcome(name: str = "") -> str:
    hi = f" {name}" if name else ""
    return (
        f"✨ <b>{BRAND}</b>\n"
        f"Your money, in plain language.\n"
        f"────────────────────\n"
        f"Hi{hi} 👋  Just talk to me — type, speak, or snap a photo:\n\n"
        f"💬  <i>“Spent £4.50 at Nero for coffee”</i>\n"
        f"🎙  a voice note saying what you spent\n"
        f"🧾  a photo of a receipt or payslip\n\n"
        f"Tap a button below, or send <code>/menu</code> anytime."
    )


def help_text() -> str:
    return card("Help & Commands", (
        "<b>Just send naturally</b> — I’ll record it:\n"
        "• <i>Coffee at Costa £3.20</i>\n"
        "• <i>Received invoice £500</i>\n"
        "• <i>Actually that coffee was £6</i>  (correction)\n"
        "• <i>Delete the £5 one</i>  (void)\n\n"
        "<b>Inputs:</b> text · 🎙 voice · 🧾 photos\n\n"
        "<b>Commands</b>\n"
        "/menu — open the menu\n"
        "/summary · /month — spending\n"
        "/budget · /setbudget &lt;cat&gt; &lt;amt&gt;\n"
        "/income · /history\n"
        "/dashboard — private web view"
    ))


def add_help() -> str:
    return card("➕ Add an entry", (
        "Send me any of these and I’ll log it:\n\n"
        "💬  <i>Spent £12 on lunch</i>\n"
        "💬  <i>Paid £45 for Uber</i>\n"
        "💬  <i>Received salary £3200</i>\n"
        "🎙  a voice note\n"
        "🧾  a receipt / payslip photo\n\n"
        "I’ll auto-categorise and confirm."
    ))


def bot_commands() -> list:
    """Populates the Telegram '/' command menu next to the input box."""
    return [
        BotCommand("menu", "🏠 Open the menu"),
        BotCommand("summary", "📊 This week’s spending"),
        BotCommand("month", "🗓 This month’s summary"),
        BotCommand("budget", "🎯 Budgets vs actual"),
        BotCommand("setbudget", "✏️ Set a monthly budget"),
        BotCommand("income", "💰 Income this month"),
        BotCommand("history", "🧾 Recent transactions"),
        BotCommand("dashboard", "📈 Private web dashboard"),
        BotCommand("spaces", "🗂 Switch Budget Space"),
        BotCommand("help", "❓ How to use the bot"),
    ]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
