# LodgeOS — Project Handoff

_Snapshot for continuing after a context reset. Read this first._
_Last updated: 2026-06-27. Tests: **239 passing**. Branch of record: `main`._

## 1. What it is
**LodgeOS** (codename `openclaw` in source) is a **natural-language finance OS**, used through a **Telegram bot**. You talk (text, voice, photo); it extracts, validates, categorises, stores, reports. Local-first, deterministic, auditable. Python backend + a React landing page. Real users skew **Naira (NGN)**.

## 2. Where it runs (production)
- **GCP Compute Engine VM** `instance-20260605-223310`, zone `us-central1-a`, project `ai-analytics-423806`, ext IP `35.202.94.160`, Debian.
  - Browser-SSH user is **`fran6jy`** (app at `~/lodgeos`). Always `ssh fran6jy@instance-...` (the `fran6` default user has an empty home).
- **Docker Compose** (`~/lodgeos`): services `bot`, `dashboard`, `caddy`. Caddy serves HTTPS at **`https://35.202.94.160.sslip.io`**.
- `gcloud` CLI installed + authed locally at `$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`.

### Deploy command (used every time this session)
```powershell
$g="$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
& $g compute ssh fran6jy@instance-20260605-223310 --zone us-central1-a --quiet `
  --command "cd lodgeos && git pull --ff-only && docker compose up -d --build bot && echo DEPLOYED"
```
- Server pulls **`origin/main`**. Builds can be slow (~3 min) when the base image refreshes.
- **One-off scripts in the container** (e.g. DB maintenance): `scp` file → `docker compose cp <f> bot:/tmp/<f>` → `docker compose exec -T -w /app -e PYTHONPATH=/app bot python /tmp/<f>`. (Use PowerShell for the `gcloud ... --command "..."` SSH step; Git-Bash works for `scp`.)
- Production **DB path inside the container: `/data/openclaw.db`** (appdata volume).

## 3. 🔴 SECURITY — still must rotate (pasted in chat earlier, unrotated)
| Secret | Where | Action |
|---|---|---|
| **Telegram token** `8988509951:AAGa…` | `.env` `TELEGRAM_TOKEN` | @BotFather `/revoke` → new → `.env` → `docker compose up -d --force-recreate bot` |
| **OpenRouter key** `sk-or-v1-43dc…` | `.env` `OPENROUTER_API_KEY` | regenerate at openrouter.ai |
| **Groq key** `gsk_843si…` | `.env` `WHISPER_CLOUD_API_KEY` | regenerate at console.groq.com |
| Leaked SSH key + possible old Oracle VM (`84.8.156.16`) | — | rotate/terminate |
Bot handle is **`@LodgerOS_bot`** (note the "r"); brand string is **LodgeOS**.

## 4. Git branches (GitHub `Fran6jy/lodgeos`, private)
- **`main`** — the bot (Python). Deployed to GCP. Source of truth.
- **`landing`** — bot code **+** `landing/` React app **+** `netlify.toml`. Updated this session (feature copy). **Netlify NOT yet connected** — won't publish until you do (Add site → Import from Git → branch `landing`).
- **Commit style:** the user asked to **strip "Co-Authored-By: Claude" trailers** — history was rewritten once and trailers removed; **do NOT add that trailer to new commits.**

## 5. Architecture / code map
`openclaw/core/` — `agent_orchestrator.py` (the brain: routing, budget router, multi-item, refunds, corrections, currency), `intent_parser`, `correction_detector`, `document_parser`, `shopping.py`, `router`, `validator`, `memory_store`.
`openclaw/domains/finance/finance_plugin.py` — categorisation, budgets, summaries, Q&A, insights, subscriptions, Wrapped recap data, refunds-in-transform, semantic categoriser.
`openclaw/llm/` — clients + factory + prompts (`prompt_templates.py`).
`openclaw/integrations/telegram_bot/` — `bot.py` (handlers, jobs, pinning), `ui.py` (keyboards/copy/help), `charts.py` (donut + **premium Wrapped poster, Pillow**), `progress_manager.py`, `assets/fonts/` (vendored Inter + Space Grotesk TTFs).
`openclaw/storage/sqlite_adapter.py` — append-only records + soft-void + migrations; `user_prefs` holds active_list/budget/currency/reminders/help_pinned/referred_by/active_list_at; `category_cache` table.
`openclaw/tests/` — 239 tests, run `python -m pytest openclaw/tests -q`.

## 6. Feature inventory (all live)
**Capture:** NL text · voice (Groq Whisper-large-v3, cloud) · receipt/photo (vision fallback) · **multi-item** (rule splitter first, LLM fallback; needs currency markers for bare numbers).
**Money:** rule-based categorisation **+ semantic LLM fallback (cached)** · per-space budgets · NL budget verbs · **refunds = negative expenses** · **currency-aware** (NGN/£/$/€, grouped, **never summed across currencies — anywhere**) · **per-user home currency** (`set my currency to naira`; bare amounts follow it).
**Budgets** — set/see/spend-against/**rename**/**delete**/**delete-all (confirm)**/list→budget. HTML report with capsule progress bars.
**Spaces:** Personal/Business/Property/custom; always-shown **space chip** (🏠/💼/🏢).
**Shopping/market lists:** quantities, qty edits, price edits, category tags `[shopping]`, add-to-named-trip, buy→expense, remove item. **Active list auto-expires after 15 min idle** (`ACTIVE_TTL`) so it stops absorbing unrelated messages.
**Insights/Q&A:** financial memory ("how much at Tesco?") · spending insights vs last month · subscription detection.
**Reminders:** daily digest (20:00) · morning briefing (07:00) · **monthly Wrapped (1st, 09:00, `WRAPPED_HOUR`)** — opt-in; **new users default-enrolled** in all three; existing users were backfilled.
**Wrapped recap:** premium Pillow poster (radial glow, capsule bars, curated palette, highlight card, vendored fonts), `/wrapped` + 🎁 menu, share deep-link `t.me/<bot>?start=ref_<uid>`, `/start` captures `ref_`.
**UX:** menu reordered by importance; pinned "How to use" guide on `/start` (once); `/examples` card; friendly nudge for vague messages; greeting guard; **ambiguous spoken amounts** ("eight ten") → tap £8.10/£810.
**Reports views:** summary/month, history, category drill-down, income, subscriptions — all restyled to clean HTML (icons, bold, escaped).
**Dashboard:** private per-user token web view.
**LLM:** Anthropic → OpenRouter (`gpt-oss-20b:free`) fallback; offline `--mock`. Free tier 429s → 5–15s replies, masked by `progress_manager`.

## 7. Key design notes (don't re-break these)
- **All "budget" messages route through one classifier: `AgentOrchestrator._route_budget`** (precedence: delete → query → convert-list → set → trip → log-against). Don't re-scatter budget logic into `shopping.handle`. (Memory: `budget-router`.)
- **Never sum across currencies.** `summarize`, `_budget_report`, and Q&A (`answer_question`/`execute_query_plan` via `_sum_by_currency`/`_fmt_multi`) all group per currency.
- **Refunds** are forced to a negative **finance** expense in `FinancePlugin.transform` (any path), shown as "↩️ Recorded refund". Prompt + heuristic no longer call refund "income".
- **Categorisation** is keyword-first (`CATEGORY_KEYWORDS`, includes Naira staples), then a cached LLM fallback (`build_llm_categoriser`, `category_cache` table) wired in `bot._build_orchestrator`.
- **Active shopping list** only absorbs bare items/edits/removes while *fresh* (`active_list_age` ≤ `ACTIVE_TTL`); always usable by name (show/bought/add-to-<name>). Corrections, ledger deletes and expenses are explicitly excluded from absorption.

## 8. This session's deliverables outside the bot
- **Investor pitch PDF** at `C:\Users\fran6\Downloads\LodgeOS_Investor_Pitch.pdf` (14-page dark deck; has `[founder: …]` placeholders for metrics/market/ask).
- **Social copy** (X/LinkedIn/IG + full Features section + 10-slide carousel) and a **screen-recording run-of-show** — delivered in chat, not committed.
- **fran6jy's demo account wiped** (user_id `8008172274`, 71 rows) for clean recording; other 3 users untouched. Telegram usernames are NOT stored — identify accounts by data fingerprint (lists/budgets/currencies).

## 9. Open items / next steps
1. **Rotate the 3 secrets** (section 3) — highest priority.
2. ~~Decide refund model~~ **RESOLVED 2026-06-27 → (A)**: keep the original record and add a separate −refund record (net-correct, full audit trail). This is already the live, tested behavior (`FinancePlugin.transform` forces refunds to a negative finance expense; `TestRefunds`). No further work — option B (silently reducing the matching original) is rejected.
3. **Connect Netlify** to the `landing` branch so site updates publish.
4. **Optional:** one-message **demo pre-load** (offered, not built) to fill a ₦ month for filming.
5. Phase-3 **property plugin**; base-currency FX; Postgres scale; Pro tier.

## 10. Gotchas
- Single-process polling bot, ~1 GB VM (2 GB swap). Biggest scale lever = paid LLM, then Postgres (storage swappable).
- **Demo data is messy across £/$/₦** on old accounts → reports look confusing (correct, just mixed currency). Record on a clean account with `set my currency to naira`.
- matplotlib font lacks emoji → Wrapped poster strips emoji from drawn text (kept in Telegram caption). Clash Display auto-used if its TTF is dropped in `assets/fonts/`.
- LF→CRLF warnings on commit are harmless.
- Memory files (`~/.claude/.../memory/`): `budget-router`, `users-naira-primary`, plus OpenClaw overview/state/deployment.
