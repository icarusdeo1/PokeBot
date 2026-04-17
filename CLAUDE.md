# CLAUDE.md — PokeDrop Bot

## Project Overview

**PokeDrop Bot** is a high-speed auto-checkout automation tool for Pokemon merchandise. It monitors retailer pages (Target, Walmart, Best Buy) for restocks and completes purchases within milliseconds of stock availability.

The bot is a single local Python process. No custom backend server. All configuration is via YAML. Phase 1 covers Target MVP; Walmart and Best Buy are Phase 2.

**Source of truth:** `PokeBot_PRD.md` — all product direction, requirements, and acceptance criteria live there.

## Role

You are an expert Python automation engineer for the PokeDrop Bot project. You help build, debug, test, and maintain a Python-based auto-checkout system using Playwright, httpx, and asyncio. You understand the full architecture — from the retailer adapter layer through the checkout state machine to webhook notifications — and you follow the conventions in this file.

## Tech Stack

| Component | Choice | Version | Notes |
|-----------|--------|---------|-------|
| Language | Python | 3.11+ | Async ecosystem |
| HTTP Client | httpx | ≥0.27 | Async, HTTP/2, connection pooling |
| Browser Automation | Playwright | ≥1.40 | Headless, anti-detect, cross-browser |
| CAPTCHA Solving | 2Captcha API | — | reCAPTCHA, hCaptcha, Cloudflare Turnstile |
| Config | YAML + PyYAML | ≥6.0 | Human-readable, no compilation |
| CLI | argparse | stdlib | Zero dependencies |
| Notifications | aiohttp | ≥3.9 | Async webhook delivery |
| Testing | pytest | ≥8.0 | Unit and integration coverage |
| Type Checking | mypy | ≥1.8 | Optional strict mode |
| Logging | stdlib logging | — | RotatingFileHandler, structured JSON to stdout |

### What We Do NOT Use

- **Selenium** — Playwright is the sole browser automation library. No Selenium.
- **requests** — httpx is the HTTP client (async required).
- **threading / multiprocessing** — use asyncio for all concurrent operations.
- **Celery / Redis** — no external task queue in v1-v2 (coordination via file lock).
- **Firebase / Supabase** — no backend database. Local SQLite only if needed for state.
- **Hardcoded delays** — use `jitter.py` utilities for all timing randomization.

## Project Structure

```
poke-drop-bot/
├── config.yaml                  # Runtime config (NOT committed)
├── config.example.yaml          # Template with all keys, no secrets
├── requirements.txt             # Pinned dependencies
├── pyproject.toml               # Package metadata
├── README.md                    # Setup and usage guide
├── src/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point (argparse)
│   ├── config.py                # Config loading + validation
│   ├── logger.py                # Structured logging setup
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── stock_monitor.py     # Core monitoring state machine
│   │   └── retailers/
│   │       ├── __init__.py
│   │       ├── base.py          # Abstract RetailerAdapter (ABC)
│   │       ├── target.py        # Target.com implementation
│   │       ├── walmart.py       # Walmart.com implementation
│   │       └── bestbuy.py       # BestBuy.com implementation
│   ├── checkout/
│   │   ├── __init__.py
│   │   ├── cart_manager.py      # Cart operations (add, verify, clear)
│   │   ├── checkout_flow.py     # Full checkout pipeline
│   │   ├── payment.py           # Payment form handling
│   │   ├── shipping.py          # Shipping form handling
│   │   └── captcha.py           # 2Captcha integration
│   ├── evasion/
│   │   ├── __init__.py
│   │   ├── user_agents.py       # UA pool and rotation
│   │   ├── fingerprint.py       # Browser fingerprint randomization
│   │   ├── jitter.py            # Timing randomization utilities
│   │   └── proxy.py             # Proxy rotation (v2.0+)
│   ├── notifications/
│   │   ├── __init__.py
│   │   ├── webhook.py           # Generic webhook sender
│   │   ├── discord.py           # Discord-specific adapter
│   │   └── telegram.py          # Telegram-specific adapter
│   └── session/
│       ├── __init__.py
│       └── prewarmer.py         # Session pre-warming (cookie/cache)
└── tests/
    ├── conftest.py              # Pytest fixtures
    ├── test_monitor.py
    ├── test_checkout.py
    ├── test_evasion.py
    ├── test_config.py
    └── test_notifications.py
```

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

## Architecture Layers

```
CLI (main.py / argparse)
  │
  ▼ reads and validates
Config (config.py / config.yaml)
  │
  ▼
StockMonitor (stock_monitor.py) — state machine loop
  │
  ├──► RetailerAdapter subclasses (target.py, walmart.py, bestbuy.py)
  ├──► CartManager (cart_manager.py)
  ├──► CheckoutFlow (checkout_flow.py → payment.py, shipping.py, captcha.py)
  ├──► Evasion (user_agents.py, fingerprint.py, jitter.py, proxy.py)
  └──► Notifications (webhook.py → discord.py, telegram.py)
```

### Layer Rules

- **`src/main.py`** is the sole CLI entry point. All user-facing commands go through argparse.
- **`src/config.py`** loads and validates `config.yaml`. All config access goes through this module — no direct YAML reads in other modules.
- **`src/monitor/stock_monitor.py`** contains the state machine. It coordinates adapters, cart, and checkout — never implements retailer-specific logic.
- **Retailer adapters** (`src/monitor/retailers/`) implement retailer-specific page interactions, login flows, and API calls. One class per retailer.
- **`src/checkout/`** contains the checkout pipeline — cart management, form filling, payment, shipping, CAPTCHA. Retailer-agnostic.
- **`src/evasion/`** contains anti-detection utilities: UA rotation, fingerprint randomization, jitter, proxy rotation.
- **`src/notifications/`** contains webhook delivery. All network calls for notifications go through this layer.
- **`src/session/`** contains pre-warming logic — cookie management, session state, auth token refresh.
- All modules use `async/await`. No callback patterns, no `.then()` chains. No `threading` or `multiprocessing`.

## Data Models

All defined as Python `dataclass` in the PRD (Section 8). Import from their defined modules — do not redefine.

```python
# Core entities (from src/monitor/retailers/base.py or defined inline)
@dataclass
class MonitoredItem:
    id: str
    name: str
    retailers: list[str]
    skus: list[str]
    keywords: list[str]
    enabled: bool = True

@dataclass
class RetailerAdapter(ABC):
    name: str                              # "target" | "walmart" | "bestbuy"
    base_url: str
    enabled: bool
    check_interval_ms: int
    prewarm_minutes: int
    requires_login: bool
    has_queue: bool

@dataclass
class CheckoutConfig:
    shipping: ShippingInfo
    payment: PaymentInfo
    use_1click_if_available: bool
    human_delay_ms: int

@dataclass
class ShippingInfo:
    name: str
    address1: str
    address2: str = ""
    city: str
    state: str
    zip: str
    phone: str
    email: str = ""

@dataclass
class PaymentInfo:
    card_number: str
    exp_month: str
    exp_year: str
    cvv: str
    card_type: str = ""

@dataclass
class WebhookEvent:
    event: str                             # STOCK_DETECTED, CART_ADDED, etc.
    item: str
    retailer: str
    timestamp: str                         # ISO-8601 UTC
    order_id: str = ""
    error: str = ""
    attempt: int = 1

@dataclass
class SessionState:
    cookies: dict
    auth_token: str = ""
    cart_token: str = ""
    prewarmed_at: datetime = None
    is_valid: bool = True
```

## Webhook Event Catalog

All 12 events must fire in sequence. See PRD Section 8.2 for the full table.

| Event | Trigger |
|-------|---------|
| `MONITOR_STARTED` | Bot starts monitoring |
| `STOCK_DETECTED` | OOS → IS transition |
| `CART_ADDED` | Item confirmed in cart |
| `CHECKOUT_STARTED` | Checkout flow initiated |
| `CHECKOUT_SUCCESS` | Order confirmed |
| `CHECKOUT_FAILED` | Checkout rejected |
| `CAPTCHA_REQUIRED` | CAPTCHA challenge detected |
| `CAPTCHA_SOLVED` | CAPTCHA solved |
| `QUEUE_DETECTED` | Retailer queue entered |
| `QUEUE_CLEARED` | Queue position released |
| `SESSION_EXPIRED` | Auth/session invalidated |
| `PAYMENT_DECLINED` | Payment rejected |

## CLI Commands

| Command | Description |
|---------|-------------|
| `pokeDrop start [--item <name>] [--retailer <name>]` | Start monitoring (all items if none specified) |
| `pokeDrop stop` | Stop monitoring gracefully |
| `pokeDrop status` | Show current monitoring state, active items, session health |
| `pokeDrop test-config` | Validate config.yaml and report errors |
| `pokeDrop dry-run [--item <name>] [--retailer <name>]` | Run checkout without placing order |
| `pokeDrop prewarm [--retailer <name>]` | Pre-warm session without starting checkout |

## Functional Requirements Priority

### P0 (MVP Must-Have)

**Stock Monitoring (MON-1 through MON-8, MON-11):**
- Playwright headless browser monitoring
- OOS → IS detection via SKU and keyword
- Configurable check interval (default 500ms, min 100ms)
- Jitter ±20% on check interval
- Session pre-warming before drop window
- Cookie persistence across checks
- Graceful shutdown

**Cart + Checkout (CART-1 through CART-4, CART-6, CO-1 through CO-10):**
- Add to cart via API (preferred) or UI fallback
- Cart verification before checkout
- 1-Click checkout when available
- Auto-fill shipping and payment forms
- Randomized human-like delay between steps (300ms ±50ms)
- Retry failed checkout up to 2 times (configurable)
- Handle payment decline (retry once after 2s delay)
- Handle post-cart OOS failures

**CAPTCHA (CAP-1 through CAP-5):**
- Detect reCAPTCHA, hCaptcha, Turnstile
- Submit to 2Captcha API with exponential backoff (max 120s)
- Inject solution token and resubmit
- Log solve time in milliseconds

**Anti-Detection (EV-1 through EV-3, EV-5):**
- UA rotation from pool of ≥50 real UA strings
- Browser fingerprint randomization (viewport, timezone, locale, hardware concurrency)
- Respect retailer robots.txt
- Detect and handle IP rate limits with backoff

**Notifications (NOT-1 through NOT-4, NOT-6):**
- Discord webhook with embed formatting
- Telegram webhook with formatted message
- Retry failed delivery up to 3 times with exponential backoff
- ISO-8601 timestamps on all payloads
- All 12 lifecycle events fired

**Config (CFG-1, CFG-2, CFG-4, CFG-5, CFG-6):**
- All config via YAML — zero hardcoded values
- Schema validation on startup (fail fast on missing/invalid fields)
- Sensitive fields never logged or printed
- Multiple items and per-retailer overrides supported

### P1 (Phase 2)

- Queue/waiting room handling
- Session re-authentication on expiration
- Telegram webhook
- Browser fingerprint randomization
- Per-retailer pre-warming
- Cart clearing on failure

## Non-Functional Requirements

### Performance Targets

| Metric | Target |
|--------|--------|
| Stock detection latency | < 1s (Target/Walmart), < 500ms (Best Buy) |
| Checkout completion (Target) | < 10s |
| Checkout completion (Walmart) | < 15s |
| Checkout completion (Best Buy) | < 5s |
| Memory footprint (idle, pre-warmed) | < 512 MB |
| Browser instances per retailer | 1 (shared session) |

### Reliability Targets

| Metric | Target |
|--------|--------|
| Uptime during monitoring | 99% (network failures excluded) |
| Checkout success rate (pre-warmed) | ≥ 85% |
| Webhook delivery reliability | ≥ 99% after retries |
| Crash recovery | Restart from last known good state; no re-purchase |

### Security Requirements

| Requirement | Notes |
|-------------|-------|
| `config.yaml` permissions | `chmod 600` — owner read/write only |
| CVV never stored post-checkout | Cleared after use |
| API keys from environment variables | `POKEDROP_2CAPTCHA_KEY`, etc. |
| All webhook URLs must be HTTPS | Validation enforced |
| No external network calls except retailers, 2Captcha, notification endpoints | Hard constraint |
| Browser sandboxed | No local filesystem access beyond config/logs |

## Configuration Rules

- **`config.yaml`** is the runtime config. Never commit it.
- **`config.example.yaml`** is the template with all keys and placeholder values, no secrets.
- All secrets (card_number, cvv, API keys) come from environment variables in production.
- Config schema is validated in `src/config.py`. Startup fails on missing required fields.
- Sensitive fields are masked in all log output (DEBUG level logs must mask `card_number`, `cvv`, `api_key`).

### Environment Variable Overrides

| Variable | Purpose |
|----------|---------|
| `POKEDROP_2CAPTCHA_KEY` | 2Captcha API key |
| `POKEDROP_DISCORD_URL` | Discord webhook URL |
| `POKEDROP_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `POKEDROP_TELEGRAM_CHAT_ID` | Telegram chat ID |

## Testing Requirements

| Test Type | Coverage Target | Framework |
|-----------|----------------|-----------|
| Unit tests | Core logic: config validation, jitter, UA rotation, state machine | pytest |
| Retailer adapter unit tests | Mocked responses, each adapter method | pytest + responses library |
| Integration tests | End-to-end dry-run against live retailer pages | pytest (opt-in, tagged `integration`) |
| CAPTCHA integration tests | Mock 2Captcha responses, verify token injection | pytest |
| Evasion tests | Verify fingerprint randomization, UA uniqueness | pytest |
| Config validation tests | Valid and invalid configs; verify error messages | pytest |

**Integration tests run only with `pytest --run-integration`.** They interact with live retailer pages and may place orders.

## Logging

- **Format:** Structured JSON to stdout; plain text to file via `RotatingFileHandler` (10MB max, 5 backups).
- **Levels:**
  - `DEBUG` — form field values (sensitive fields masked), UA selected, jitter value
  - `INFO` — lifecycle events (MONITOR_STARTED, STOCK_DETECTED, CART_ADDED, CHECKOUT_START, CHECKOUT_SUCCESS, CHECKOUT_FAILED)
  - `WARNING` — retriable errors (network timeout, rate limit hit)
  - `ERROR` — fatal errors (config invalid, checkout step failed after retries)
- **Key events to log:** MONITOR_START, STOCK_DETECTED, CART_ADDED, CHECKOUT_START, CHECKOUT_SUCCESS, CHECKOUT_FAILED, ERROR
- **Health check:** `GET /health` returns `200 OK` + `{"status": "ok", "active_items": N}`

## Business Rules

| Rule | Value |
|------|-------|
| One active cart per retailer | Only one item checked out per retailer at a time |
| Pre-warm required | At least `prewarm_minutes` before drop window |
| Checkout retries | Max 2 per item per monitoring session |
| CAPTCHA timeout | 120s — abort and alert if not solved |
| Payment retry | Wait 2s, retry once; second decline → abort |
| Per-checkout-step timeout | 30s; overall checkout timeout 60s |
| Pre-warmed session expiry | 2 hours |

## Edge Case Handling

| Scenario | Handling |
|----------|----------|
| Network drops mid-checkout | Retry checkout from cart (re-verify item still in cart) |
| Retailer page structure changes | Log error, fire SESSION_EXPIRED, alert operator, do not silently continue |
| Payment declines on retry | Fire PAYMENT_DECLINED webhook, do not retry further |
| Item goes OOS during cart wait | Fire CHECKOUT_FAILED with stage="stock_verify", retry if retries remaining |
| CAPTCHA solve times out | Fire CAPTCHA_REQUIRED → alert, skip or retry on next stock detection |
| Queue blocks > 60s | Fire QUEUE_DETECTED → QUEUE_CLEARED when through, continue |
| Session cookie expires mid-checkout | Re-authenticate, restart checkout from cart |
| Multiple operators start same item | First-to-acquire lock wins; others receive SESSION_EXPIRED |
| Config modified while running | Hot-reload not supported; operator must restart |
| Disk full | Log to stdout only, emit warning, continue operation |

## Workflow

### 1. Before Writing Code

- Understand the **requirement** — trace it to the PRD section (e.g., MON-5 for check interval jitter) or task ID.
- Check the **architecture layer** the change belongs to:
  - `src/monitor/` — state machine and retailer adapters
  - `src/checkout/` — checkout pipeline
  - `src/evasion/` — anti-detection utilities
  - `src/notifications/` — webhook delivery
  - `src/session/` — pre-warming and session state
  - `src/config.py` — configuration loading
- Verify which **modules** and **functions** are involved.
- If the change touches retailer-specific page structure, the change belongs in the retailer adapter — not in the generic monitor or checkout flow.
- If the change adds a new webhook event, add it to the catalog in Section 8.2 of this file AND the PRD.

### 2. Write the Code

- **Follow the architecture rules** above. No shortcuts.
- **Use async/await** for all I/O operations. No blocking calls (`time.sleep`, `requests`).
- **Use Playwright** for all browser automation. No Selenium.
- **Use httpx** for all HTTP requests. No `requests`.
- **Use dataclasses** for all data models. No dicts as structured data.
- **Use jitter utilities** from `src/evasion/jitter.py` for all timing — no raw `asyncio.sleep`.
- **Use UA rotation** from `src/evasion/user_agents.py` on every request — never hardcode a User-Agent.
- **Mask sensitive fields** in all log output — card_number, cvv, api_key.
- **Write tests alongside the feature** — not after. Unit tests for pure logic, integration tests for flows.
- **All user-facing output** (CLI, webhooks) should use the event names from the Webhook Event Catalog.

### 3. Branch, Commit, and Push

**Always use feature branches. Never commit directly to `dev` or `main`.**

1. Verify you are on `dev` and it is up to date: `git checkout dev && git pull origin dev`
2. Create a feature branch from `dev`: `git checkout -b <type>/<task-id>-<short-description>`
   - `feature/<task-id>-<description>` — new features
   - `fix/<task-id>-<description>` — bug fixes
   - `chore/<description>` — maintenance
   - `refactor/<description>` — code refactors
   - `test/<task-id>-<description>` — adding tests
3. Make changes and commit with a clear message:
   ```
   feat(MON-5): add jitter to check interval ±20%
   ```
   Format: `<type>(<scope>): <concise description>` — Conventional Commits with optional task ID scope.
4. Push: `git push origin <branch-name>`
5. Open a PR against `dev`.
6. After merge, clean up the local branch: `git branch -d <branch-name>`

### 4. Report

After completing a task, give a brief summary:
- What was built or fixed and why
- Which modules were touched
- Whether tests pass
- Any remaining issues or TODOs

## Rules

- **Never commit `config.yaml`** — it contains secrets. Only `config.example.yaml` goes in git.
- **Never log sensitive fields** (`card_number`, `cvv`, `api_key`) — mask them at DEBUG level.
- **Never use `time.sleep`** — use `asyncio.sleep` with jitter from `src/evasion/jitter.py`.
- **Never use `requests`** — use `httpx.AsyncClient`.
- **Never use Selenium** — use `playwright.async_api`.
- **Never hardcode UA strings** — use `src/evasion/user_agents.py` rotation.
- **Never commit secrets or API keys** — use environment variables or EAS Secrets.
- **Preserve existing code patterns** — match the style, naming conventions, and architecture already in use.
- **If unsure about a fix**, explain the error and your proposed fix before applying it.
- **Don't suppress errors** with empty `except:` — actually handle or re-raise.
- **Run tests before committing** — don't push code that breaks existing tests.
- **One logical change per commit** — keep changes atomic and easy to revert.
- **Config validation must fail fast** — if `config.yaml` is invalid, the bot must exit with a clear error, not continue with defaults.
- **All 12 webhook events must fire** in the correct sequence for every checkout attempt.
- **Crash recovery must prevent duplicate orders** — persist state to disk; on restart, check whether item was already ordered.

## CI/CD Pipeline

| Trigger | Pipeline | What It Does |
|---------|----------|-------------|
| PR opened/updated | `ci-pr` | mypy type-check → pytest unit tests → coverage gate (≥80% for `src/`) |
| Merge to `dev` | `ci-dev` | Full test suite → EAS Build (preview) → Internal distribution |
| Merge to `main` | `ci-main` | Full test suite → EAS Build (production) |
| Weekly (scheduled) | `ci-integration` | Run integration tests against live retailer pages (opt-in, `--run-integration`) |

**Branch strategy:** `main` (stable releases) ← `dev` (integration, preview builds) ← feature branches.

## Glossary

| Term | Definition |
|------|-----------|
| **OOS → IS** | Out-of-stock to in-stock state transition |
| **1-Click** | Retailer express checkout using saved shipping/payment |
| **Pre-warming** | Loading retailer session (cookies, auth tokens) before drop window |
| **Queue/Waiting Room** | Retailer-implemented rate limiter holding users before checkout |
| **Turnstile** | Cloudflare's CAPTCHA replacement (used by Best Buy) |
| **Stealth Mode** | Playwright configuration that hides automation signals |
| **Dry-run** | Full checkout flow without placing order; validates config and flow |
| **Adapter** | Retailer-specific implementation of the `RetailerAdapter` base class |
| **Jitter** | Random variance added to timing to appear more human-like |

## Phase Roadmap

| Phase | Focus | Retailers | Key Features |
|-------|-------|-----------|--------------|
| v1.0 | Target MVP | Target only | Core monitoring, checkout, Discord webhook, UA rotation, jitter |
| v1.1–v1.2 | Walmart + Evasion | +Walmart, +BestBuy | Full adapters, fingerprint randomization, queue handling, Telegram |
| v2.0 | Production Hardening | All three | Proxy rotation, 2Captcha (all types), multi-account, crash recovery, health endpoint |
| v3.0 | Current (this PRD) | All three + extensible | Full feature parity, operational tooling |

Exit criteria for each phase are defined in PRD Section 14.
