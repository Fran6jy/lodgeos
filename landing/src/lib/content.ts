// All site copy + structured content lives here so sections stay declarative.

export const LINKS = {
  telegram: "https://t.me/LodgerOS_bot",
  demo: "#hero-demo",
  github: "https://github.com/Fran6jy/lodgeos",
};

export const NAV_ITEMS = [
  { label: "How it works", href: "#how" },
  { label: "Financial memory", href: "#memory" },
  { label: "Features", href: "#features" },
  { label: "For business", href: "#business" },
  { label: "Trust", href: "#trust" },
];

export const COMPARISON = {
  traditional: {
    title: "Traditional finance apps",
    rows: ["Manual entry, field by field", "Endless forms & dropdowns", "You pick the category", "Needs your bank login"],
  },
  lodgeos: {
    title: "LodgeOS",
    rows: ["Plain language — just say it", "Voice notes work too", "Snap a receipt, done", "Logged the instant it happens"],
  },
};

export const MEMORY_EXAMPLES = [
  { q: "How much have I spent at Tesco this year?", a: "£1,284 across 47 purchases." },
  { q: "What did I spend on fuel last month?", a: "£163.40 — down £21 on the month before." },
  { q: "Show all expenses for the kitchen renovation.", a: "14 records · £4,210 — Wickes, Howdens, plumber, tiler…" },
];

export type Feature = { icon: string; title: string; body: string };

export const FEATURES: Feature[] = [
  { icon: "🎯", title: "Budgets", body: "Set a budget by talking. LodgeOS tracks it and warns you before you overspend." },
  { icon: "🔁", title: "Subscriptions", body: "Recurring charges detected automatically, with a monthly total you can act on." },
  { icon: "💡", title: "Insights", body: "“You spent 12% less on coffee this month.” Real trends from your own records." },
  { icon: "📈", title: "Dashboard", body: "A private, link-scoped web view of your spending — charts, budgets, history." },
  { icon: "🗂", title: "Spaces", body: "Keep Personal, Business and Property apart so nothing ever gets mixed up." },
  { icon: "🧾", title: "History", body: "Every record kept, searchable in plain language. Nothing lost, nothing hidden." },
  { icon: "📊", title: "Reports", body: "Weekly and monthly summaries, by category, by space, by currency." },
  { icon: "🔔", title: "Reminders", body: "An opt-in daily digest and morning briefing so tracking becomes a habit." },
];

export type Persona = { role: string; emoji: string; scenario: string };

export const PERSONAS: Persona[] = [
  { role: "Landlords", emoji: "🏠", scenario: "“Tenant paid £850 rent for Flat 2.” → rent logged to the right property space." },
  { role: "Freelancers", emoji: "💻", scenario: "“Client paid £500 invoice.” → income recorded, ready for the tax bucket." },
  { role: "Tutors", emoji: "📚", scenario: "“£40 for a session with John.” → income tracked per student, no spreadsheet." },
  { role: "Consultants", emoji: "🧠", scenario: "“Spent £30 on Facebook ads.” → marketing expense, categorised instantly." },
  { role: "Tradespeople", emoji: "🔧", scenario: "Snap the Screwfix receipt → materials logged, VAT captured." },
  { role: "Property managers", emoji: "🏢", scenario: "“Paid plumber £120 for Flat 3.” → maintenance cost on the right unit." },
];

export type Trust = { icon: string; title: string; body: string };

export const TRUST: Trust[] = [
  { icon: "🔒", title: "Privacy-first", body: "Your records are yours. Dashboard links are private and expire." },
  { icon: "📦", title: "Local-first", body: "Runs on your own storage. No vendor lock-in, exportable any time." },
  { icon: "🧾", title: "Append-only audit trail", body: "Corrections never delete — every change is kept and reversible." },
  { icon: "👥", title: "Multi-user isolation", body: "Each Telegram user’s data is scoped to them alone." },
  { icon: "🎯", title: "95%+ accuracy gate", body: "A regression suite blocks releases below 95% on a 100-message set." },
  { icon: "✅", title: "180+ automated tests", body: "Deterministic-over-clever: the numbers come from your ledger, not a guess." },
];

export const ROADMAP = {
  today: ["Personal Finance", "Small Business"],
  tomorrow: ["Property Management", "Healthcare", "Education", "Inventory", "Field Operations"],
};

export const ARCHITECTURE = [
  "Natural Language",
  "Intent Parser",
  "Validation",
  "Domain Router",
  "Plugin System",
  "Storage",
  "Insights",
];

export const HOW_IT_WORKS = [
  { mode: "Text", icon: "💬", input: "Spent £20 at Tesco", result: "Groceries · £20.00 · recorded" },
  { mode: "Voice", icon: "🎤", input: "🎙️ 0:04 voice note", result: "Transcribed → recorded" },
  { mode: "Photo", icon: "🧾", input: "Receipt photo", result: "Merchant + total extracted" },
];
