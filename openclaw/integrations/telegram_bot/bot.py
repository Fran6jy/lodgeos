"""
OpenClaw Telegram Bot — skeleton for Phase 2.

Install: pip install python-telegram-bot
Run:     TELEGRAM_TOKEN=<token> ANTHROPIC_API_KEY=<key> python -m openclaw.integrations.telegram_bot.bot

All messages route through the same AgentOrchestrator as the CLI.
Each Telegram user_id gets their own ledger partition via user_id.
"""

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
    from openclaw.domains.finance.finance_plugin import FinancePlugin
    from openclaw.storage.sqlite_adapter import SQLiteAdapter

    from openclaw.llm.factory import build_llm_client, build_vision_client

    db = SQLiteAdapter(os.environ.get("OPENCLAW_DB", "openclaw.db"))
    finance = FinancePlugin(db)
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)

    # Chains Anthropic → OpenRouter automatically; mock bypasses both.
    llm = build_llm_client(use_mock=use_mock)
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
    await update.message.reply_text(
        ui.welcome(name), parse_mode="HTML", reply_markup=ui.main_menu_kb()
    )


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        ui.welcome(), parse_mode="HTML", reply_markup=ui.main_menu_kb()
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ui.help_text(), parse_mode="HTML", reply_markup=ui.back_kb())


def _history_page(fp, user_id: str, offset: int = 0, n: int = 10):
    """Return (card_text, keyboard) for one page of history."""
    rows = fp.db.query_records(domain="finance", user_id=user_id, limit=offset + n + 1)
    page = rows[offset:offset + n]
    has_more = len(rows) > offset + n
    if not page:
        return ui.card("🧾 History", "No more records." if offset else
                       "No records yet — send me an expense to start."), ui.history_kb(offset, False)
    lines = []
    for r in page:
        ts = (r.get("timestamp", "") or "")[:10]
        amt = format_amount(r.get("amount") or 0, r.get("currency", "GBP"))
        sign = "＋" if r.get("type") == "income" else "－"
        lines.append(f"{ts}  {sign}{amt:>10}  {r.get('description','')[:24]}")
    title = f"🧾 History  ·  {offset + 1}–{offset + len(page)}"
    return ui.card(title, "\n".join(lines), mono=True), ui.history_kb(offset, has_more)


async def _dashboard_text(fp, user_id: str) -> str:
    ttl = int(os.environ.get("DASHBOARD_TTL", "3600"))
    token = fp.db.create_dashboard_token(user_id, ttl_seconds=ttl)
    base = os.environ.get("DASHBOARD_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return ui.card("📈 Your private dashboard", (
        f"<a href=\"{base}/d/{token}\">Open dashboard →</a>\n\n"
        f"Valid {ttl // 60} min · shows only your data.\n"
        f"🔒 Don’t share this link."
    ))


async def _send_chart(q, fp, uid: str) -> None:
    """Render a spending donut and send it as a photo with category drill-down chips."""
    import io
    from openclaw.integrations.telegram_bot import charts
    space = fp.db.get_active_space(uid)
    by_cat = fp.category_breakdown("month", uid, space=space)
    png = charts.category_donut(by_cat, f"This month · {space}")
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
        await q.edit_message_text(ui.welcome(), parse_mode="HTML", reply_markup=ui.main_menu_kb())
        return
    if action == "spaces":
        active = fp.db.get_active_space(uid)
        await q.edit_message_text(ui.spaces_card(active), parse_mode="HTML",
                                  reply_markup=ui.spaces_kb(fp.db.list_spaces(uid), active))
        return
    if action == "chart":
        await _send_chart(q, fp, uid)
        return
    if action == "history":
        text, kb = _history_page(fp, uid, 0)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if action in ("summary", "month"):
        tf = "week" if action == "summary" else "month"
        space = fp.db.get_active_space(uid)
        title = "📊 This Week" if tf == "week" else "🗓 This Month"
        text = ui.card(title, fp.summarize(tf, uid, space=space), mono=True)
        cats = list(fp.category_breakdown(tf, uid, space=space).keys())
        kb = ui.category_kb(cats, tf) if cats else ui.back_kb()
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if action == "budget":
        text = ui.card("🎯 Budgets", fp._budget_report(uid, space=fp.db.get_active_space(uid)), mono=True)
    elif action == "income":
        text = ui.card("💰 Income", fp._income_summary(uid, space=fp.db.get_active_space(uid)), mono=True)
    elif action == "dashboard":
        text = await _dashboard_text(fp, uid)
    elif action == "add":
        text = ui.add_help()
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
    if not txs:
        body = "No transactions here."
    else:
        total = sum(r.get("amount", 0) or 0 for r in txs)
        lines = [f"{(r.get('timestamp','') or '')[:10]}  "
                 f"{format_amount(r.get('amount') or 0, r.get('currency','GBP')):>9}  "
                 f"{r.get('description','')[:24]}" for r in txs]
        lines.append("─" * 30)
        lines.append(f"{'Total':<20}{format_amount(total):>9}")
        body = "\n".join(lines)
    span = "this week" if tf == "week" else "this month"
    await q.message.reply_text(ui.card(f"{category} · {span}", body, mono=True),
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
    text = fp.summarize("week", user_id=str(update.effective_user.id))
    await update.message.reply_text(ui.card("📊 This Week", text, mono=True),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    text = fp.summarize("month", user_id=str(update.effective_user.id))
    await update.message.reply_text(ui.card("🗓 This Month", text, mono=True),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    uid = str(update.effective_user.id)
    text = fp._budget_report(user_id=uid, space=fp.db.get_active_space(uid))
    await update.message.reply_text(ui.card("🎯 Budgets", text, mono=True),
                                    parse_mode="HTML", reply_markup=ui.back_kb())


async def income_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, fp = _get_orchestrator()
    text = fp._income_summary(user_id=str(update.effective_user.id))
    await update.message.reply_text(ui.card("💰 Income", text, mono=True),
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
    name = " ".join(context.args or []).strip().title()
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


async def _handle_text(update: Update, text: str) -> None:
    """Shared pipeline for text (typed or transcribed): guard, process, reply."""
    user_id = str(update.effective_user.id)

    # Don't record questions as transactions — answer or guide instead.
    if _looks_like_question(text):
        await update.message.reply_text(
            "That looks like a question — I record transactions, I don't answer queries yet.\n"
            "Try: /summary, /budget, or /income for your numbers."
        )
        return

    await update.message.reply_text("Processing…")
    orch, _ = _get_orchestrator()
    result = orch.process(text, user_id=user_id)

    # Ambiguous correction → present single-tap buttons instead of asking to retype.
    if getattr(result, "pending", None):
        payload = {**result.pending, "user_id": user_id}
        token = _sessions.put(payload)
        keyboard = []
        for i, c in enumerate(payload["candidates"]):
            amt = format_amount(c["amount"] or 0, c.get("currency", "GBP"))
            label = f"{c['description'][:40]} ({amt})"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"corr|{token}|{i}")])
        keyboard.append([InlineKeyboardButton("✖️ Cancel", callback_data=f"corr|{token}|cancel")])
        await update.message.reply_text(result.response, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if result.success:
        quick = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 This Week", callback_data="menu|summary"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu|home"),
        ]])
        await update.message.reply_text(result.response, reply_markup=quick)
    else:
        await update.message.reply_text(f"❌ {result.response}")


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
    """Handle free-text messages — route through orchestrator."""
    await _handle_text(update, update.message.text)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse a photo (receipt/invoice/payslip/screenshot) into a transaction."""
    import base64

    photo = update.message.photo[-1] if update.message.photo else None  # largest size
    doc = update.message.document
    file_id = photo.file_id if photo else (doc.file_id if doc else None)
    if file_id is None:
        return

    await update.message.reply_text("🧾 Reading document…")
    try:
        tg_file = await context.bot.get_file(file_id)
        image = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"❌ Couldn't fetch that image: {e}")
        return

    image_b64 = base64.b64encode(image).decode()
    orch, _ = _get_orchestrator()
    result = orch.process_document(image_b64, mime="image/jpeg", user_id=str(update.effective_user.id))
    await update.message.reply_text(result.response if result.success else f"❌ {result.response}")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice/audio note, then route the text through the pipeline."""
    media = update.message.voice or update.message.audio
    if media is None:
        return

    await update.message.reply_text("🎙️ Transcribing…")
    try:
        tg_file = await context.bot.get_file(media.file_id)
        audio = bytes(await tg_file.download_as_bytearray())
        text = _get_transcriber().transcribe(audio, suffix=".ogg")
    except Exception as e:
        logger.exception("Transcription failed")
        await update.message.reply_text(f"❌ Couldn't transcribe that: {e}")
        return

    if not text:
        await update.message.reply_text("🤔 I couldn't make out any words — try again?")
        return

    await update.message.reply_text(f'🗣️ Heard: "{text}"')
    await _handle_text(update, text)


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
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("month", month_handler))
    app.add_handler(CommandHandler("budget", budget_handler))
    app.add_handler(CommandHandler("income", income_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("setbudget", setbudget_handler))
    app.add_handler(CommandHandler("dashboard", dashboard_handler))
    app.add_handler(CommandHandler("spaces", spaces_handler))
    app.add_handler(CommandHandler("space", space_set_handler))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu\|"))
    app.add_handler(CallbackQueryHandler(space_callback, pattern=r"^space\|"))
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat\|"))
    app.add_handler(CallbackQueryHandler(history_page_callback, pattern=r"^hist\|"))
    app.add_handler(CallbackQueryHandler(correction_callback, pattern=r"^corr\|"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("OpenClaw Telegram bot starting…")
    app.run_polling()


if __name__ == "__main__":
    main()
