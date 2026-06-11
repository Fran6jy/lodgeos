"""Unit tests for the ProgressManager (perceived-performance layer)."""

import asyncio
from types import SimpleNamespace

from openclaw.integrations.telegram_bot.progress_manager import ProgressManager


class FakeBot:
    """Records Telegram API calls so we can assert on the user experience."""

    def __init__(self):
        self.sent = []        # [(text, kwargs)]
        self.edits = []       # [text]
        self.actions = []     # [action]
        self._id = 1000

    async def send_message(self, chat_id, text, **kw):
        self._id += 1
        self.sent.append((text, kw))
        return SimpleNamespace(message_id=self._id)

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append(text)

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)


def _run(coro):
    return asyncio.run(coro)


def test_ack_sent_then_final_edit():
    bot = FakeBot()

    async def go():
        pm = ProgressManager(bot, 1, kind="text")
        await pm.start()
        await pm.finish("✅ Recorded expense: coffee £3")

    _run(go())
    # Acknowledgement was sent first (before any processing).
    assert bot.sent and "Received" in bot.sent[0][0]
    # The same message was edited into the final response.
    assert bot.edits[-1] == "✅ Recorded expense: coffee £3"


def test_failure_shows_friendly_error():
    bot = FakeBot()

    async def go():
        pm = ProgressManager(bot, 1, kind="text")
        await pm.start()
        await pm.fail()

    _run(go())
    assert "couldn't process" in bot.edits[-1].lower()
    # Never leaves the user on a 'processing…' state.
    assert "processing" not in bot.edits[-1].lower()


def test_progress_advances_and_types():
    bot = FakeBot()

    async def go():
        pm = ProgressManager(bot, 1, kind="text")
        pm.TICK = 0.01          # speed up for the test
        await pm.start()
        await asyncio.sleep(0.1)  # let a few ticks run
        await pm.finish("done")

    _run(go())
    # Typing indicator fired, and stages advanced past stage 1.
    assert bot.actions, "expected a typing indicator"
    assert any("Categorising" in e for e in bot.edits), "stages should advance"
    assert bot.edits[-1] == "done"


def test_insight_shown_only_after_threshold_and_only_if_real():
    bot = FakeBot()

    async def go():
        pm = ProgressManager(bot, 1, kind="text", insight_provider=lambda: "💡 Top category: Coffee")
        pm.TICK = 0.01
        pm.INSIGHT_AFTER = 0.03
        await pm.start()
        await asyncio.sleep(0.2)
        await pm.finish("done")

    _run(go())
    assert any("💡 Top category: Coffee" in e for e in bot.edits)


def test_insight_skipped_when_none():
    bot = FakeBot()

    async def go():
        pm = ProgressManager(bot, 1, kind="text", insight_provider=lambda: None)
        pm.TICK = 0.01
        pm.INSIGHT_AFTER = 0.02
        await pm.start()
        await asyncio.sleep(0.1)
        await pm.finish("done")

    _run(go())
    # No fabricated insight ever appears.
    assert not any("💡" in e for e in bot.edits)


def test_receipt_and_voice_have_their_own_stages():
    assert ProgressManager.STAGES["receipt"][0].startswith("📸")
    assert ProgressManager.STAGES["voice"][0].startswith("🎤")
    assert ProgressManager.ACK["receipt"].startswith("📸")
