"""
Perceived-performance layer for the Telegram bot.

The orchestrator is synchronous and can take 10–20s on a slow LLM tier. To make
the bot *feel* responsive without touching that logic, this manager:

  • sends an acknowledgement within ~one API round-trip (before processing),
  • shows a TYPING action and edits the same message through staged updates,
  • surfaces a real-data insight if the wait exceeds a threshold,
  • finalises (or fails) by editing that one message — no message spam.

It is presentation-only. The orchestrator remains the source of truth; callers
run it in a worker thread and hand the result to finish()/fail().
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

try:
    from telegram.constants import ChatAction
    _TYPING = ChatAction.TYPING
except Exception:  # pragma: no cover - telegram always present in prod
    _TYPING = "typing"


class ProgressManager:
    ACK = {
        "text": "📝 Received. Recording your entry…",
        "receipt": "📸 Receipt received. Extracting details…",
        "voice": "🎤 Voice note received. Transcribing…",
    }
    STAGES = {
        "text": ["📝 Reading transaction…", "🧠 Categorising…",
                 "📊 Updating budgets…", "💾 Saving to your ledger…"],
        "receipt": ["📸 Reading receipt…", "🧾 Extracting merchant…",
                    "🧠 Categorising purchase…", "💾 Saving record…"],
        "voice": ["🎤 Transcribing…", "🧠 Understanding transaction…",
                  "📊 Updating records…", "💾 Saving…"],
    }
    DEFAULT_FAIL = ("⚠️ I couldn't process that record.\n"
                    "Please try again or rephrase the message.")

    TICK = 1.8            # seconds between stage edits / typing pings
    INSIGHT_AFTER = 5.0   # show an insight once the wait passes this

    def __init__(self, bot, chat_id, kind="text", insight_provider=None):
        self.bot = bot
        self.chat_id = chat_id
        self.kind = kind if kind in self.ACK else "text"
        self.insight_provider = insight_provider  # callable() -> str|None (cheap, real data)
        self._msg = None
        self._task = None
        self._stop = asyncio.Event()

    # -- lifecycle -----------------------------------------------------------

    async def start(self):
        """Send the acknowledgement and begin the background progress loop."""
        self._msg = await self.bot.send_message(self.chat_id, self.ACK[self.kind])
        self._task = asyncio.create_task(self._loop())
        return self._msg

    async def finish(self, text, reply_markup=None, parse_mode=None):
        """Stop progress and edit the ack message into the final response."""
        await self._close()
        await self._edit(text, reply_markup=reply_markup, parse_mode=parse_mode, fallback_send=True)

    async def fail(self, text=None):
        """Stop progress and show a friendly error — never a stuck 'processing…'."""
        await self._close()
        await self._edit(text or self.DEFAULT_FAIL, fallback_send=True)

    # -- internals -----------------------------------------------------------

    async def _close(self):
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass

    async def _edit(self, text, reply_markup=None, parse_mode=None, fallback_send=False):
        if self._msg is None:
            return
        try:
            await self.bot.edit_message_text(
                text, chat_id=self.chat_id, message_id=self._msg.message_id,
                reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            # "message is not modified" and edit races are expected; only fall
            # back to a fresh message for the final/ error states.
            if fallback_send:
                try:
                    await self.bot.send_message(self.chat_id, text, reply_markup=reply_markup,
                                                parse_mode=parse_mode)
                except Exception:
                    logger.debug("progress fallback send failed: %s", e)

    async def _typing(self):
        try:
            await self.bot.send_chat_action(self.chat_id, _TYPING)
        except Exception:
            pass

    async def _loop(self):
        stages = self.STAGES[self.kind]
        start = time.monotonic()
        i = 0
        insight_shown = False
        await self._typing()
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.TICK)
                    break  # finished/failed during the wait
                except asyncio.TimeoutError:
                    pass
                await self._typing()  # keep the "typing…" indicator alive
                if i < len(stages):
                    await self._edit(stages[i])
                    i += 1
                elif (not insight_shown and self.insight_provider
                      and (time.monotonic() - start) >= self.INSIGHT_AFTER):
                    insight = None
                    try:
                        insight = self.insight_provider()
                    except Exception:
                        insight = None
                    if insight:
                        await self._edit(f"{stages[-1]}\n\n{insight}")
                    insight_shown = True  # real data only; skip if none
        except asyncio.CancelledError:  # pragma: no cover
            pass
