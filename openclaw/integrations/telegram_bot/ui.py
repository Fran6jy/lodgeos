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


# Per-space icon so the user always knows which space they're in.
_SPACE_ICONS = {"personal": "🏠", "business": "💼", "property": "🏢"}


def space_icon(space: str) -> str:
    return _SPACE_ICONS.get((space or "Personal").strip().lower(), "🗂")


def space_chip(space: str) -> str:
    """A small always-visible label, e.g. '🏠 Personal' / '💼 Business'."""
    space = space or "Personal"
    return f"{space_icon(space)} {space}"


def main_menu_kb() -> InlineKeyboardMarkup:
    """The home screen — a 2-column grid of the primary actions."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 This Week", callback_data="menu|summary"),
         InlineKeyboardButton("🗓 This Month", callback_data="menu|month")],
        [InlineKeyboardButton("🎯 Budgets", callback_data="menu|budget"),
         InlineKeyboardButton("💰 Income", callback_data="menu|income")],
        [InlineKeyboardButton("🎁 Wrapped", callback_data="menu|wrapped"),
         InlineKeyboardButton("📉 Spending Chart", callback_data="menu|chart")],
        [InlineKeyboardButton("💡 Insights", callback_data="menu|insights"),
         InlineKeyboardButton("🔁 Subscriptions", callback_data="menu|subs")],
        [InlineKeyboardButton("🗂 Spaces", callback_data="menu|spaces"),
         InlineKeyboardButton("🧾 History", callback_data="menu|history")],
        [InlineKeyboardButton("📈 Dashboard", callback_data="menu|dashboard"),
         InlineKeyboardButton("🔔 Reminders", callback_data="menu|reminders")],
        [InlineKeyboardButton("💖 Support", callback_data="menu|donate"),
         InlineKeyboardButton("✨ Examples", callback_data="menu|examples")],
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
    w = "✅" if reminders.get("wrapped") else "⬜️"
    text = card("🔔 Reminders", (
        "Get a gentle nudge so tracking becomes a habit:\n\n"
        f"{d} <b>Daily digest</b> — evening recap of today's spending\n"
        f"{b} <b>Morning briefing</b> — yesterday + month-to-date\n"
        f"{w} <b>Monthly Wrapped</b> — a shareable recap on the 1st 🎁\n\n"
        "<i>Tap to toggle. Sent at the times set by the bot host.</i>"
    ))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{d} Daily digest", callback_data="rem|digest")],
        [InlineKeyboardButton(f"{b} Morning briefing", callback_data="rem|briefing")],
        [InlineKeyboardButton(f"{w} Monthly Wrapped", callback_data="rem|wrapped")],
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
        ("👋 <b>Hi! I'm LodgeOS.</b>\n────────────────────\n"
         "I help you keep track of your money. You just talk to me — like texting a friend.\n\n"
         "Want a quick look? (about 30 seconds)",
         [[InlineKeyboardButton("Yes, show me ▶", callback_data="tut|1")],
          [InlineKeyboardButton("Skip", callback_data="tut|done")]]),

        ("<b>1 of 4 · Tell me what you spent</b> 💬\n────────────────────\n"
         "Type it, 🎙 say it, or 🧾 take a photo of a receipt.\n\n"
         "👉 <b>Try it:</b> send <i>Spent £3 on coffee</i>\n"
         "I'll sort it and tick it ✅. (or tap Next)",
         [[InlineKeyboardButton("Next ▶", callback_data="tut|2")]]),

        ("<b>2 of 4 · Ask me anything</b> ❓\n────────────────────\n"
         "I only use your own records — no guessing:\n"
         "• <i>How much did I spend this month?</i>\n"
         "• <i>How much at Tesco?</i>",
         [[InlineKeyboardButton("Next ▶", callback_data="tut|3")]]),

        ("<b>3 of 4 · Lists &amp; budgets</b> 🛒🎯\n────────────────────\n"
         "Going to the market? Make a list:\n"
         "<i>start a chai list: 3 ginger at 250, milk 1200</i>\n"
         "When you've paid: <i>bought chai</i>.\n\n"
         "Set a spending limit:\n"
         "<i>Set budget for food 100</i>",
         [[InlineKeyboardButton("Next ▶", callback_data="tut|4")]]),

        ("<b>4 of 4 · Keep things separate</b> 🗂\n────────────────────\n"
         "Home money and work money stay apart:\n"
         "<i>switch to business space</i>, or label one:\n"
         "<i>Business: spent £30 on ads</i>.\n\n"
         "That's it — you're ready! 🎉  Tap below anytime.",
         [[InlineKeyboardButton("Open menu 🏠", callback_data="tut|done")]]),
    ]
    step = max(0, min(step, len(steps) - 1))
    text, kb = steps[step]
    return text, InlineKeyboardMarkup(kb)


def welcome(name: str = "", space: str = "Personal") -> str:
    hi = f" {name}" if name else ""
    return (
        f"✨ <b>{BRAND}</b>  ·  {space_chip(space)}\n"
        f"Your money, in plain language.\n"
        f"────────────────────\n"
        f"Hi{hi} 👋  Just talk to me — type, speak, or snap a photo:\n\n"
        f"💬  <i>“Spent £4.50 on coffee”</i>\n"
        f"🎙  a voice note saying what you spent\n"
        f"🧾  a photo of a receipt or payslip\n\n"
        f"You can also <b>ask</b> (<i>“how much did I spend this month?”</i>), "
        f"make a 🛒 shopping list, or set a 🎯 budget.\n\n"
        f"Tap a button below, send <code>/menu</code>, or <code>/help</code> for the full guide."
    )


def help_text() -> str:
    return card("📖 How to use LodgeOS", (
        "Just talk to me like a friend. Type it, 🎙 say it, or 🧾 snap a photo.\n"
        "Here is everything you can do — with examples you can copy:\n\n"

        "<b>1️⃣ TELL ME WHAT YOU SPENT (or got)</b> 💬\n"
        "• <i>Spent £4.50 on coffee</i>\n"
        "• <i>Paid £45 for Uber</i>\n"
        "• <i>Got salary £3200</i>\n"
        "• Got money back? <i>Refund £10 for shoes</i>\n"
        "• Many at once: <i>£10 on rice and £20 on soap</i>\n"
        "Works in any money — £, $, ₦, € … I keep each on its own.\n"
        "💡 Tell me your everyday money once: <i>set my currency to naira</i> — "
        "then a plain <i>3000</i> means ₦3,000 (no need to type it each time).\n"
        "I sort it into the right group and show you a tick ✅.\n\n"

        "<b>2️⃣ ASK ME ANYTHING</b> ❓\n"
        "• <i>How much did I spend this month?</i>\n"
        "• <i>How much at Tesco?</i>\n"
        "• <i>What's my biggest expense?</i>\n\n"

        "<b>3️⃣ FIX A MISTAKE</b> ✏️\n"
        "• <i>Actually that coffee was £6</i>\n"
        "• <i>Delete the £5 one</i>\n\n"

        "<b>4️⃣ MAKE A SHOPPING LIST</b> 🛒\n"
        "• Start one: <i>start a chai list: 3 ginger at 250, milk 1200</i>\n"
        "• Add more: <i>add sugar 300</i>  ·  <i>add a flight 450 to the Dubai trip</i>\n"
        "• Change how many: <i>2 more ginger</i>  ·  <i>make milk 3</i>\n"
        "• Change a price: <i>ginger is now 300</i>\n"
        "• Take one off: <i>remove milk</i>\n"
        "• Put a label on it: <i>phone charger 5000 [shopping]</i>\n"
        "• See it: <i>show my list</i>  ·  all lists: /lists\n"
        "• When you've paid: <i>bought chai</i> → I log it for you.\n\n"

        "<b>5️⃣ SET A BUDGET (a spending limit)</b> 🎯\n"
        "• <i>Set budget for food 100</i>\n"
        "• See them: <i>show my budgets</i>  (or /budget)\n"
        "• Spend from one: <i>spent 20 from the food budget</i>\n"
        "• Rename one: <i>rename the food budget to groceries</i>\n"
        "• Remove one: <i>delete the food budget</i>  ·  all: <i>delete all budgets</i>\n"
        "• Turn a price list into budgets: <i>turn this list into a budget</i>\n\n"

        "<b>6️⃣ KEEP THINGS SEPARATE</b> 🗂\n"
        "Personal · Business · Property don't mix:\n"
        "• <i>switch to business space</i>\n"
        "• or label one: <i>Business: spent £30 on ads</i>\n"
        "• make a new one: <code>/space Side Hustle</code>\n\n"

        "<b>7️⃣ SEE YOUR NUMBERS &amp; GET NUDGES</b> 📊\n"
        "/summary — this week  ·  /month — this month\n"
        "/income — money in  ·  /history — past entries\n"
        "/insights — how this month compares to last\n"
        "/subscriptions — bills that repeat\n"
        "/dashboard — your own private web page\n"
        "🔔 /reminders — a little daily recap + morning hello\n\n"

        "💡 <b>Easiest of all:</b> send /menu and just tap the buttons — "
        "every feature here is one tap away."
    ))


def examples_card() -> str:
    """A tiny starter card — copy any line and send it."""
    return card("✨ Try these — just copy &amp; send", (
        "Tap to copy a line, then send it to me:\n\n"
        "💬  <code>Spent £4 on coffee</code>\n"
        "💬  <code>Got salary £3200</code>\n"
        "❓  <code>How much did I spend this month?</code>\n"
        "🛒  <code>start a chai list: 3 ginger at 250, milk 1200</code>\n"
        "🎯  <code>Set budget for food 100</code>\n"
        "🗂  <code>switch to business space</code>\n\n"
        "More in /help, or tap /menu for buttons."
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
        BotCommand("wrapped", "🎁 Your shareable monthly recap"),
        BotCommand("insights", "💡 Spending insights vs last month"),
        BotCommand("subscriptions", "🔁 Detect recurring charges"),
        BotCommand("lists", "🛒 Shopping / price lists"),
        BotCommand("reminders", "🔔 Daily digest / morning briefing"),
        BotCommand("digest", "📊 Preview today's digest"),
        BotCommand("history", "🧾 Recent transactions"),
        BotCommand("dashboard", "📈 Private web dashboard"),
        BotCommand("spaces", "🗂 Switch Budget Space"),
        BotCommand("examples", "✨ Copy-and-send starter examples"),
        BotCommand("help", "❓ How to use the bot"),
        BotCommand("donate", "💖 Buy the dev a coffee"),
    ]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
