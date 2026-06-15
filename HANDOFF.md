# LodgeOS — Project Handoff

_Snapshot for continuing work after a context reset. Read this first._

## 1. What it is
**LodgeOS** (codename `openclaw` in the source) is a **natural-language record OS for finance**, used through a **Telegram bot**. You talk (text, voice, or photo); it extracts, validates, categorises, stores, and reports. Local-first, deterministic, auditable. Python backend + a React landing page.

## 2. Where it runs (production)
- **GCP Compute Engine VM** `instance-20260605-223310`, zone `us-central1-a`, project `ai-analytics-423806`, external IP `35.202.94.160`, Debian 12.
  - **Two Linux users matter:** browser-SSH logs in as **`fran6jy`** (where the app lives at `~/lodgeos`); `gcloud compute ssh` defaults to `fran6` (empty home) — **always use `fran6jy@instance-...`**.
- Runs via **Docker Compose** (`~/lodgeos`): services `bot`, `dashboard`, `caddy`. Caddy serves HTTPS for **`https://35.202.94.160.sslip.io`** (sslip.io = IP-based DNS, no domain needed).
- **`gcloud` CLI is installed + authed** locally (`fran6jy@gmail.com`) at `C:\Users\fran6\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`.

### Deploy command (the one used all session)
```powershell
$g="$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
& $g compute ssh fran6jy@instance-20260605-223310 --zone us-central1-a --quiet `
  --command "cd lodgeos && git pull --ff-only && docker compose up -d --build bot"
```
Server pulls **`origin/main`**. Useful: `docker compose logs -f bot`, `docker compose ps`, `docker compose restart`.

## 3. 🔴 SECURITY — rotate these (all pasted in chat, still in use)
| Secret | Where | Action |
|---|---|---|
| **Telegram bot token** `8988509951:AAGa…` | server `.env` `TELEGRAM_TOKEN` | @BotFather `/revoke` `LodgerOS` → new token → update `.env` → `docker compose up -d --force-recreate bot` |
| **OpenRouter key** `sk-or-v1-43dc…` | `.env` `OPENROUTER_API_KEY` | regenerate at openrouter.ai |
| **Groq key** `gsk_843si…` | `.env` `WHISPER_CLOUD_API_KEY` | regenerate at console.groq.com |
| Old SSH key `lodgeos_key` | (instance) | a previous private key was leaked; current access is fine but consider rotating |
Also: an **earlier Oracle VM** (IP `84.8.156.16`) may still be running with a leaked key — terminate it.

## 4. Server `.env` (key vars)
`TELEGRAM_TOKEN`, `OPENROUTER_API_KEY`, `WHISPER_MODE=cloud`, `WHISPER_CLOUD_API_KEY` (Groq `whisper-large-v3`), `DASHBOARD_BASE_URL=https://35.202.94.160.sslip.io`, `DASHBOARD_ROOT=0`, `BRAND_NAME=LodgeOS`, `DONATE_URL=https://www.paypal.me/Fran6jy`, `DIGEST_HOUR=20`, `BRIEFING_HOUR=7`.

## 5. Git branches (GitHub `Fran6jy/lodgeos`, private)
- **`main`** — the **bot** (Python). Deployed to GCP. This is the source of truth for the backend.
- **`landing`** — bot code **plus** the `landing/` React app **plus** `netlify.toml`. Use this branch for the website deploy.
- Bot fixes go on `main`; they were cherry-picked there when committed on `landing` by mistake. Keep new **bot** work on `main`.

## 6. Feature inventory (all built, ~192 tests, regression 100%)
**Capture:** text NL · voice notes (Groq Whisper-large-v3, cloud) · receipt/photo parsing (vision-model fallback chain) · **multi-item extraction** (one message/voice paragraph → many records).
**Money:** rule-based categorisation incl. Groceries & Marketing · per-space budgets · NL budget setting ("set tea budget to 50") · refunds (negative amounts) · **currency-aware** (NGN/£/$/€…, grouped never summed across currencies).
**Spaces:** Personal/Business/Property/custom; prefix (`Business: …`) or NL switch; name normalisation.
**Corrections:** update / soft-void (audit trail) with hallucination-guarded targeting + tap-to-pick buttons; bulk void with confirmation.
**Insights/Q&A:** Financial Memory ("how much at Tesco?") deterministic + LLM query-plan fallback · spending insights · subscription detection.
**Shopping/price lists (newest):** "start a chai list: ginger 500, milk 1200" → plan → update prices → "bought chai" → one Groceries expense. `ShoppingManager` in `openclaw/core/shopping.py`, `shopping_items` table, `active_list` pref.
**Reminders:** opt-in daily digest (20:00) + morning briefing (07:00) via PTB JobQueue; `/reminders`.
**UI:** inline-keyboard menu, HTML cards, `/` command list, perceived-performance layer (`progress_manager.py` — ack <500ms, typing, staged edits, insight-after-5s), first-run tutorial, 💖 donate, 🔔 reminders.
**Dashboard:** read-only, per-user token links (`/dashboard`), space filter, charts.
**LLM layer:** Anthropic → OpenRouter (`gpt-oss-20b:free`) fallback; offline `--mock`.

### Code map
`openclaw/core/` orchestrator, intent_parser, correction_detector, document_parser, **shopping**, router, validator, memory · `openclaw/domains/finance/finance_plugin.py` · `openclaw/llm/` clients+factory+prompts · `openclaw/integrations/{telegram_bot,api_server,transcription,session_store}` · `openclaw/storage/sqlite_adapter.py` (append-only + soft-void + migrations) · `openclaw/tests/`.
SQLite DB lives in the `appdata` Docker volume at `/data/openclaw.db`.

## 7. Landing page (`landing/`, on `landing` branch)
React + TS + Tailwind + Framer Motion (Vite). Centrepiece: live Telegram simulator. `cd landing && npm i && npm run dev` (or `npm run build`). 9 Vitest tests. **Netlify NOT yet connected** — `netlify.toml` is ready (base=`landing`, build=`npm run build`, publish=`dist`).

## 8. Outstanding / next steps
1. **Rotate the 3 exposed tokens** (section 3) — highest priority before wider use.
2. **Connect Netlify** to the `landing` branch (Add site → Import from Git → branch `landing`; or CLI with a token).
3. **Phase 3 — property plugin** (rent/maintenance/tenant logs; Spaces already support per-flat profit).
4. Smaller asks floated: per-item **quantities** in shopping lists; **balance + forecast** primitive for the full morning briefing; base-currency **FX conversion**; Redis-backed sessions; chart/insights full currency-grouping; rename `LodgeOS` vs `LodgerOS` (bot handle is `LodgerOS_bot`).

## 9. Gotchas
- Bot is **single-process polling**; ~tens of concurrent users on free LLM + 1 GB VM. Biggest scale lever = paid LLM, then Postgres (storage layer is swappable).
- Free OpenRouter tier 429s a lot → retries make replies slow (5–15s); the perceived-performance layer masks it.
- 1 GB VM has a **2 GB swap** file; voice is offloaded to Groq so RAM is fine.
- Windows line-ending (LF→CRLF) warnings on commit are harmless.
