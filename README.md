# LodgeOS

**A natural-language operating system for structured records.** Talk to it in plain
English — by text, voice, or a photo — and it turns what you say into validated,
auditable finance records. Not a chatbot: a multi-domain transaction engine with a
Telegram front-end, a private web dashboard, and a local-first SQLite ledger.

> Working/codename in the source tree: `openclaw`.

---

## What it does

Send any of these to the Telegram bot and it records, categorises, and confirms:

- 💬 **Text** — *“Spent £4.50 at Nero for coffee”*, *“Received salary £3200”*
- 🎙 **Voice notes** — transcribed locally (or via a cloud endpoint)
- 🧾 **Photos** — receipts, invoices, payslips, bank screenshots → parsed by a vision model
- ✏️ **Corrections** — *“Actually that coffee was £6”*, *“Delete the £5 one”*
- 📊 **Insights** — weekly/monthly summaries, budgets, a spending donut, and a private dashboard

### Highlights

| Area | What's built |
|---|---|
| **Pipeline** | intent parse → schema validate → route → domain plugin → store → respond |
| **Categorization** | rule-based keyword engine (deterministic; LLM-free), incl. a dedicated **Groceries** split |
| **LLM layer** | Anthropic → OpenRouter fallback chain; offline **mock mode** (no key, no cost) |
| **Voice** | `faster-whisper` local **or** cloud — one config toggle |
| **Images** | vision-model fallback chain; refunds stored as negative amounts |
| **Corrections** | update / soft-void (append-only audit trail) with hallucination-guarded targeting + tap-to-pick menus |
| **Dashboard** | read-only, per-user **token-scoped** private links; spending charts, drill-down, pagination |
| **Quality** | 123 tests; regression harness gates **95%** domain/intent/category accuracy |

---

## Quickstart (local, zero cost)

No API keys needed — uses the built-in heuristic mock LLM.

```bash
pip install -r requirements.txt

# CLI
python -m openclaw.integrations.cli.cli --mock

# Telegram (only a BotFather token needed in mock mode)
export TELEGRAM_TOKEN=<your-botfather-token>
python -m openclaw.integrations.telegram_bot.bot --mock
```

### With real understanding (OpenRouter)

```bash
export TELEGRAM_TOKEN=<botfather-token>
export OPENROUTER_API_KEY=<sk-or-...>     # text + vision
python -m openclaw.integrations.telegram_bot.bot
```

Set `ANTHROPIC_API_KEY` too and Anthropic is used first, OpenRouter as fallback.

### Dashboard

```bash
python -m openclaw.integrations.api_server.dashboard
# → http://127.0.0.1:8000   (localhost, read-only, single user)
```
In the bot, `/dashboard` mints a private, time-limited link scoped to that user.

---

## Configuration

Copy `.env.example` → `.env` and fill in. Key variables:

| Variable | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | BotFather token |
| `OPENROUTER_API_KEY` | text + vision model access |
| `ANTHROPIC_API_KEY` | optional; tried first if set |
| `WHISPER_MODE` | `local` (faster-whisper) or `cloud` |
| `DASHBOARD_BASE_URL` | public URL for `/dashboard` links |
| `BRAND_NAME` | user-facing name (default `LodgeOS`) |

Full list with comments in [`.env.example`](.env.example).

---

## Deployment

One-box VPS + Docker (bot + dashboard + Caddy auto-HTTPS). See **[DEPLOY.md](DEPLOY.md)**.

```bash
cp .env.example .env   # fill in
docker compose up -d --build
```

---

## Architecture

```
Telegram / CLI / API
        │
   AgentOrchestrator  ──►  IntentParser ─► SchemaValidator ─► Router ─► Plugin ─► SQLite
        │                  CorrectionDetector / DocumentParser
        └── LLM factory: Anthropic → OpenRouter (fallback) | Mock
```

- `openclaw/core` — orchestrator, parsers, router, validator, memory
- `openclaw/domains/finance` — the finance plugin (categories, budgets, reporting)
- `openclaw/llm` — clients, fallback chain, prompts
- `openclaw/integrations` — Telegram bot, CLI, dashboard, transcription
- `openclaw/storage` — append-only SQLite adapter (soft-void, audit history)

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

---

## Testing

```bash
python -m pytest -q                                  # full suite (123 tests)
python -m openclaw.tests.regression.report           # accuracy report
```

---

## Design principles

Local-first · deterministic over clever · auditability over intelligence · domain
separation · privacy-preserving (financial data is sensitive — the dashboard is
read-only and access-scoped by design).

## Roadmap

Phase 1–2 (finance: text/voice/image, corrections, dashboard) ✅ · Phase 3 property ·
Phase 4 education + healthcare · Phase 5 full orchestration API.
