import { describe, expect, it } from "vitest";
import { classify, formatMoney, respond, symbolFor } from "./simulator";

describe("formatMoney", () => {
  it("formats GBP with the £ symbol and 2dp", () => {
    expect(formatMoney(4.5, "GBP")).toBe("£4.50");
    expect(formatMoney(1284, "GBP")).toBe("£1,284.00");
  });
  it("supports other currencies", () => {
    expect(symbolFor("NGN")).toBe("₦");
    expect(formatMoney(5000, "NGN")).toBe("₦5,000.00");
  });
});

describe("classify", () => {
  it("parses a record from natural language", () => {
    const r = classify("Spent £4.50 at Nero for coffee");
    expect(r.type).toBe("record");
    if (r.type === "record") {
      expect(r.amount).toBe(4.5);
      expect(r.currency).toBe("GBP");
      expect(r.merchant).toBe("Nero");
      expect(r.category).toBe("Food & Drink");
    }
  });

  it("categorises a supermarket as groceries", () => {
    const r = classify("Bought groceries at Tesco £62");
    expect(r.type).toBe("record");
    if (r.type === "record") expect(r.category).toBe("Groceries");
  });

  it("recognises questions as queries", () => {
    expect(classify("How much have I spent on coffee this month?")).toMatchObject({
      type: "query",
      topic: "coffee",
    });
    expect(classify("What did I spend on fuel last month?")).toMatchObject({ type: "query", topic: "fuel" });
  });

  it("falls back to unknown for chit-chat", () => {
    expect(classify("hello there").type).toBe("unknown");
  });
});

describe("respond", () => {
  it("returns a recorded card with the passed budget remaining", () => {
    const reply = respond("Spent £4.50 at Nero for coffee", 45.5);
    expect(reply.kind).toBe("recorded");
    if (reply.kind === "recorded") {
      expect(reply.card.merchant).toBe("Nero");
      expect(reply.card.budgetRemaining).toBe(45.5);
    }
  });

  it("returns the coffee insight for the coffee question", () => {
    const reply = respond("How much have I spent on coffee this month?", null);
    expect(reply.kind).toBe("insight");
    if (reply.kind === "insight") {
      expect(reply.card.headline).toBe("£32.40");
      expect(reply.card.emoji).toBe("☕");
    }
  });

  it("gives a helpful nudge for unknown input", () => {
    const reply = respond("???", null);
    expect(reply.kind).toBe("text");
  });
});
