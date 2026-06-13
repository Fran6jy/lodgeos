import { AnimatePresence, motion } from "framer-motion";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ChatMessage, useSimulator } from "../hooks/useSimulator";
import { BotReply, formatMoney } from "../lib/simulator";

const SUGGESTIONS = [
  "Spent £4.50 at Nero for coffee",
  "How much have I spent on coffee this month?",
  "Bought groceries at Tesco £62",
  "Received £500 invoice payment",
];

function BotBubble({ reply }: { reply: BotReply }) {
  if (reply.kind === "recorded") {
    const c = reply.card;
    return (
      <div className="space-y-1.5 text-[13px] leading-snug">
        <div className="font-semibold text-emerald-400">✅ Recorded</div>
        <Row label="Merchant" value={c.merchant} />
        <Row label="Category" value={c.category} />
        <Row label="Amount" value={formatMoney(c.amount, c.currency)} />
        {c.budgetRemaining != null && (
          <Row label="Budget left" value={formatMoney(c.budgetRemaining, c.currency)} highlight />
        )}
      </div>
    );
  }
  if (reply.kind === "insight") {
    const c = reply.card;
    return (
      <div className="text-[13px] leading-snug">
        <div className="text-2xl font-bold text-white">
          {c.emoji} {c.headline}
        </div>
        {c.detail && <div className="mt-0.5 text-slate-300">{c.detail}</div>}
        {c.sub && <div className="mt-0.5 text-emerald-400">{c.sub}</div>}
      </div>
    );
  }
  return <div className="text-[13px] leading-snug text-slate-300">{reply.text}</div>;
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-slate-400">{label}</span>
      <span className={highlight ? "font-semibold text-emerald-400" : "text-slate-200"}>{value}</span>
    </div>
  );
}

function Bubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.from === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 shadow-sm ${
          isUser
            ? "rounded-br-md bg-emerald-500 text-white"
            : "rounded-bl-md bg-ink-700/80 text-slate-200 ring-1 ring-white/5"
        }`}
      >
        {isUser ? <span className="text-[13px] leading-snug">{msg.text}</span> : <BotBubble reply={msg.reply} />}
      </div>
    </motion.div>
  );
}

export function TelegramSimulator() {
  const { messages, isTyping, send } = useSimulator();
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isTyping]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(value);
    setValue("");
  }

  return (
    <div className="relative mx-auto w-full max-w-sm">
      {/* glow */}
      <div className="absolute -inset-6 -z-10 rounded-[2.5rem] bg-brand-500/20 blur-3xl" aria-hidden />
      <div className="overflow-hidden rounded-[2rem] border border-white/10 bg-ink-900 shadow-card">
        {/* phone header */}
        <div className="flex items-center gap-3 border-b border-white/10 bg-ink-800 px-4 py-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-emerald-600 text-sm font-bold text-white">
            L
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">LodgeOS</div>
            <div className="text-[11px] text-emerald-400">● online</div>
          </div>
          <div className="ml-auto text-slate-500" aria-hidden>
            ⋮
          </div>
        </div>

        {/* messages */}
        <div
          ref={scrollRef}
          className="h-80 space-y-2.5 overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.06),_transparent_60%)] px-3.5 py-4"
          role="log"
          aria-live="polite"
          aria-label="LodgeOS conversation demo"
        >
          {messages.map((m) => (
            <Bubble key={m.id} msg={m} />
          ))}
          <AnimatePresence>
            {isTyping && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex justify-start"
              >
                <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-ink-700/80 px-4 py-3 ring-1 ring-white/5">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* suggestion chips */}
        <div className="flex flex-wrap gap-1.5 border-t border-white/10 bg-ink-800 px-3 pt-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-full border border-white/10 bg-ink-700/60 px-2.5 py-1 text-[11px] text-slate-300 transition hover:border-brand-400/50 hover:text-brand-300"
            >
              {s.length > 26 ? s.slice(0, 24) + "…" : s}
            </button>
          ))}
        </div>

        {/* input */}
        <form onSubmit={onSubmit} className="flex items-center gap-2 bg-ink-800 p-3">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Type a message…"
            aria-label="Type a message to LodgeOS"
            className="flex-1 rounded-full border border-white/10 bg-ink-900 px-4 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-brand-400 focus:outline-none"
          />
          <button
            type="submit"
            aria-label="Send"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-500 text-white transition hover:bg-brand-400 active:scale-95"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
