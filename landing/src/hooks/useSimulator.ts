import { useCallback, useRef, useState } from "react";
import { BotReply, DEMO_BUDGETS, classify, respond } from "../lib/simulator";

export type ChatMessage =
  | { id: string; from: "user"; text: string }
  | { id: string; from: "bot"; reply: BotReply };

let counter = 0;
const nextId = () => `m${++counter}`;

const SEED: ChatMessage[] = [
  {
    id: nextId(),
    from: "bot",
    reply: { kind: "text", text: "👋 Hi! Tell me what you spent, or ask me a question. Try the chips below." },
  },
];

export function useSimulator() {
  const [messages, setMessages] = useState<ChatMessage[]>(SEED);
  const [isTyping, setIsTyping] = useState(false);
  // Running demo budget per category so "budget remaining" feels live.
  const spent = useRef<Record<string, number>>({});
  const timers = useRef<number[]>([]);

  const send = useCallback((raw: string) => {
    const text = raw.trim();
    if (!text) return;

    setMessages((m) => [...m, { id: nextId(), from: "user", text }]);
    setIsTyping(true);

    const parsed = classify(text);
    let budgetRemaining: number | null = null;
    if (parsed.type === "record") {
      const cap = DEMO_BUDGETS[parsed.category];
      if (cap != null) {
        const used = (spent.current[parsed.category] ?? 0) + parsed.amount;
        spent.current[parsed.category] = used;
        budgetRemaining = Math.max(0, Math.round((cap - used) * 100) / 100);
      }
    }

    const t = window.setTimeout(() => {
      setIsTyping(false);
      setMessages((m) => [...m, { id: nextId(), from: "bot", reply: respond(text, budgetRemaining) }]);
    }, 1100);
    timers.current.push(t);
  }, []);

  const reset = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    spent.current = {};
    counter = 0;
    setIsTyping(false);
    setMessages([
      {
        id: nextId(),
        from: "bot",
        reply: { kind: "text", text: "👋 Hi! Tell me what you spent, or ask me a question." },
      },
    ]);
  }, []);

  return { messages, isTyping, send, reset };
}
