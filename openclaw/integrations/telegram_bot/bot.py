"""
OpenClaw Telegram Bot — skeleton for Phase 2.

Install: pip install python-telegram-bot
Run:     TELEGRAM_TOKEN=<token> ANTHROPIC_API_KEY=<key> python -m openclaw.integrations.telegram_bot.bot

All messages route through the same AgentOrchestrator as the CLI.
Each Telegram user_id gets their own ledger partition via user_id.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

_PKG_ROOT = str(Path(__file__).resolve().parents[3])
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

logger = logging.getLogger(__name__)

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed. Run: pip install python-telegram-bot")


def _build_orchestrator(use_mock: bool = False):
    from openclaw.core.agent_orchestrator import AgentOrchestrator
    from openclaw.core.router import Router
    from openclaw.domains.finance.finance_plugin import FinancePlugin, build_llm_categoriser
    from openclaw.storage.sqlite_adapter import SQLiteAdapter

    from openclaw.llm.factory import build_llm_client, build_vision_client

    db = SQLiteAdapter(os.environ.get("OPENCLAW_DB", "openclaw.db"))
    finance = FinancePlugin(db)
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)

    # Chains Anthropic → OpenRouter automatically; mock bypasses both.
    llm = build_llm_client(use_mock=use_mock)
    # Semantic category fallback for items the keyword list misses (cached).
    finance.llm_categorize = build_llm_categoriser(llm, db)
    try:
        vision = build_vision_client(use_mock=use_mock)
    except Exception as e:
        logger.warning("Vision/image parsing disabled: %s", e)
        vision = None
    return AgentOrchestrator(llm_client=llm, router=router, vision_client=vision), finance


# Module-level orchestrator (initialised on first use)
_orchestrator = None
_finance_plugin = None
_transcriber = None
_USE_MOCK = False

# Holds pending interactive choices (e.g. ambiguous correction menus) keyed by token.
# SQLite-backed so menus survive bot restarts (in-memory would lose them).
from openclaw.integrations.session_store import SqliteSessionStore
from openclaw.integrations.telegram_bot.progress_manager import ProgressManager, _TYPING as _PM_TYPING
from openclaw.utils.currency_normalizer import format_amount
_sessions = SqliteSessionStore(os.environ.get("OPENCLAW_DB", "openclaw.db"))


def _get_orchestrator():
    global _orchestrator, _finance_plugin
    if _orchestrator is None:
        _orchestrator, _finance_plugin = _build_orchestrator(use_mock=_USE_MOCK)
    return _orchestrator, _finance_plugin


def _get_transcriber():
    """Lazily build the configured (local/cloud) transcriber."""
    global _transcriber
    if _transcriber is None:
        from openclaw.integrations.transcription import build_transcriber
        _transcriber = build_transcriber()
    return _transcriber


# -------------------------------------------------------------------------
# Handlers
# -------------------------------------------------------------------------

from openclaw.integrations.telegram_bot import ui


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name if update.effective_user else ""
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    # Capture a referral from a /start?ref_<id> deep link (once, for new users).
    if context.args and context.args[0].startswith("ref_"):
        referrer = context.args[0][4:]
        if referrer.isdigit() and fp.db.set_referred_by(uid, referrer):
            logger.info("Referral: user %s joined via %s", uid, referrer)

    is_new = not fp.db.get_tutorial_done(uid) and not fp.db.query_records(domain="finance", user_id=uid, limit=1)
    # New users join the gentle engagement loop by default (toggle off via /reminders).
    if is_new:
        for _k in ("digest", "briefing", "wrapped"):
            fp.db.set_reminder(uid, _k, True)

    # Pin the "How to use" guide once, so it's always one tap away at the top.
    if not fp.db.get_help_pinned(uid):
        try:
            msg = await update.message.reply_text(ui.help_text(), parse_mode="HTML",
                                                  disable_web_page_preview=True)
            await context.bot.pin_chat_message(update.effective_chat.id, msg.message_id,
                                               disable_notification=True)
            fp.db.set_help_pinned(uid)
        except Exception:
            logger.warning("Could not pin help for %s", uid, exc_info=True)

    # First-run interactive tour: only for genuinely new users (no records yet).
    if is_new:
        text, kb = ui.tutorial(0)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return
    await update.message.reply_text(
        ui.welcome(name, fp.db.get_active_space(uid)), parse_mode="HTML", reply_markup=ui.main_menu_kb()
    )


async def tutorial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Advance or finish the first-run tour."""
    q = update.callback_query
    await q.answer()
    arg = q.data.split("|", 1)[1]
    _, fp = _get_orchestrator()
    if arg == "done":
        uid = str(q.from_user.id)
        fp.db.set_tutorial_done(uid)
        name = q.from_user.first_name or ""
        await q.edit_message_text(ui.welcome(name, fp.db.get_active_space(uid)),
                                  parse_mode="HTML", reply_markup=ui.main_menu_kb())
        return
    text, kb = ui.tutorial(int(arg))
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    await update.message.reply_text(
        ui.welcome("", fp.db.get_active_space(uid)), parse_mode="HTML", reply_markup=ui.main_menu_kb()
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ui.help_text(), parse_mode="HTML", reply_markup=ui.back_kb(),
                                    disable_web_page_preview=True)


async def examples_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ui.examples_card(), parse_mode="HTML", reply_markup=ui.back_kb())


def _fmt_day(iso: str) -> str:
    """'2026-06-23T..' → '23 Jun'."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b") if iso else ""
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(iso).strftime("%d %b").lstrip("0")
        except Exception:
            return (iso or "")[:10]


def _tx_line(r) -> str:
    """One transaction as tidy HTML: icon · date · bold amount — description."""
    from html import escape
    from openclaw.domains.finance.finance_plugin import category_icon
    is_income = r.get("type") == "income"
    icon = "💰" if is_income else category_icon(r.get("entities", {}).get("category", "Other"))
    amt = format_amount(r.get("amount") or 0, r.get("currency", "GBP"))
    sign = "+" if is_income else ""
    desc = escape((r.get("description", "") or "")[:28])
    return f"{icon} <i>{_fmt_day(r.get('timestamp',''))}</i>  <b>{sign}{amt}</b> — {desc}"


def _history_page(fp, user_id: str, offset: int = 0, n: int = 10):
    """Return (card_text, keyboard) for one page of history."""
    rows = fp.db.query_records(domain="finance", user_id=user_id, limit=offset + n + 1)
    page = rows[offset:offset + n]
    has_more = len(rows) > offset + n
    if not page:
        return ui.card("🧾 History", "No more records." if offset else
                       "No records yet — send me an expense to start. ✨"), ui.history_kb(offset, False)
    body = "\n".join(_tx_line(r) for r in page)
    title = f"🧾 History  ·  {offset + 1}–{offset + len(page)}"
    return ui.card(title, body), ui.history_kb(offset, has_more)


async def _dashboard_text(fp, user_id: str) -> str:
    ttl = int(os.environ.get("DASHBOARD_TTL", "3600"))
    token = fp.db.create_dashboard_token(user_id, ttl_seconds=ttl)
    base = os.environ.get("DASHBOARD_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return ui.card("📈 Your private dashboard", (
        f"<a href=\"{base}/d/{token}\">Open dashboard →</a>\n\n"
        f"Valid {ttl // 60} min · shows only your data.\n"
        f"🔒 Don’t share this link."
    ))


def _share_link(bot_username: str, uid: str) -> str:
    """A Telegram deep link that opens the bot and attributes the referral."""
    return f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else ""


def _build_wrapped(fp, uid: str, bot_username: str = "", month_offset: int = 0):
    """Return (png_bytesio, caption, recap) for the Wrapped poster."""
    import io
    from openclaw.integrations.telegram_bot import charts
    from openclaw.utils.currency_normalizer import CODE_SYMBOLS
    space = fp.db.get_active_space(uid)
    recap = fp.monthly_recap(uid, space=space, month_offset=month_offset)
    symbol = CODE_SYMBOLS.get(recap["currency"], "") or recap["currency"] + " "
    png = charts.monthly_wrapped(recap, brand=ui.BRAND, currency_symbol=symbol,
                                 bot_username=bot_username or "LodgeOS_bot")
    caption = f"✨ <b>My {recap['label']} on {ui.BRAND}</b> — tracked just by talking to a bot."
    link = _share_link(bot_username, uid)
    if link:
        caption += f"\nForward this — your friends start here 👉 {link}"
    return io.BytesIO(png), caption, recap


async def _send_wrapped(target, fp, uid: str, bot_username: str = "", month_offset: int = 0) -> None:
    """Send the Wrapped poster to a message/callback target (reply_photo)."""
    buf, caption, _ = _build_wrapped(fp, uid, bot_username, month_offset)
    await target.reply_photo(photo=buf, caption=caption, parse_mode="HTML", reply_markup=ui.back_kb())


async def wrapped_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    await _send_wrapped(update.message, fp, str(update.effective_user.id),
                        bot_username=context.bot.username)


async def _send_chart(q, fp, uid: str) -> None:
    """Render a spending donut and send it as a photo with category drill-down chips."""
    import io
    from openclaw.integrations.telegram_bot import charts
    space = fp.db.get_active_space(uid)
    by_cat = fp.category_breakdown("month", uid, space=space)
    from openclaw.utils.currency_normalizer import CODE_SYMBOLS
    symbol = CODE_SYMBOLS.get(fp._user_currency(uid, space), "")
    png = charts.category_donut(by_cat, f"This month · {space}", currency_symbol=symbol or "£")
    cats = list(by_cat.keys())
    kb = ui.category_kb(cats, "month") if cats else ui.back_kb()
    await q.message.reply_photo(
        photo=io.BytesIO(png),
        caption=f"📉 <b>Spending this month · {space}</b> — tap a category to drill in.",
        parse_mode="HTML", reply_markup=kb,
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route taps from the home menu to the right screen, editing in place."""
    q = update.callback_query
    await q.answer()
    action = q.data.split("|", 1)[1]
    _, fp = _get_orchestrator()
    uid = str(q.from_user.id)

    if action == "home":
        await q.edit_message_text(ui.welcome("", fp.db.get_active_space(uid)),
                                  parse_mode="HTML", reply_markup=ui.main_menu_kb())
        return
    if action == "donate":
        text, kb = ui.donate_card_and_kb()
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if action == "reminders":
        text, kb = ui.reminders_card_and_kb(fp.db.get_reminders(uid))
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if action == "spaces":
        active = fp.db.get_active_space(uid)
        await q.edit_message_text(ui.spaces_card(active), parse_mode="HTML",
                                  reply_markup=ui.spaces_kb(fp.db.list_spaces(uid), active))
        return
    if action == "chart":
        await _send_chart(q, fp, uid)
        return
    if action == "wrapped":
        await _send_wrapped(q.message, fp, uid, bot_username=context.bot.username)
        return
    if action == "history":
        text, kb = _history_page(fp, uid, 0)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if action in ("summary", "month"):
        tf = "week" if action == "summary" else "month"
        space = fp.db.get_active_space(uid)
        title = "📊 This Week" if tf == "week" else "🗓 This Month"
        text = ui.card(title, fp.summarize(tf, uid, space=space))
        cats = list(fp.category_breakdown(tf, uid, space=space).keys())
        kb = ui.category_kb(cats, tf) if cats else ui.back_kb()
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if action == "insights":
        text = ui.card("💡 Insights", fp.spending_insights(uid, space=fp.db.get_active_space(uid)))
    elif action == "subs":
        text = ui.card("🔁 Subscriptions", fp.detect_subscriptions(uid, space=fp.db.get_active_space(uid)))
    elif action == "budget":
        text = ui.card("🎯 Budgets", fp._budget_report(uid, space=fp.db.get_active_space(uid)))
    elif action == "income":
        text = ui.card("💰 Income", fp._income_summary(uid, space=fp.db.get_active_space(uid)))
    elif action == "dashboard":
        text = await _dashboard_text(fp, uid)
    elif action == "add":
        text = ui.add_help()
    elif action == "examples":
        text = ui.examples_card()
    elif action == "help":
        text = ui.help_text()
    else:
        text = ui.card("Hmm", "Unknown action.")

    await q.edit_message_text(
        text, parse_mode="HTML", reply_markup=ui.back_kb(), disable_web_page_preview=True
    )


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drill into one category's transactions for the timeframe."""
    q = update.callback_query
    await q.answer()
    _, category, tf = q.data.split("|", 2)
    _, fp = _get_orchestrator()
    uid = str(q.from_user.id)
    txs = fp.category_transactions(category, tf, uid, space=fp.db.get_active_space(uid))
    span = "this week" if tf == "week" else "this month"
    from openclaw.domains.finance.finance_plugin import category_icon
    if not txs:
        body = "No transactions here yet."
    else:
        cur = txs[0].get("currency", "GBP")
        total = sum(r.get("amount", 0) or 0 for r in txs)
        lines = [_tx_line(r) for r in txs]
        lines.append("─────────────")
        lines.append(f"<b>Total · {format_amount(total, cur)}</b> · {len(txs)} item{'s' if len(txs) != 1 else ''}")
        body = "\n".join(lines)
    await q.message.reply_text(ui.card(f"{category_icon(category)} {category} · {span}", body),
                               parse_mode="HTML", reply_markup=ui.back_kb())


async def history_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Paginate the history list in place."""
    q = update.callback_query
    await q.answer()
    offset = int(q.data.split("|", 1)[1])
    _, fp = _get_orchestrator()
    text, kb = _history_page(fp, str(q.from_user.id), offset)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp.summarize("week", user_id=uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("📊 This Week", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp.summarize("month", user_id=uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("🗓 This Month", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp._budget_report(user_id=uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("🎯 Budgets", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def income_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    text = fp._income_summary(user_id=str(update.effective_user.id))
    await update.message.reply_text(ui.card("💰 Income", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    text, kb = _history_page(fp, str(update.effective_user.id), 0)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def dashboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a private, time-limited dashboard link scoped to this user only."""
    _, fp = _get_orchestrator()
    text = await _dashboard_text(fp, str(update.effective_user.id))
    await update.message.reply_text(text, parse_mode="HTML",
                                    reply_markup=ui.back_kb(), disable_web_page_preview=True)


async def lists_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's shopping / price lists."""
    orch, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = orch.shopping._render_all(uid, fp.db.get_active_space(uid))
    await update.message.reply_text(text, reply_markup=ui.back_kb())


async def insights_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp.spending_insights(uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("💡 Insights", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def subscriptions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp.detect_subscriptions(uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("🔁 Subscriptions", text),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def donate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = ui.donate_card_and_kb()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def reminders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    text, kb = ui.reminders_card_and_kb(fp.db.get_reminders(str(update.effective_user.id)))
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def reminders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a reminder opt-in from the inline switcher."""
    q = update.callback_query
    await q.answer()
    kind = q.data.split("|", 1)[1]  # 'digest' | 'briefing'
    _, fp = _get_orchestrator()
    uid = str(q.from_user.id)
    current = fp.db.get_reminders(uid)
    fp.db.set_reminder(uid, kind, not current.get(kind, False))
    text, kb = ui.reminders_card_and_kb(fp.db.get_reminders(uid))
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def digest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Preview today's digest on demand."""
    _, fp = _get_orchestrator()
    await update.message.reply_text(fp.daily_digest(str(update.effective_user.id)),
                                    reply_markup=ui.back_kb())


async def briefing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Preview the morning briefing on demand."""
    _, fp = _get_orchestrator()
    await update.message.reply_text(fp.morning_briefing(str(update.effective_user.id)),
                                    reply_markup=ui.back_kb())


async def _send_reminder(context, kind: str, builder_name: str) -> None:
    """Daily job: send the digest/briefing to every opted-in user."""
    _, fp = _get_orchestrator()
    builder = getattr(fp, builder_name)
    for uid in fp.db.list_reminder_users(kind):
        try:
            await context.bot.send_message(int(uid), builder(uid))
        except Exception:
            logger.warning("Reminder '%s' failed for user %s", kind, uid, exc_info=True)


async def _send_wrapped_recaps(context):
    """Monthly job (1st): push last month's Wrapped poster to opted-in users."""
    _, fp = _get_orchestrator()
    username = context.bot.username
    for uid in fp.db.list_reminder_users("wrapped"):
        try:
            buf, caption, recap = _build_wrapped(fp, uid, bot_username=username, month_offset=-1)
            if recap.get("empty"):
                continue
            await context.bot.send_photo(int(uid), photo=buf, caption=caption, parse_mode="HTML")
        except Exception:
            logger.warning("Wrapped recap failed for user %s", uid, exc_info=True)


async def _send_digests(context):
    await _send_reminder(context, "digest", "daily_digest")


async def _send_briefings(context):
    await _send_reminder(context, "briefing", "morning_briefing")


async def spaces_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Budget Spaces and let the user switch the active one."""
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    active = fp.db.get_active_space(uid)
    await update.message.reply_text(ui.spaces_card(active), parse_mode="HTML",
                                    reply_markup=ui.spaces_kb(fp.db.list_spaces(uid), active))


async def space_set_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/space <name> — create and/or switch to a Budget Space."""
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    name = _normalize_space_name(" ".join(context.args or []))
    if not name:
        await update.message.reply_text("Usage: /space <name>   e.g. /space Side Hustle")
        return
    fp.db.set_active_space(uid, name)
    await update.message.reply_text(f"🗂 Active space set to <b>{name}</b>.", parse_mode="HTML",
                                    reply_markup=ui.back_kb())


async def space_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the active Budget Space from the inline switcher."""
    q = update.callback_query
    await q.answer()
    space = q.data.split("|", 1)[1]
    _, fp = _get_orchestrator()
    uid = str(q.from_user.id)
    fp.db.set_active_space(uid, space)
    await q.edit_message_text(ui.spaces_card(space), parse_mode="HTML",
                              reply_markup=ui.spaces_kb(fp.db.list_spaces(uid), space))


async def setbudget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setbudget <category> <amount> — set a monthly budget."""
    _, fp = _get_orchestrator()
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /setbudget <category> <amount>\n"
            "Example: /setbudget Food & Drink 200"
        )
        return
    try:
        amount = float(args[-1].replace("£", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number, e.g. /setbudget Transport 150")
        return
    category = " ".join(args[:-1]).title()
    uid = str(update.effective_user.id)
    text = fp.set_budget(category, amount, "monthly", user_id=uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(text)


_QUESTION_STARTS = ("how", "what", "why", "when", "where", "which", "who",
                    "can", "could", "should", "do", "does", "is", "are", "if")


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    return t.endswith("?") or t.split()[0] in _QUESTION_STARTS if t else False


_SWITCH_VERBS = ("switch", "change", "go", "move", "use", "set", "open")


def _normalize_space_name(name: str) -> str:
    """Clean a space name: drop punctuation (e.g. a transcribed trailing '.'),
    collapse whitespace, Title-Case. Prevents 'Business .' ≠ 'Business' bugs."""
    import re
    name = re.sub(r"[^\w &'\-]", " ", name)   # strip '.', ',', etc.
    return " ".join(name.split()).strip().title()


def _parse_space_switch(text: str, fp, user_id: str):
    """Detect 'switch to <space>' style commands; return the target space or None."""
    import re
    t = text.strip().lower()
    words = t.split()
    if not words or words[0] not in _SWITCH_VERBS:
        return None
    if "space" not in t and words[0] != "switch":
        return None  # require the word 'space' unless it's an explicit 'switch ...'
    cleaned = re.sub(
        r"\b(switch|change|go|move|use|set|open|to|into|over|my|the|active|current|space|spaces|please)\b",
        " ", t)
    name = _normalize_space_name(cleaned)
    if not name:
        return None
    known = {s.lower(): s for s in fp.db.list_spaces(user_id)}
    return known.get(name.lower(), name)


def _quick_insight(fp, user_id: str, space):
    """A cheap, real-data one-liner for the wait experience (no LLM, never faked)."""
    try:
        by = fp.category_breakdown("month", user_id, space=space)
        if not by:
            return None
        top, amt = max(by.items(), key=lambda x: x[1])
        from openclaw.utils.currency_normalizer import format_amount as _fmt
        return f"💡 Your top category this month is {top} ({_fmt(amt, fp._user_currency(user_id, space))})."
    except Exception:
        return None


def _quick_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 This Week", callback_data="menu|summary"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu|home"),
    ]])


async def _finalise(pm, result, user_id: str, prefix: str = "") -> None:
    """Turn a ProcessingResult into the final edit on the progress message."""
    if getattr(result, "pending", None):
        payload = {**result.pending, "user_id": user_id}
        token = _sessions.put(payload)
        if payload.get("action") in ("VOID_ALL", "CLEAR_BUDGETS"):
            label = ("void all" if payload.get("action") == "VOID_ALL" else "delete all budgets")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Yes, {label} ({payload.get('count', '')})", callback_data=f"corr|{token}|confirm")],
                [InlineKeyboardButton("✖️ Cancel", callback_data=f"corr|{token}|cancel")],
            ])
        elif payload.get("action") == "AMOUNT_CONFIRM":
            rows = [[InlineKeyboardButton(format_amount(c["amount"], c["currency"]),
                                          callback_data=f"corr|{token}|{i}")]
                    for i, c in enumerate(payload["candidates"])]
            rows.append([InlineKeyboardButton("✖️ Neither / cancel", callback_data=f"corr|{token}|cancel")])
            kb = InlineKeyboardMarkup(rows)
        else:
            rows = []
            for i, c in enumerate(payload["candidates"]):
                amt = format_amount(c["amount"] or 0, c.get("currency", "GBP"))
                rows.append([InlineKeyboardButton(f"{c['description'][:40]} ({amt})", callback_data=f"corr|{token}|{i}")])
            rows.append([InlineKeyboardButton("✖️ Cancel", callback_data=f"corr|{token}|cancel")])
            kb = InlineKeyboardMarkup(rows)
        await pm.finish(result.response, reply_markup=kb)
        return

    if result.success:
        await pm.finish(prefix + result.response, reply_markup=_quick_keyboard())
    else:
        # Soft replies (nudges, "which budget?", confirmations) already carry their
        # own emoji/tone — don't slap a scary ⚠️ on them. Bare/empty → default fail.
        await pm.fail(result.response or None)


async def _process_user_text(update, context, text: str, kind: str = "text",
                             heard: str = "", pm: "ProgressManager" = None) -> None:
    """Shared pipeline for text (typed or transcribed) with a perceived-performance layer.

    Fast paths (space switch, questions) reply immediately. The record path runs
    the blocking orchestrator in a worker thread while a ProgressManager keeps the
    UI alive (ack → typing → staged edits → insight → final)."""
    user_id = str(update.effective_user.id)
    orch, fp = _get_orchestrator()
    chat_id = update.effective_chat.id

    # Fast path 1 — natural-language space switch (no heavy processing).
    target = _parse_space_switch(text, fp, user_id)
    if target:
        fp.db.set_active_space(user_id, target)
        txt = ui.card("🗂 Space switched", f"Active space is now <b>{target}</b>.\nNew entries go here.")
        kb = ui.spaces_kb(fp.db.list_spaces(user_id), target)
        if pm:  # reuse the progress message rather than leaving it dangling
            await pm.finish(txt, reply_markup=kb, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id, txt, parse_mode="HTML", reply_markup=kb)
        return

    # Fast path 2 — questions (Financial Memory). Run in a thread (may hit the LLM).
    if _looks_like_question(text):
        await context.bot.send_chat_action(chat_id, _PM_TYPING)
        answer = await asyncio.to_thread(orch.answer, text, user_id, fp.db.get_active_space(user_id))
        txt = ui.card("💬 Answer", answer)
        if pm:
            await pm.finish(txt, reply_markup=ui.back_kb(), parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id, txt, parse_mode="HTML", reply_markup=ui.back_kb())
        return

    # Record path — acknowledge first, then process off the event loop.
    space = fp.db.get_active_space(user_id)
    if pm is None:
        pm = ProgressManager(context.bot, chat_id, kind=kind,
                             insight_provider=lambda: _quick_insight(fp, user_id, space))
        await pm.start()
    try:
        # Bare amounts follow the user's home currency, not a hardcoded £.
        result = await asyncio.to_thread(orch.process, text, user_id, fp.default_currency(user_id, space))
    except Exception:
        logger.exception("processing failed")
        await pm.fail()
        return
    await _finalise(pm, result, user_id, prefix=heard)


async def correction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve an interactive correction menu when the user taps a button."""
    query = update.callback_query
    await query.answer()
    try:
        _, token, choice = query.data.split("|", 2)
    except ValueError:
        return

    payload = _sessions.pop(token)
    if payload is None:
        await query.edit_message_text("⌛ That menu expired — please send the correction again.")
        return
    if choice == "cancel":
        await query.edit_message_text("✖️ Correction cancelled.")
        return
    if choice == "confirm" and payload.get("action") == "VOID_ALL":
        orch, _ = _get_orchestrator()
        result = orch.apply_void_all(payload["user_id"], space=payload.get("space"))
        await query.edit_message_text(result.response)
        return
    if choice == "confirm" and payload.get("action") == "CLEAR_BUDGETS":
        orch, _ = _get_orchestrator()
        result = orch.apply_clear_budgets(payload["user_id"], space=payload.get("space"))
        await query.edit_message_text(result.response)
        return
    if payload.get("action") == "AMOUNT_CONFIRM":
        orch, _ = _get_orchestrator()
        result = orch.record_amount_choice(payload, int(choice), payload["user_id"])
        await query.edit_message_text(result.response)
        return

    candidate = payload["candidates"][int(choice)]
    orch, _ = _get_orchestrator()
    result = orch.apply_correction(
        record_id=candidate["id"],
        action=payload["action"],
        updates=payload.get("updates"),
        user_id=payload["user_id"],
    )
    await query.edit_message_text(result.response)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages — route through orchestrator with progress UI."""
    await _process_user_text(update, context, update.message.text, kind="text")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse a photo (receipt/invoice/payslip/screenshot) into a transaction."""
    import base64

    photo = update.message.photo[-1] if update.message.photo else None  # largest size
    doc = update.message.document
    file_id = photo.file_id if photo else (doc.file_id if doc else None)
    if file_id is None:
        return

    user_id = str(update.effective_user.id)
    orch, fp = _get_orchestrator()
    space = fp.db.get_active_space(user_id)
    pm = ProgressManager(context.bot, update.effective_chat.id, kind="receipt",
                         insight_provider=lambda: _quick_insight(fp, user_id, space))
    await pm.start()
    try:
        tg_file = await context.bot.get_file(file_id)
        image = bytes(await tg_file.download_as_bytearray())
        image_b64 = base64.b64encode(image).decode()
        result = await asyncio.to_thread(orch.process_document, image_b64, "image/jpeg", user_id)
    except Exception:
        logger.exception("document processing failed")
        await pm.fail("⚠️ I couldn't read that document. Try a clearer photo?")
        return
    await _finalise(pm, result, user_id)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice/audio note (with progress), then route the text."""
    media = update.message.voice or update.message.audio
    if media is None:
        return

    user_id = str(update.effective_user.id)
    orch, fp = _get_orchestrator()
    space = fp.db.get_active_space(user_id)
    pm = ProgressManager(context.bot, update.effective_chat.id, kind="voice",
                         insight_provider=lambda: _quick_insight(fp, user_id, space))
    await pm.start()
    try:
        tg_file = await context.bot.get_file(media.file_id)
        audio = bytes(await tg_file.download_as_bytearray())
        text = await asyncio.to_thread(_get_transcriber().transcribe, audio, ".ogg")
    except Exception:
        logger.exception("Transcription failed")
        await pm.fail("⚠️ Couldn't transcribe that. Try again?")
        return

    if not text:
        await pm.fail("🤔 I couldn't make out any words — try again?")
        return

    # Continue with the same progress message; prepend what was heard to the result.
    await _process_user_text(update, context, text, kind="voice",
                             heard=f'🗣️ Heard: "{text}"\n\n', pm=pm)


# -------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------

def main():
    import argparse

    global _USE_MOCK

    parser = argparse.ArgumentParser(description="OpenClaw Telegram bot")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Offline mode: heuristic LLM, no Anthropic API key or cost",
    )
    args = parser.parse_args()
    _USE_MOCK = args.mock or os.environ.get("OPENCLAW_MOCK") == "1"

    if not _TELEGRAM_AVAILABLE:
        print("python-telegram-bot not installed. Run: pip install python-telegram-bot")
        sys.exit(1)

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("Set TELEGRAM_TOKEN environment variable.")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    if _USE_MOCK:
        logger.info("Running in MOCK mode — no Anthropic API calls.")

    async def _post_init(application):
        # Populate the Telegram "/" command menu beside the input box.
        await application.bot.set_my_commands(ui.bot_commands())

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("examples", examples_handler))
    app.add_handler(CommandHandler("wrapped", wrapped_handler))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("month", month_handler))
    app.add_handler(CommandHandler("budget", budget_handler))
    app.add_handler(CommandHandler("income", income_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("setbudget", setbudget_handler))
    app.add_handler(CommandHandler("dashboard", dashboard_handler))
    app.add_handler(CommandHandler("spaces", spaces_handler))
    app.add_handler(CommandHandler("space", space_set_handler))
    app.add_handler(CommandHandler("insights", insights_handler))
    app.add_handler(CommandHandler("lists", lists_handler))
    app.add_handler(CommandHandler("subscriptions", subscriptions_handler))
    app.add_handler(CommandHandler("donate", donate_handler))
    app.add_handler(CommandHandler("reminders", reminders_handler))
    app.add_handler(CommandHandler("digest", digest_handler))
    app.add_handler(CommandHandler("briefing", briefing_handler))
    app.add_handler(CallbackQueryHandler(tutorial_callback, pattern=r"^tut\|"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu\|"))
    app.add_handler(CallbackQueryHandler(space_callback, pattern=r"^space\|"))
    app.add_handler(CallbackQueryHandler(reminders_callback, pattern=r"^rem\|"))
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat\|"))
    app.add_handler(CallbackQueryHandler(history_page_callback, pattern=r"^hist\|"))
    app.add_handler(CallbackQueryHandler(correction_callback, pattern=r"^corr\|"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Daily reminders (opt-in per user). Times are server-local (UTC on the VM).
    if app.job_queue is not None:
        from datetime import time as _dtime
        digest_h = int(os.environ.get("DIGEST_HOUR", "20"))
        briefing_h = int(os.environ.get("BRIEFING_HOUR", "7"))
        app.job_queue.run_daily(_send_digests, time=_dtime(hour=digest_h, minute=0))
        app.job_queue.run_daily(_send_briefings, time=_dtime(hour=briefing_h, minute=0))
        # Monthly "Wrapped" recap, 1st of the month (covers the previous month).
        wrapped_h = int(os.environ.get("WRAPPED_HOUR", "9"))
        app.job_queue.run_monthly(_send_wrapped_recaps, when=_dtime(hour=wrapped_h, minute=0), day=1)
        logger.info("Scheduled daily digest @%02d:00, briefing @%02d:00, monthly Wrapped @%02d:00 day 1 (server time)",
                    digest_h, briefing_h, wrapped_h)
    else:
        logger.warning("JobQueue unavailable — install python-telegram-bot[job-queue] to enable reminders.")

    logger.info("OpenClaw Telegram bot starting…")
    app.run_polling()


if __name__ == "__main__":
    main()
