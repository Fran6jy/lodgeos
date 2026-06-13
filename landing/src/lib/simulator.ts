// A tiny, deterministic NL engine that powers the interactive Telegram demo.
// It mirrors how the real LodgeOS bot behaves: parse → classify → respond.

export type RecordedCard = {
  merchant: string;
  category: string;
  amount: number;
  currency: string;
  budgetRemaining: number | null;
  space?: string;
};

export type InsightCard = {
  emoji: string;
  headline: string;
  detail?: string;
  sub?: string;
};

export type BotReply =
  | { kind: "recorded"; card: RecordedCard }
  | { kind: "insight"; card: InsightCard }
  | { kind: "text"; text: string };

const CATEGORY_KEYWORDS: Record<string, string[]> = {
  "Food & Drink": ["coffee", "nero", "costa", "starbucks", "lunch", "dinner", "restaurant", "pub", "pizza", "snack"],
  Groceries: ["tesco", "sainsbury", "asda", "lidl", "aldi", "groceries", "supermarket"],
  Transport: ["uber", "fuel", "petrol", "train", "bus", "taxi", "parking"],
  Shopping: ["amazon", "clothes", "shoes", "jacket"],
  Utilities: ["electric", "water", "internet", "phone", "bill"],
  Rent: ["rent", "deposit", "tenant", "landlord"],
  Income: ["invoice", "salary", "received", "paid me", "client"],
};

const CURRENCY_SYMBOL: Record<string, string> = { "£": "GBP", $: "USD", "€": "EUR", "₦": "NGN" };

function categorise(text: string): string {
  const t = text.toLowerCase();
  for (const [cat, words] of Object.entries(CATEGORY_KEYWORDS)) {
    if (words.some((w) => t.includes(w))) return cat;
  }
  return "Other";
}

export function symbolFor(code: string): string {
  const entry = Object.entries(CURRENCY_SYMBOL).find(([, c]) => c === code);
  return entry ? entry[0] : code + " ";
}

export function formatMoney(amount: number, currency = "GBP"): string {
  const sign = amount < 0 ? "-" : "";
  return `${sign}${symbolFor(currency)}${Math.abs(amount).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// Demo budgets per category — the simulator decrements these as you spend.
export const DEMO_BUDGETS: Record<string, number> = {
  "Food & Drink": 50,
  Groceries: 200,
  Transport: 120,
  Shopping: 100,
};

type ParsedRecord = {
  type: "record";
  amount: number;
  currency: string;
  merchant: string;
  category: string;
};

type Parsed =
  | ParsedRecord
  | { type: "query"; topic: "coffee" | "tesco" | "fuel" | "month" | "renovation" }
  | { type: "unknown"; text: string };

export function classify(input: string): Parsed {
  const text = input.trim();
  const lower = text.toLowerCase();

  // Questions (Financial Memory)
  if (/(how much|what did|show|spent on|spend on|spent at)/.test(lower)) {
    if (/coffee/.test(lower)) return { type: "query", topic: "coffee" };
    if (/tesco/.test(lower)) return { type: "query", topic: "tesco" };
    if (/fuel|petrol/.test(lower)) return { type: "query", topic: "fuel" };
    if (/kitchen|renovation/.test(lower)) return { type: "query", topic: "renovation" };
    return { type: "query", topic: "month" };
  }

  // Records: "Spent £4.50 at Nero for coffee"
  const money = text.match(/([£$€₦])\s*(\d+(?:[.,]\d+)?)/);
  if (money && /(spent|paid|bought|received|got)/.test(lower)) {
    const currency = CURRENCY_SYMBOL[money[1]] ?? "GBP";
    const amount = parseFloat(money[2].replace(",", ""));
    const at = text.match(/\b(?:at|from)\s+([A-Z][\w'&]+(?:\s[A-Z][\w'&]+)?)/);
    const onFor = text.match(/\b(?:on|for)\s+([a-zA-Z][\w &]+?)(?:\.|$)/);
    const merchant = at?.[1] ?? (onFor?.[1] ? capitalise(onFor[1].trim()) : "—");
    return { type: "record", amount, currency, merchant, category: categorise(text) };
  }

  return { type: "unknown", text };
}

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const QUERY_REPLIES: Record<string, InsightCard> = {
  coffee: { emoji: "☕", headline: "£32.40", detail: "9 coffee purchases this month", sub: "12% less than last month" },
  tesco: { emoji: "🛒", headline: "£1,284", detail: "across 47 purchases this year", sub: "Your #2 spending category" },
  fuel: { emoji: "⛽", headline: "£163.40", detail: "on fuel last month", sub: "Down £21 from the month before" },
  renovation: {
    emoji: "🔧",
    headline: "Kitchen renovation",
    detail: "£4,210 across 14 records",
    sub: "Wickes · Howdens · plumber · tiler",
  },
  month: { emoji: "📊", headline: "£612.80", detail: "spent this month", sub: "Groceries is your top category" },
};

export function respond(input: string, budgetRemaining: number | null): BotReply {
  const parsed = classify(input);
  if (parsed.type === "record") {
    return {
      kind: "recorded",
      card: {
        merchant: parsed.merchant,
        category: parsed.category,
        amount: parsed.amount,
        currency: parsed.currency,
        budgetRemaining,
      },
    };
  }
  if (parsed.type === "query") {
    return { kind: "insight", card: QUERY_REPLIES[parsed.topic] };
  }
  return {
    kind: "text",
    text: "Try: “Spent £4.50 at Nero for coffee” — or ask “How much have I spent on coffee this month?”",
  };
}
