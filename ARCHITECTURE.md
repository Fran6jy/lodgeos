# OpenClaw — System Architecture

## Text-Based Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INTEGRATION LAYER                               │
│                                                                         │
│   ┌──────────┐   ┌──────────────┐   ┌─────────────┐   ┌─────────────┐ │
│   │   CLI    │   │ Telegram Bot │   │  Signal Bot │   │  REST API   │ │
│   │ (Phase1) │   │  (Phase 2)   │   │  (Phase 3)  │   │  (Phase 5)  │ │
│   └────┬─────┘   └──────┬───────┘   └──────┬──────┘   └──────┬──────┘ │
│        └────────────────┴──────────────────┴─────────────────┘        │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ message: str, user_id: str
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       AGENT ORCHESTRATOR                                │
│                    (agent_orchestrator.py)                              │
│                                                                         │
│   Input → IntentParser → SchemaValidator → Router → Plugin → Response  │
└──────┬──────────┬─────────────────┬───────────────────────┬────────────┘
       │          │                 │                       │
       ▼          ▼                 ▼                       ▼
┌──────────┐ ┌─────────┐   ┌──────────────┐       ┌──────────────┐
│  Intent  │ │ Schema  │   │    Router    │       │    Memory    │
│  Parser  │ │Validator│   │  (router.py) │       │    Store     │
│          │ │         │   │              │       │ (in-session) │
│ Pass 1:  │ │ Validate│   │ domain→      │       └──────────────┘
│  Intent  │ │ record  │   │ plugin map   │
│ classify │ │ contract│   │              │
│          │ │         │   │ Fallback:    │
│ Pass 2:  │ │         │   │ confidence   │
│  Entity  │ │         │   │ threshold    │
│ extract  │ └─────────┘   └──────┬───────┘
└──────────┘                      │
       │                          │ routes to
       ▼                          ▼
┌──────────────┐        ┌─────────────────────────────────────────────┐
│  LLM Client  │        │              DOMAIN PLUGINS                 │
│              │        │                                             │
│  Anthropic   │        │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  Claude API  │        │  │ Finance  │  │ Property │  │Education │ │
│              │        │  │(Phase 1) │  │(Phase 3) │  │(Phase 4) │ │
│  - temp=0    │        │  └────┬─────┘  └──────────┘  └──────────┘ │
│  - caching   │        │       │                                     │
│  - JSON only │        │  ┌────┴────────────────────────────────┐   │
└──────────────┘        │  │ BasePlugin interface:               │   │
                        │  │  validate() transform() store()    │   │
                        │  │  query()    summarize()            │   │
                        │  │  build_response()                  │   │
                        │  └────────────────────────────────────┘   │
                        └─────────────────┬───────────────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────────────┐
                        │               STORAGE LAYER                 │
                        │                                             │
                        │  ┌──────────────┐  ┌───────────────────┐   │
                        │  │    SQLite    │  │   JSON (flat)     │   │
                        │  │  (Phase 1)   │  │   (Phase 1 alt)   │   │
                        │  └──────────────┘  └───────────────────┘   │
                        │                                             │
                        │  ┌──────────────┐  ┌───────────────────┐   │
                        │  │   hledger /  │  │   PostgreSQL      │   │
                        │  │   beancount  │  │   (Phase 2/3)     │   │
                        │  │  (Phase 2)   │  └───────────────────┘   │
                        │  └──────────────┘                           │
                        └─────────────────────────────────────────────┘
```

## Data Flow

```
User Message (natural language)
         │
         ▼
[IntentParser] ──────────────── LLM Pass 1: classify intent + domain
         │                               ↓
         │                        {intents, primary_intent,
         │                         confidence, domain}
         │
         ▼
[IntentParser] ──────────────── LLM Pass 2: extract entities
         │                               ↓
         │                        {domain, type, timestamp,
         │                         entities, amount, currency,
         │                         description, raw_input, confidence}
         │
         ▼
[SchemaValidator] ─────────────── validate record contract
         │
         ▼
[Router] ──────────────────────── map domain → plugin
         │                        fallback if low confidence
         │
         ▼
[Plugin.transform()] ──────────── enrich, infer category,
         │                        normalise fields
         │
         ▼
[Plugin.store()] ───────────────── persist to SQLite
         │
         ▼
[Plugin.build_response()] ──────── human-friendly confirmation
         │                         + budget remaining
         │
         ▼
 Response to user
```

## Record Contract (all domains)

```json
{
  "id":           "uuid",
  "domain":       "finance | property | education | healthcare | inventory | personal_life | field_operations | general",
  "type":         "expense | income | task | event | inventory_update | care_log | education_record | property_transaction | general_note",
  "timestamp":    "ISO8601",
  "entities":     { "merchant": null, "category": null, "tags": [], "notes": null },
  "amount":       4.50,
  "currency":     "GBP",
  "description":  "Coffee at Nero",
  "raw_input":    "Spent £4.50 at Nero for coffee",
  "confidence":   0.92,
  "user_id":      "default",
  "processed_at": "ISO8601"
}
```

## SQLite Schema

```sql
records (
  id          TEXT PRIMARY KEY,
  domain      TEXT NOT NULL,
  type        TEXT NOT NULL,
  amount      REAL,
  currency    TEXT DEFAULT 'GBP',
  description TEXT,
  timestamp   TEXT NOT NULL,
  user_id     TEXT DEFAULT 'default',
  confidence  REAL,
  data        TEXT NOT NULL,     -- full JSON record
  created_at  TEXT NOT NULL
)

budgets (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  category    TEXT NOT NULL,
  amount      REAL NOT NULL,
  currency    TEXT DEFAULT 'GBP',
  period      TEXT NOT NULL,     -- 'weekly' | 'monthly'
  created_at  TEXT NOT NULL,
  UNIQUE(user_id, category, period)
)
```

## Folder Structure

```
openclaw/
├── core/
│   ├── agent_orchestrator.py   ← main entry point for all integrations
│   ├── intent_parser.py        ← two-pass LLM extraction
│   ├── schema_validator.py     ← record contract enforcement
│   ├── router.py               ← domain routing with fallback
│   └── memory_store.py         ← in-session context
│
├── domains/
│   └── finance/
│       └── finance_plugin.py   ← full Phase 1 implementation
│
├── plugins/
│   ├── base_plugin.py          ← abstract plugin interface
│   └── plugin_registry.py      ← plugin registry
│
├── storage/
│   └── sqlite_adapter.py       ← SQLite with WAL mode + budgets
│
├── llm/
│   ├── anthropic_client.py     ← Claude client + mock
│   ├── prompt_templates.py     ← all LLM prompts
│   └── function_schemas.py     ← JSON schemas + constants
│
├── integrations/
│   ├── cli/cli.py              ← Phase 1 CLI
│   ├── telegram_bot/bot.py     ← Phase 2 skeleton
│   └── api_server/             ← Phase 5 placeholder
│
├── utils/
│   ├── date_parser.py          ← datetime parsing
│   └── currency_normalizer.py  ← amount + currency extraction
│
└── tests/
    ├── test_intent_parser.py
    ├── test_schema_validator.py
    ├── test_router.py
    ├── test_finance_plugin.py
    ├── test_sqlite_adapter.py
    ├── test_orchestrator.py
    └── sample_dataset.py       ← 20+ regression messages
```

## Roadmap

### Phase 1 — Core Engine ✅ (implemented)
- [x] Intent parser (two-pass LLM)
- [x] Schema validator
- [x] Domain router with fallback
- [x] Finance plugin (expenses, income, budgets, reporting)
- [x] SQLite storage (WAL mode, budgets table)
- [x] CLI with /commands
- [x] Mock LLM for offline development
- [x] Full test suite

### Phase 2 — Telegram + Reporting
- [ ] Telegram bot (skeleton done, needs token)
- [ ] hledger export adapter
- [ ] Recurring expense detection
- [ ] Weekly/monthly digest via cron
- [ ] Budget alerts (push notification when near limit)

### Phase 3 — Property Plugin
- [ ] Rent payments (tenant, amount, period)
- [ ] Maintenance cost tracking
- [ ] Profit/loss per property
- [ ] Tenant log (payments, issues)

### Phase 4 — Education + Healthcare
- [ ] Education: student progress, attendance, behaviour logs
- [ ] Healthcare: medication logs with audit trail, care activities, shift reports
- [ ] Audit trail adapter (immutable append-only for care logs)

### Phase 5 — Full Platform
- [ ] FastAPI REST server
- [ ] Signal bot integration
- [ ] PostgreSQL adapter
- [ ] Multi-user auth (API keys)
- [ ] Plugin hot-reload
- [ ] Web dashboard (optional)

## Design Principles

| Principle              | Implementation                                          |
|------------------------|---------------------------------------------------------|
| Local-first            | SQLite default, no cloud dependency                     |
| No vendor lock-in      | LLM client is swappable (mock, Claude, Ollama)          |
| Privacy preserving     | All data stays on-device                                |
| Auditability           | Append-only records, created_at immutable               |
| Deterministic outputs  | temperature=0, strict JSON prompts                      |
| Extensible via plugins | BasePlugin interface, Router.register()                 |
| Domain separation      | Each plugin owns its transform/store/query logic        |
