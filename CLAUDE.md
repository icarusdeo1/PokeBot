# CLAUDE.md — PokeDrop Bot

**Source of truth:** `PokeBot_PRD.md` — all product direction, requirements, and acceptance criteria live there.

---

## Product Overview

**PokeDrop Bot** is a high-speed auto-checkout automation for Pokemon merchandise. It monitors retailer pages (Target, Walmart, Best Buy) for restocks and completes purchases within milliseconds of stock availability.

**Operator interface:** Web dashboard at `http://localhost:8080` — no CLI, no terminal, no technical knowledge required.

---

## Architecture — Two-Process Model

```
┌─────────────────────────────────────────────────────────────┐
│  Daemon (src/daemon.py)                                     │
│  - Runs silently in background                              │
│  - Handles all bot logic: monitoring, cart, checkout        │
│  - Communicates with dashboard via SQLite (state.db) + SSE  │
└─────────────────────────────────────────────────────────────┘
                            │
                     SQLite state.db
                     SSE stream
                            │
┌─────────────────────────────────────────────────────────────┐
│  Dashboard (src/dashboard/server.py — FastAPI + Uvicorn)   │
│  - Serves web UI at http://localhost:8080                  │
│  - All operator interaction goes through here               │
│  - Consumes SSE for real-time event display                 │
└─────────────────────────────────────────────────────────────┘
```

**Operator never interacts directly with the daemon.** All actions go through the dashboard.

---

## Tech Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| Language | Python | 3.11+, async ecosystem |
| HTTP Client | httpx | ≥0.27, async, HTTP/2 |
| Browser Automation | Playwright | ≥1.40, headless, anti-detect |
| CAPTCHA Solving | 2Captcha API + Manual Mode | Smart routing (see Section 9.4 PRD) |
| Config | YAML + PyYAML | ≥6.0, human-readable |
| Web Framework | FastAPI | ≥0.110, async |
| ASGI Server | Uvicorn | ≥0.27 |
| Frontend | Vanilla HTML + CSS + JS | No build step, SPA |
| Local Database | SQLite | `state.db` (bot state) + `auth.db` (credentials), WAL mode |
| Password Hashing | argon2 or bcrypt | Dashboard PIN/password |
| Real-time | Server-Sent Events (SSE) | Daemon → Dashboard push |
| Notifications | aiohttp | Async webhook delivery |
| Testing | pytest + Playwright | ≥8.0 |
| Type Checking | mypy | ≥1.8 |

### What We DO NOT Use

- **`argparse` / CLI** — replaced by web dashboard. No terminal commands.
- **`Rich` / `Textual` TUI** — removed. Replaced by web dashboard.
- **`requests`** — use `httpx` (async required)
- **`threading / multiprocessing`** — use `asyncio` only
- **Selenium** — use Playwright only
- **Firebase / Supabase / external DB** — local SQLite only

---

## Project Structure

```
poke-drop-bot/
├── config.yaml                  # Runtime config (NOT committed)
├── config.example.yaml          # Template, all keys, no secrets
├── auth.db                      # SQLite: operator credentials, sessions
├── state.db                     # SQLite: bot state, event history (WAL mode)
├── requirements.txt
├── pyproject.toml
├── README.md
├── src/
│   ├── __init__.py
│   ├── daemon.py                # Bot daemon entry point (background process)
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── config.py            # Config loading + validation (YAML)
│   │   ├── logger.py            # Structured logging → file + SSE
│   │   ├── monitor/
│   │   │   ├── stock_monitor.py # Core state machine
│   │   │   └── retailers/
│   │   │       ├── base.py      # Abstract RetailerAdapter (ABC)
│   │   │       ├── target.py
│   │   │       ├── walmart.py
│   │   │       └── bestbuy.py
│   │   ├── checkout/
│   │   │   ├── cart_manager.py
│   │   │   ├── checkout_flow.py
│   │   │   ├── payment.py
│   │   │   ├── shipping.py
│   │   │   └── captcha.py
│   │   ├── evasion/
│   │   │   ├── user_agents.py
│   │   │   ├── fingerprint.py
│   │   │   ├── jitter.py
│   │   │   └── proxy.py
│   │   ├── notifications/
│   │   │   ├── webhook.py
│   │   │   ├── discord.py
│   │   │   └── telegram.py
│   │   └── session/
│   │       └── prewarmer.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── server.py            # FastAPI app — dashboard + API
│   │   ├── auth.py              # Login, session management, PIN hashing
│   │   ├── routes/
│   │   │   ├── status.py        # GET /api/status
│   │   │   ├── config.py        # GET/PATCH /api/config
│   │   │   ├── events.py        # GET /api/events/stream (SSE)
│   │   │   ├── monitor.py       # POST /api/monitor/start, /stop
│   │   │   ├── dryrun.py        # POST /api/dryrun
│   │   │   └── health.py        # GET /health
│   │   └── templates/
│   │       └── index.html       # Dashboard SPA
│   └── shared/
│       ├── __init__.py
│       ├── db.py                # SQLite helpers (WAL mode)
│       └── models.py            # Shared dataclasses
└── tests/
    ├── conftest.py
    ├── test_bot/
    ├── test_dashboard/
    └── test_auth.py
```

---

## Core State Machine

```
STANDBY ──[stock detected]──> STOCK_FOUND ──[cart added]──> CART_READY
  │                                  │                          │
  │                                  │                          ▼
  │                                  └────────[checkout done]──> CHECKOUT_COMPLETE
  │                                                               │
  │                                                               ▼
  └─────────────[failure/timeout]──────────────────────────────> CHECKOUT_FAILED
```

---

## Data Models

All dataclasses defined in `src/shared/models.py`. Import from there — do not redefine.

Key entities: `MonitoredItem`, `RetailerAdapter`, `CheckoutConfig`, `ShippingInfo`, `PaymentInfo`, `WebhookEvent`, `SessionState`

---

## Webhook Event Catalog (15 events)

All must fire in correct sequence. See PRD Section 8.2.

| Event | Trigger |
|-------|---------|
| `MONITOR_STARTED` | Bot starts monitoring |
| `STOCK_DETECTED` | OOS → IS transition |
| `CART_ADDED` | Item confirmed in cart |
| `CHECKOUT_STARTED` | Checkout flow initiated |
| `CHECKOUT_SUCCESS` | Order confirmed |
| `CHECKOUT_FAILED` | Checkout rejected |
| `CAPTCHA_REQUIRED` | CAPTCHA detected |
| `CAPTCHA_SOLVED` | CAPTCHA solved |
| `CAPTCHA_PENDING_MANUAL` | Bot paused for manual solve |
| `CAPTCHA_MANUAL_RESOLVED` | Operator resolved CAPTCHA |
| `CAPTCHA_MANUAL_TIMEOUT` | Manual solve timed out |
| `CAPTCHA_BUDGET_EXCEEDED` | Daily 2Captcha budget hit |
| `QUEUE_DETECTED` | Retailer queue entered |
| `QUEUE_CLEARED` | Queue position released |
| `SESSION_EXPIRED` | Auth/session invalidated |
| `PAYMENT_DECLINED` | Payment rejected |

---

## CAPTCHA Modes

| Mode | Behavior |
|------|----------|
| `auto` | All CAPTCHAs sent to 2Captcha; operator pays per solve |
| `manual` | Bot pauses; fires `CAPTCHA_PENDING_MANUAL`; waits for operator to solve in browser |
| `smart` (default) | Turnstile → auto-solve; reCAPTCHA/hCaptcha → manual mode |

CAPTCHA Budget: `$5.00/day` default, per-retailer overrides supported.

---

## Dashboard Features (DSH Requirements)

- **Login**: PIN/password authentication, hashed with argon2/bcrypt
- **Status view**: Daemon online/offline, active items, per-retailer session health (green/yellow/red)
- **Real-time event log**: SSE stream — timestamp, event type, item, retailer
- **Start/Stop buttons**: With confirmation dialogs
- **Item selector**: Choose items and retailers before starting
- **Dry-run panel**: Full checkout without placing order, output streamed to dashboard
- **Settings page**: Form-based config editing (no raw YAML), inline validation
- **Validate Config button**: Full schema validation with specific error messages
- **CAPTCHA panel**: Mode, daily spend vs. budget, per-retailer breakdown, solve time alerts
- **Drop Window Calendar**: Scheduled drops with auto-prewarm, per-drop `max_cart_quantity`
- **Multi-Account panel**: Per-account session health, enabled/disabled toggle
- **Event history**: Last 500 events, filterable by type/retailer/item
- **Restart Daemon button**: In header, with confirmation
- **Setup Wizard**: First launch — PIN setup, retailer account, shipping, payment, CAPTCHA mode
- **Viewer role**: Read-only access — can see status/logs but cannot start/stop/change settings

---

## Configuration Rules

- **`config.yaml`** — runtime config, never committed
- **`config.example.yaml`** — template with all keys, no secrets
- Sensitive fields (`card_number`, `cvv`, `api_key`) masked in all logs and dashboard UI
- All config via YAML — zero hardcoded values
- Schema validation on startup — fail fast on invalid config
- Hot-reload: `POST /api/config/reload` — validates, applies if valid, logs error if not

### Environment Variable Overrides

| Variable | Purpose |
|----------|---------|
| `POKEDROP_2CAPTCHA_KEY` | 2Captcha API key |
| `POKEDROP_DISCORD_URL` | Discord webhook URL |
| `POKEDROP_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `POKEDROP_TELEGRAM_CHAT_ID` | Telegram chat ID |

---

## Anti-Detection (Evasion)

- **UA rotation**: Pool of ≥50 real UA strings, rotated per request
- **Fingerprint randomization**: Viewport, timezone, locale, hardware concurrency
- **Respect robots.txt**: Do not crawl disallowed paths
- **Proxy rotation**: v2.0+ (residential proxy pool)
- **IP rate limit handling**: Retry with backoff

---

## Functional Requirements Priority

### P0 (MVP — Phase 1)

**Monitoring:** Playwright headless, OOS→IS detection (SKU + keyword), configurable interval (500ms default, 100ms min), jitter ±20%, session pre-warming, cookie persistence, graceful shutdown

**Cart + Checkout:** Add via API or UI fallback, cart verification, 1-Click when available, auto-fill forms, human-like delay (300ms ±50ms), retry up to 2 times, payment decline retry (2s delay, then abort)

**CAPTCHA:** Detect reCAPTCHA/hCaptcha/Turnstile, 2Captcha API with exponential backoff (max 120s), token injection, smart routing (default: Turnstile→auto, others→manual)

**Evasion:** UA rotation, fingerprint randomization, respect robots.txt, rate limit backoff

**Notifications:** Discord + Telegram webhooks, 3 retries with exponential backoff, ISO-8601 timestamps, all 15 events

**Dashboard:** Login, status view, start/stop with confirmation, real-time event log (SSE), dry-run panel, settings form, validate config, CAPTCHA panel, drop window calendar, multi-account panel, viewer role, restart daemon, setup wizard

**Config:** All YAML, schema validation, sensitive field masking, multiple items, per-retailer overrides

---

## Business Rules

| Rule | Value |
|------|-------|
| One active cart per retailer | One item per retailer at a time |
| Pre-warm required | At least `prewarm_minutes` before drop window |
| Checkout retries | Max 2 per item per session |
| CAPTCHA timeout | 120s — abort and alert |
| Payment retry | Wait 2s, retry once; second decline → abort |
| Per-checkout-step timeout | 30s; overall checkout timeout 60s |
| Pre-warmed session expiry | 2 hours |
| Cart quantity control | `max_cart_quantity` per drop window, retailer limit takes precedence |

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Network drops mid-checkout | Retry from cart (re-verify item still there) |
| Page structure changes | Log error, fire SESSION_EXPIRED, alert operator |
| Payment declines on retry | Fire PAYMENT_DECLINED, no further retries |
| OOS during cart wait | Fire CHECKOUT_FAILED, retry if retries remain |
| CAPTCHA timeout | Fire CAPTCHA_REQUIRED → alert, skip or retry |
| Queue > 60s | Fire QUEUE_DETECTED → QUEUE_CLEARED when through |
| Session expires mid-checkout | Re-authenticate, restart from cart |
| Multiple operators same item | First-to-lock wins; others get SESSION_EXPIRED |
| Config modified while running | Hot-reload not supported; restart required |
| Disk full | Log to stdout only, emit warning, continue |

---

## Logging

- **Format:** Structured JSON to `logs/poke_drop.log`; plain text via `RotatingFileHandler` (10MB max, 5 backups)
- **DEBUG**: Form field values (sensitive fields masked), UA selected, jitter value
- **INFO**: Lifecycle events (MONITOR_STARTED, STOCK_DETECTED, CART_ADDED, CHECKOUT_START, CHECKOUT_SUCCESS, CHECKOUT_FAILED)
- **WARNING**: Retriable errors (network timeout, rate limit)
- **ERROR**: Fatal errors (config invalid, checkout failed after retries)

---

## Git Workflow

**Always use feature branches. Never commit directly to `dev` or `main`.**

1. `git checkout dev && git pull origin dev`
2. `git checkout -b <type>/<task-id>-<short-description>`
   - `feature/<task-id>-<description>`
   - `fix/<task-id>-<description>`
   - `chore/<description>`
   - `refactor/<description>`
   - `test/<task-id>-<description>`
3. Commit: `feat(MON-5): add jitter to check interval ±20%`
4. `git push origin <branch-name>`
5. Open PR against `dev`
6. After merge: `git branch -d <branch-name>`

Format: `<type>(<scope>): <description>` — Conventional Commits with optional task ID scope.

---

## Testing

| Type | Target | Framework |
|------|--------|-----------|
| Unit tests | Core logic: config, jitter, UA rotation, state machine | pytest |
| Retailer adapter tests | Mocked responses, each adapter method | pytest + responses |
| Integration tests | End-to-end dry-run against live pages | pytest (`--run-integration` only) |
| CAPTCHA tests | Mock 2Captcha, verify token injection | pytest |
| Evasion tests | Fingerprint randomization, UA uniqueness | pytest |
| Config validation tests | Valid/invalid configs, error messages | pytest |
| API route tests | Dashboard endpoints | FastAPI TestClient |
| Auth tests | Login success/fail, session expiry, role enforcement | pytest |

---

## Phase Roadmap

| Phase | Focus | Retailers | Key Features |
|-------|-------|-----------|--------------|
| v1.0 | Target MVP | Target only | Core monitoring, checkout, Discord webhook, UA rotation, jitter, web dashboard |
| v1.1–v1.2 | Walmart + Evasion | +Walmart, +BestBuy | Full adapters, fingerprint randomization, queue handling, Telegram |
| v2.0 | Production Hardening | All three | Proxy rotation, 2Captcha (all types), multi-account, crash recovery, health endpoint |
| v4.0 | Current (this PRD) | All three + extensible | Full feature parity, operational tooling, social listening, drop countdown |

---

## Key Rules

- **Never commit `config.yaml`** — contains secrets. Only `config.example.yaml` goes in git.
- **Never log sensitive fields** (`card_number`, `cvv`, `api_key`) — mask them at DEBUG level.
- **Never use `time.sleep`** — use `asyncio.sleep` with jitter from `src/bot/evasion/jitter.py`.
- **Never use `requests`** — use `httpx.AsyncClient`.
- **Never use Selenium** — use `playwright.async_api`.
- **Never hardcode UA strings** — use `src/bot/evasion/user_agents.py` rotation.
- **Never commit secrets** — use environment variables.
- **Preserve existing code patterns** — match style, naming, architecture.
- **If unsure, explain first** — describe the error and proposed fix before applying.
- **Don't suppress errors** — handle or re-raise.
- **Run tests before committing** — don't push broken code.
- **One logical change per commit** — atomic, easy to revert.
- **Crash recovery must prevent duplicate orders** — persist state to disk; on restart, check if item was already ordered.
- **All 15 webhook events must fire** in correct sequence.
- **Dashboard is localhost-only** — no external network exposure.
