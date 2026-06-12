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
         InlineKeyboardButton("💡 Insights", callback_data="menu|insights")],
        [InlineKeyboardButton("🔁 Subscriptions", callback_data="menu|subs"),
         InlineKeyboardButton("🗂 Spaces", callback_data="menu|spaces")],
        [InlineKeyboardButton("🧾 History", callback_data="menu|history"),
         InlineKeyboardButton("📈 Dashboard", callback_data="menu|dashboard")],
        [InlineKeyboardButton("🔔 Reminders", callback_data="menu|reminders"),
         InlineKeyboardButton("💖 Support", callback_data="menu|donate")],
        [InlineKeyboardButton("❓ Help", callback_data="menu|help")],
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


def donate_card_and_kb():
    """Support screen: coffee-sized PayPal buttons + custom amount. Returns (text, kb).

    Reads DONATE_URL (e.g. https://paypal.me/yourname). Amount buttons append
    /<amount> per PayPal.me convention; Custom opens the bare link."""
    url = os.environ.get("DONATE_URL", "").rstrip("/")
    if not url:
        return card("💖 Support", "Donations aren't set up yet."), back_kb()
    text = card("💖 Support LodgeOS", (
        "LodgeOS is free and runs on coffee.\n"
        "If it saves you time, you can fuel the developer ☕\n\n"
        "<i>Totally optional — the bot stays free either way.</i>"
    ))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ £3", url=f"{url}/3"),
         InlineKeyboardButton("☕☕ £5", url=f"{url}/5"),
         InlineKeyboardButton("🍰 £10", url=f"{url}/10")],
        [InlineKeyboardButton("✏️ Custom amount", url=url)],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")],
    ])
    return text, kb


def reminders_card_and_kb(reminders: dict):
    """Toggle screen for the daily digest + morning briefing. Returns (text, kb)."""
    d = "✅" if reminders.get("digest") else "⬜️"
    b = "✅" if reminders.get("briefing") else "⬜️"
    text = card("🔔 Reminders", (
        "Get a gentle nudge so tracking becomes a habit:\n\n"
        f"{d} <b>Daily digest</b> — evening recap of today's spending\n"
        f"{b} <b>Morning briefing</b> — yesterday + month-to-date\n\n"
        "<i>Tap to toggle. Sent once a day at the times set by the bot host.</i>"
    ))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{d} Daily digest", callback_data="rem|digest")],
        [InlineKeyboardButton(f"{b} Morning briefing", callback_data="rem|briefing")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu|home")],
    ])
    return text, kb


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


def tutorial(step: int):
    """A short interactive first-run tour. Returns (text, keyboard)."""
    steps = [
        ("👋 <b>Welcome to LodgeOS!</b>\n────────────────────\n"
         "I turn what you say into organised money records — no spreadsheets, no forms.\n\n"
         "Take the 30-second tour?",
         [[InlineKeyboardButton("Start tour ▶", callback_data="tut|1")],
          [InlineKeyboardButton("Skip", callback_data="tut|done")]]),

        ("<b>Step 1 of 3 · Record anything</b> 💬\n────────────────────\n"
         "Just tell me what happened — type it, 🎙 say it, or 🧾 snap a receipt.\n\n"
         "👉 <b>Try it now:</b> send <i>Spent £3 on coffee</i>\n"
         "(or tap Next to keep reading)",
         [[InlineKeyboardButton("Next ▶", callback_data="tut|2")]]),

        ("<b>Step 2 of 3 · Ask anything</b> ❓\n────────────────────\n"
         "I answer from your own records — no guessing:\n"
         "• <i>How much have I spent this month?</i>\n"
         "• <i>How much at Tesco?</i>",
         [[InlineKeyboardButton("Next ▶", callback_data="tut|3")]]),

        ("<b>Step 3 of 3 · Keep things separate</b> 🗂\n────────────────────\n"
         "Personal · Business · Property — kept apart so they don't mix.\n"
         "Say <i>switch to business space</i>, or tag one entry: <i>Business: spent £30 on ads</i>.\n\n"
         "That's it — you're ready! 🎉",
         [[InlineKeyboardButton("Open menu 🏠", callback_data="tut|done")]]),
    ]
    step = max(0, min(step, len(steps) - 1))
    text, kb = steps[step]
    return text, InlineKeyboardMarkup(kb)


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
        f"You can also <b>ask</b> — <i>“how much did I spend this month?”</i>\n\n"
        f"Tap a button below, send <code>/menu</code>, or <code>/help</code> for the full guide."
    )


def help_text() -> str:
    return card("📖 How to use LodgeOS", (
        "No apps, no forms — just talk to me. Here's everything:\n\n"

        "<b>1️⃣ RECORD — tell me what happened</b>\n"
        "Type it, say it, or snap it:\n"
        "• <i>Spent £4.50 at Nero for coffee</i>\n"
        "• 🎙 a voice note of what you spent\n"
        "• 🧾 a photo of a receipt or payslip\n"
        "I auto-categorise and confirm each one.\n\n"

        "<b>2️⃣ ASK — questions about your money</b>\n"
        "• <i>How much have I spent this month?</i>\n"
        "• <i>How much have I spent at Tesco?</i>\n"
        "• <i>What's my biggest expense?</i>\n\n"

        "<b>3️⃣ FIX — correct or undo</b>\n"
        "• <i>Actually that coffee was £6</i>\n"
        "• <i>Delete the £5 one</i>  (kept for audit, not lost)\n\n"

        "<b>4️⃣ SPACES — keep things separate</b> 🗂\n"
        "Split Personal / Business / Property so they don't mix:\n"
        "• <i>switch to business space</i>\n"
        "• or tag one entry: <i>Business: spent £30 on ads</i>\n"
        "• new space: <code>/space Side Hustle</code>\n\n"

        "<b>5️⃣ SEE — your numbers</b>\n"
        "/summary · /month — spending\n"
        "/budget · /setbudget &lt;cat&gt; &lt;amt&gt;\n"
        "/income · /history\n"
        "/insights — vs last month · /subscriptions\n"
        "/dashboard — private web view\n\n"

        "💡 <b>Tip:</b> send /menu for tap-buttons — no need to remember commands."
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
        BotCommand("insights", "💡 Spending insights vs last month"),
        BotCommand("subscriptions", "🔁 Detect recurring charges"),
        BotCommand("reminders", "🔔 Daily digest / morning briefing"),
        BotCommand("digest", "📊 Preview today's digest"),
        BotCommand("history", "🧾 Recent transactions"),
        BotCommand("dashboard", "📈 Private web dashboard"),
        BotCommand("spaces", "🗂 Switch Budget Space"),
        BotCommand("help", "❓ How to use the bot"),
        BotCommand("donate", "💖 Buy the dev a coffee"),
    ]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
