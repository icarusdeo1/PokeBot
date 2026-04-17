# PokeDrop Bot — Auto-Checkout System

**Version:** 4.0  
**Date:** 2026-04-17  
**Status:** Production-Ready Draft  
**Owner:** J (bullmoonfinance)  
**Interface:** Web Dashboard (localhost-first)

---

## 1. Overview

| Field | Description |
|-------|-------------|
| **Project Name** | PokeDrop Bot |
| **Type** | High-speed auto-checkout automation tool |
| **Core Functionality** | Monitor retailer pages for Pokemon merchandise restocks and automatically complete purchase within milliseconds of stock availability |
| **Target Users** | Non-technical resellers and collectors who need to secure limited Pokemon items before they sell out; operator interacts via a browser-based dashboard, no CLI knowledge required |
| **Execution Environment** | Headless daemon running in the background on the operator's machine; web dashboard accessible at `http://localhost:8080` via any browser on the same machine |
| **Architecture** | Two-process model: (1) Bot daemon — handles all monitoring, cart, checkout logic; (2) Dashboard server — serves the operator interface and exposes a local REST API consumed by the dashboard UI |

---

## 2. Problem Statement

Pokemon merchandise drops (special edition cards, plush toys, collectibles) sell out in seconds. Manual browsing and checkout is too slow. Competitive buyers use multiple devices and bot scripts to gain an unfair advantage.

PokeDrop Bot automates the entire purchase flow — from stock detection to checkout confirmation — at machine speed, restoring parity against automated competitors. The operator interacts with the bot entirely through a web dashboard — no terminal, no CLI, no technical knowledge required.

---

## 3. Product Goals

| Goal | Metric | Target |
|------|--------|--------|
| Stock detection latency | Time from item going live to bot detecting in-stock | < 1 second (Target/Walmart), < 500ms (Best Buy) |
| Checkout completion | Time from stock detection to order confirmation | < 10 seconds (Target), < 15 seconds (Walmart), < 5 seconds (Best Buy) |
| Success rate | Orders placed / checkout attempts initiated | ≥ 85% on pre-warmed sessions |
| Operational transparency | All lifecycle events visible in real-time in the dashboard event log | 100% of defined events |
| Dashboard load time | Time from browser request to page rendered | < 2 seconds (localhost) |
| Dashboard real-time latency | Time from event firing in daemon to appearing in dashboard | < 500ms via SSE |

---

## 4. Non-Goals

- This tool does **not** bypass paid CAPTCHA services — it integrates with them only.
- This tool does **not** hack, exploit, or penetration-test retailer systems.
- This tool does **not** guarantee purchase. Retailer-side failures (payment declines, session invalidation, anti-bot blocks) are outside bot control.
- This tool is **not** a scalping engine. Users are responsible for complying with retailer Terms of Service and applicable law.
- This tool does **not** require the operator to use a terminal or command line. All interaction is through the web dashboard.

---

## 5. User Roles

| Role | Permissions |
|------|-------------|
| **Operator** | Full control: start/stop monitoring, configure items and retailers, view logs, trigger dry-run — via dashboard login |
| **Viewer** | Read-only dashboard access: can view status, session health, event history, and configuration summary — but cannot start/stop monitoring or change any settings |
| **Future: API User** | Remote control via REST API (v2.1+) — not in scope for v1/v2 |

**Access Control:** Dashboard requires PIN/password authentication. Operator PIN stored hashed (argon2 or bcrypt) in `auth.db` (SQLite). No endpoint is accessible without a valid session cookie. Viewer sessions are read-only — no start, stop, dry-run, or config change operations permitted.

---

## 6. Tech Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| **Bot daemon** | Python | 3.11+ | Async ecosystem, Playwright bindings |
| **HTTP Client** | httpx | ≥0.27 | Async, HTTP/2, connection pooling |
| **Browser Automation** | Playwright | ≥1.40 | Headless, anti-detect, cross-browser |
| **CAPTCHA Solving** | 2Captcha API + Manual Mode | — | 2Captcha for auto-solve; operator-paused manual mode; smart routing (Turnstile→auto, reCAPTCHA/hCaptcha→manual) |
| **Config** | YAML + PyYAML | ≥6.0 | Human-readable, operator-editable via dashboard form |
| **Web Framework** | FastAPI | ≥0.110 | Async, fast, serves dashboard + API on localhost |
| **ASGI Server** | Uvicorn | ≥0.27 | Runs the FastAPI dashboard server |
| **Frontend** | Vanilla HTML + CSS + JS | — | Single-page dashboard; no build step, no heavy SPA framework |
| **Local Database** | SQLite | built-in | Stores bot state (`state.db`) and auth sessions (`auth.db`); WAL mode |
| **Password Hashing** | argon2 or bcrypt | ≥0.3 | Dashboard PIN/password hashing |
| **Real-time Updates** | Server-Sent Events (SSE) | built-in (FastAPI) | Pushes live events from daemon to dashboard without polling |
| **Notifications** | aiohttp | ≥3.9 | Async webhook delivery to Discord/Telegram |
| **Testing** | pytest + Playwright | ≥8.0 | Unit, integration, and API route tests |
| **Type Checking** | mypy | ≥1.8 | Optional strict mode |

**What is NOT used (removed from previous version):**
- `argparse` — no CLI commands
- `Rich` + `Textual` — no TUI; replaced by web dashboard
- Any web server requiring external hosting (dashboard is localhost-only)

---

## 7. Architecture

### 7.1 Directory Structure

```
poke-drop-bot/
├── config.yaml                  # Retailer/item configuration (operator edits via dashboard)
├── config.example.yaml          # Template with all keys, no secrets
├── auth.db                      # SQLite: operator credentials, sessions (not committed)
├── state.db                     # SQLite: bot state, event history (not committed)
├── requirements.txt             # Pinned dependencies
├── pyproject.toml               # Package metadata
├── README.md                    # Setup and usage guide
├── src/
│   ├── __init__.py
│   ├── daemon.py                # Bot daemon entry point (runs silently in background)
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── server.py            # FastAPI app — serves dashboard + exposes local API
│   │   ├── auth.py              # Login, session management, PIN/password hashing
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── status.py        # GET /api/status — bot state from state.db
│   │   │   ├── config.py        # GET/PATCH /api/config — retailer/item config
│   │   │   ├── events.py        # GET /api/events/stream — SSE real-time event stream
│   │   │   ├── monitor.py       # POST /api/monitor/start, /stop
│   │   │   ├── dryrun.py        # POST /api/dryrun — triggers dry-run checkout
│   │   │   └── health.py        # GET /health — daemon health check
│   │   └── templates/
│   │       └── index.html       # Dashboard frontend (single-page HTML/CSS/JS)
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── config.py            # Config loading + validation (from YAML)
│   │   ├── logger.py            # Structured logging → file + SSE stream
│   │   ├── monitor/
│   │   │   ├── __init__.py
│   │   │   ├── stock_monitor.py
│   │   │   └── retailers/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── target.py
│   │   │       ├── walmart.py
│   │   │       └── bestbuy.py
│   │   ├── checkout/
│   │   │   ├── __init__.py
│   │   │   ├── cart_manager.py
│   │   │   ├── checkout_flow.py
│   │   │   ├── payment.py
│   │   │   ├── shipping.py
│   │   │   └── captcha.py
│   │   ├── evasion/
│   │   │   ├── __init__.py
│   │   │   ├── user_agents.py
│   │   │   ├── fingerprint.py
│   │   │   ├── jitter.py
│   │   │   └── proxy.py
│   │   ├── notifications/
│   │   │   ├── __init__.py
│   │   │   ├── webhook.py
│   │   │   ├── discord.py
│   │   │   └── telegram.py
│   │   └── session/
│   │       ├── __init__.py
│   │       └── prewarmer.py
│   └── shared/
│       ├── __init__.py
│       ├── db.py                # SQLite state.db + auth.db helpers (WAL mode)
│       └── models.py            # Shared dataclasses
└── tests/
    ├── conftest.py
    ├── test_bot/                # Bot daemon unit tests
    ├── test_dashboard/          # API route tests (FastAPI TestClient)
    └── test_auth.py             # Auth: login success/fail, session expiry, role enforcement
```

**Two-process model:**
- `daemon.py` — runs as a background daemon; handles all bot logic (monitoring, cart, checkout, evasion); communicates with dashboard via SQLite state.db and SSE
- `dashboard/server.py` — FastAPI app; serves the dashboard frontend at `http://localhost:8080`; exposes `/api/*` endpoints consumed by the dashboard UI; reads/writes state.db to command the daemon

**Daemon ↔ Dashboard communication:**
- Bot writes state to `state.db`: active items, session health per retailer, last event timestamp, daemon uptime
- Bot emits real-time events via SSE stream at `GET /api/events/stream`
- Dashboard frontend consumes SSE and displays live event log
- Dashboard sends commands (start/stop/dry-run) by writing to `state.db` command queue table
- Daemon polls command queue or uses a file lock signal (no direct inter-process function calls)

### 7.2 Core State Machine

*(Unchanged — bot internal logic identical to v3.0)*

```
STANDBY ──[stock detected]──> STOCK_FOUND ──[cart added]──> CART_READY
  │                                  │                          │
  │                                  │                          ▼
  │                                  └────────[checkout done]──> CHECKOUT_COMPLETE
  │                                                               │
  │                                                               ▼
  └─────────────[failure/timeout]──────────────────────────────> CHECKOUT_FAILED
```

### 7.3 Data Flow

```
Operator opens browser ──> http://localhost:8080 ──> Dashboard login
                                                          │
                                           ┌──────────────┴──────────────┐
                                           │                              │
                                     [Operator actions]           [real-time state]
                                           │                              │
                                  dashboard/server.py          state.db (SQLite)
                                           │                              │
                                           │                    daemon.py (bot)
                                           │                              │
                                           │              ┌───────────────┼────────────────┐
                                           │         Stock Monitor    Checkout Flow    Session Manager
                                           │                              │                    │
                                           │                        Webhook events ──> Discord/Telegram
                                           │                              │
                                     Dashboard UI               Event written to state.db
                                     (live event log)                  │
                                     (session health)                 │
                                     (CAPTCHA panel)           SSE ──> Dashboard
```

**Operator never interacts directly with the daemon.** All actions go through the dashboard which reads from / writes to the shared SQLite database.

---

## 8. Data Models

### 8.1 Core Entities

```python
@dataclass
class MonitoredItem:
    id: str                              # UUID
    name: str                            # Display name
    retailers: list[str]                   # Retailer adapter names
    skus: list[str]                      # SKU identifiers
    keywords: list[str]                   # Keyword match strings
    enabled: bool = True

@dataclass
class RetailerAdapter(ABC):
    name: str                            # "target" | "walmart" | "bestbuy"
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
    email: str = ""                       # Optional; some retailers require it

@dataclass
class PaymentInfo:
    card_number: str                      # Stored as-is in config; production should use encrypted storage
    exp_month: str
    exp_year: str
    cvv: str
    card_type: str = ""                  # visa/mastercard/amex (auto-detected)

@dataclass
class WebhookEvent:
    event: str                            # STOCK_DETECTED, CART_ADDED, etc.
    item: str
    retailer: str
    timestamp: str                        # ISO-8601 UTC
    order_id: str = ""                    # Only on CHECKOUT_SUCCESS
    error: str = ""                       # Only on CHECKOUT_FAILED
    attempt: int = 1                      # Checkout attempt number

@dataclass
class SessionState:
    cookies: dict                         # Browser session cookies
    auth_token: str = ""
    cart_token: str = ""
    prewarmed_at: datetime = None
    is_valid: bool = True
```

### 8.2 Webhook Event Catalog

| Event | Trigger | Success Payload Fields | Failure Payload Fields |
|-------|---------|------------------------|-----------------------|
| `MONITOR_STARTED` | Bot starts monitoring an item | `item`, `retailers` | — |
| `STOCK_DETECTED` | Stock transitions OOS→IS | `item`, `retailer`, `url`, `sku` | — |
| `CART_ADDED` | Item confirmed in cart | `item`, `retailer`, `cart_url` | — |
| `CHECKOUT_STARTED` | Checkout flow initiated | `item`, `retailer`, `attempt` | — |
| `CHECKOUT_SUCCESS` | Order confirmed | `item`, `retailer`, `order_id`, `total` | — |
| `CHECKOUT_FAILED` | Checkout rejected | — | `item`, `retailer`, `error`, `attempt`, `stage` |
| `CAPTCHA_REQUIRED` | CAPTCHA challenge detected | `item`, `retailer`, `captcha_type` | — |
| `CAPTCHA_SOLVED` | CAPTCHA solved | `item`, `retailer`, `solve_time_ms` | — |
| `CAPTCHA_PENDING_MANUAL` | Bot paused for manual solve; operator required | `item`, `retailer`, `captcha_type`, `pause_url` | — |
| `CAPTCHA_MANUAL_RESOLVED` | Operator solved CAPTCHA; bot resuming | `item`, `retailer`, `solve_time_ms` | — |
| `CAPTCHA_MANUAL_TIMEOUT` | Operator did not solve within timeout; bot skipped or retried | — | `item`, `retailer`, `captcha_type`, `timeout_seconds` |
| `CAPTCHA_BUDGET_EXCEEDED` | Daily 2Captcha budget cap hit; auto-solves paused | — | `item`, `retailer`, `daily_spent_usd`, `budget_cap_usd` |
| `QUEUE_DETECTED` | Retailer queue/waiting room entered | `item`, `retailer`, `queue_url` | — |
| `QUEUE_CLEARED` | Queue position released | `item`, `retailer` | — |
| `SESSION_EXPIRED` | Auth/session invalidated | — | `item`, `retailer`, `reason` |
| `PAYMENT_DECLINED` | Payment rejected | — | `item`, `retailer`, `decline_code` |

---

## 9. Functional Requirements

### 9.1 Stock Monitoring

| ID | Requirement | Priority |
|----|-------------|----------|
| MON-1 | Monitor each configured retailer via headless Playwright browser | P0 |
| MON-2 | Detect OOS→IS state transitions on product pages | P0 |
| MON-3 | Support SKU-based detection (exact match against known SKUs) | P0 |
| MON-4 | Support keyword-based detection (page text search, fallback when SKU unavailable) | P0 |
| MON-5 | Configurable check interval per retailer (default: 500ms, min: 100ms) | P0 |
| MON-6 | Add randomized jitter ±N% to each check interval (configurable, default: 20%) | P0 |
| MON-7 | Pre-warm browser session N minutes before monitored drop window | P0 |
| MON-8 | Persist and reuse browser session cookies across checks | P0 |
| MON-9 | Detect retailer queue/waiting room redirects and handle them | P1 |
| MON-10 | Detect session expiration and re-authenticate automatically | P1 |
| MON-11 | Graceful shutdown: stop monitoring loop, close browser, persist state | P0 |

### 9.2 Cart Management

| ID | Requirement | Priority |
|----|-------------|----------|
| CART-1 | Add item to cart via retailer API (preferred) or UI automation (fallback) | P0 |
| CART-2 | Verify item is actually in cart before proceeding to checkout | P0 |
| CART-3 | Support 1-Click checkout when available (skip cart page) | P0 |
| CART-4 | Handle cart errors (item no longer available, quantity limit) | P0 |
| CART-5 | Clear cart between checkout attempts on failure | P1 |
| CART-6 | Prevent duplicate cart adds for the same SKU within a session | P0 |

### 9.3 Checkout Flow

| ID | Requirement | Priority |
|----|-------------|----------|
| CO-1 | Auto-fill shipping form fields from config | P0 |
| CO-2 | Auto-fill payment form fields from config | P0 |
| CO-3 | Apply billing address same as shipping by default | P0 |
| CO-4 | Handle order review step (acknowledge terms, if present) | P0 |
| CO-5 | Submit order and capture confirmation number | P0 |
| CO-6 | Handle payment decline (retry once with delay) | P0 |
| CO-7 | Handle "item no longer available" post-cart failure | P0 |
| CO-8 | Inject randomized human-like delay between checkout steps (default: 300ms ±50ms) | P0 |
| CO-9 | Retry failed checkout up to N times (configurable, default: 2) | P0 |
| CO-10 | Log all form field values at DEBUG level (masking sensitive fields) | P0 |

### 9.4 CAPTCHA Handling

| ID | Requirement | Priority |
|----|-------------|----------|
| CAP-1 | Detect reCAPTCHA, hCaptcha, and Cloudflare Turnstile challenges | P0 |
| CAP-2 | Submit challenge to 2Captcha API with site key and page URL | P0 |
| CAP-3 | Poll for CAPTCHA solution with exponential backoff (max 120s timeout) | P0 |
| CAP-4 | Inject solution token into page and resubmit form | P0 |
| CAP-5 | Log CAPTCHA solve time in milliseconds | P0 |
| CAP-6 | Handle CAPTCHA solve failure (alert via webhook, skip or retry) | P1 |
| CAP-7 | Budget tracking: log cumulative daily CAPTCHA spend | P2 |
| CAP-8 | **Manual CAPTCHA Mode**: when enabled, bot pauses on CAPTCHA challenge and fires `CAPTCHA_PENDING_MANUAL` webhook; waits for operator to solve in browser; resumes on completion or timeout | P0 |
| CAP-9 | **Smart CAPTCHA Routing** (when `captcha.mode = smart`): Turnstile challenges auto-solved via 2Captcha (low cost, high pass rate); reCAPTCHA/hCaptcha routed to manual mode or auto-solve with budget cap | P0 |

#### 9.4.1 CAPTCHA Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| `auto` | All CAPTCHA types sent to 2Captcha; operator pays per solve | Operator wants fully autonomous; budget available |
| `manual` | Bot pauses on any CAPTCHA; fires `CAPTCHA_PENDING_MANUAL` to Discord/Telegram; waits up to `captcha.manual_alert_timeout_seconds`; skips or retries on timeout | Operator wants full control and is monitoring the bot during drops |
| `smart` (default) | Turnstile → auto-solve (2Captcha); reCAPTCHA/hCaptcha → manual mode with operator alert | Best of both worlds: fast Turnstile solves, human accuracy on hard challenges |

#### 9.4.2 CAPTCHA Budget Tracker

| Field | Config Key | Default | Description |
|-------|-----------|---------|-------------|
| Daily budget cap | `captcha.daily_budget_usd` | $5.00 | Halts 2Captcha auto-solves when daily spend exceeds this; manual mode remains available |
| Per-retailer cap | `captcha.retailer_budget_usd` | None | Optional per-retailer override (e.g., $1.00 for Target, $3.00 for Best Buy) |
| Solve time alert threshold | `captcha.solve_time_alert_ms` | 60000ms | Fire webhook alert if single solve exceeds this (2Captcha overloaded or blocked) |
| Daily cumulative log | `captcha.log_daily_total` | true | Log total spend to console on shutdown |

### 9.5 Anti-Detection / Evasion

| ID | Requirement | Priority |
|----|-------------|----------|
| EV-1 | Rotate User-Agent strings per-request from a pool of ≥50 real UA strings | P0 |
| EV-2 | Randomize Playwright browser fingerprint (viewport, timezone, locale, hardware concurrency) | P0 |
| EV-3 | Respect retailer robots.txt (do not crawl disallowed paths) | P0 |
| EV-4 | Implement proxy rotation using residential proxy pool (v2.0+) | P0 |
| EV-5 | Detect and handle IP rate limit responses (retry with backoff) | P0 |
| EV-6 | Do not execute non-essential JS (ads, analytics, tracking pixels) | P1 |

### 9.6 Notifications

| ID | Requirement | Priority |
|----|-------------|----------|
| NOT-1 | Send webhook POST to Discord with embed-formatted event payload | P0 |
| NOT-2 | Send webhook POST to Telegram with formatted message | P0 |
| NOT-3 | Retry failed webhook delivery up to 3 times with exponential backoff | P0 |
| NOT-4 | Include ISO-8601 timestamp and event type in all webhook payloads | P0 |
| NOT-5 | Queue webhook events if network is temporarily unavailable | P1 |
| NOT-6 | Fire all defined lifecycle events (Table in Section 8.2) | P0 |

### 9.7 Dashboard Interface

| ID | Requirement | Priority |
|----|-------------|----------|
| DSH-1 | Dashboard accessible at `http://localhost:8080` with PIN/password login screen on first launch | P0 |
| DSH-2 | Main status view shows: daemon online/offline indicator, active items list, per-retailer session health (green/yellow/red), last event timestamp | P0 |
| DSH-3 | Real-time event log streams live to dashboard via SSE — shows timestamp, event type, item, retailer for each event | P0 |
| DSH-4 | "Start Monitoring" and "Stop Monitoring" buttons; both require confirmation dialog to prevent accidental clicks | P0 |
| DSH-5 | Item selector: dropdown or card grid to select which item(s) and retailer(s) to monitor before starting | P0 |
| DSH-6 | "Run Dry Run" button triggers full checkout flow without placing order; output streamed to a terminal panel in the dashboard | P0 |
| DSH-7 | Settings page: all `config.yaml` fields (retailer accounts, shipping, payment, CAPTCHA mode, daily budget) editable via form fields with inline validation — no raw YAML editing required | P0 |
| DSH-8 | "Validate Config" button runs full config validation and shows pass/fail with specific error messages | P0 |
| DSH-9 | CAPTCHA panel: shows current mode (auto/manual/smart), daily spend vs. budget cap, per-retailer spend breakdown, solve time alerts | P0 |
| DSH-10 | Drop Window Calendar: list of upcoming drop events with datetime and timezone; add/edit/delete drop windows; auto-prewarm status shown per drop | P0 |
| DSH-11 | Multi-Account panel: all configured accounts per retailer shown with session health, last prewarm time, enabled/disabled toggle | P0 |
| DSH-12 | Event history page: searchable log of past events (last 500) with filters by event type, retailer, item | P1 |
| DSH-13 | Operator logout button ends session and returns to PIN/password login | P0 |
| DSH-14 | Dashboard is responsive and works on tablet-sized screens (1024px minimum) | P1 |
| DSH-15 | Viewer role (read-only): can see status, session health, event history, and configuration summary — but start/stop/dry-run buttons are hidden and no settings changes permitted | P0 |
| DSH-16 | "Restart Daemon" button visible in dashboard header; confirms before restarting; daemon auto-restarts via supervisor/systemd on crash | P0 |
| DSH-17 | Setup wizard on first launch: operator sets PIN/password, fills in first retailer account, shipping info, payment info — step by step with inline help text | P0 |

### 9.8 Configuration Management

| ID | Requirement | Priority |
|----|-------------|----------|
| CFG-1 | All configuration via YAML file — zero hardcoded values | P0 |
| CFG-2 | Config schema validated on startup; missing/invalid fields raise errors | P0 |
| CFG-3 | Environment variable overrides for secrets: `POKEDROP_2CAPTCHA_KEY`, `POKEDROP_DISCORD_URL`, etc. | P1 |
| CFG-4 | Sensitive fields (card_number, cvv, api_key) never logged or printed | P0 |
| CFG-5 | Config supports multiple items monitored simultaneously | P0 |
| CFG-6 | Per-retailer check interval overrides at the retailer and item level | P0 |
| CFG-7 | Drop window calendar: operator defines scheduled drop events with date/time/timezone; bot auto-triggers prewarm when countdown reaches `prewarm_minutes` threshold | P0 |
| CFG-8 | Config hot-reload: `POST /api/config/reload` reloads config.yaml from disk, validates, and applies — if invalid, logs error and continues with previous config | P1 |
| CFG-9 | Dashboard Settings page provides form-based config editing for all `config.yaml` fields — shipping, payment, retailers, items, CAPTCHA mode, daily budget — rendered as form fields with inline validation | P0 |
| CFG-10 | Config changes from dashboard are validated before saving; invalid changes show inline field errors and are not saved to disk | P0 |
| CFG-11 | Sensitive fields (card_number, cvv, API keys) masked in dashboard UI (`****1234`) and in `state.db` | P0 |

### 9.9 Drop Window Calendar

| ID | Requirement | Priority |
|----|-------------|----------|
| DWC-1 | Operator can define drop events: item name, retailer, drop datetime (ISO-8601 with timezone), prewarm minutes before | P0 |
| DWC-2 | Bot auto-starts prewarm session when countdown reaches the configured `prewarm_minutes` for that drop | P0 |
| DWC-3 | Drop events stored in `config.yaml` under `drop_windows:` list; validated on startup | P0 |
| DWC-4 | Multiple drop windows can be active simultaneously (multi-item, multi-retailer) | P0 |
| DWC-5 | Bot sends `DROP_WINDOW_APPROACHING` webhook at prewarm start and `DROP_WINDOW_OPEN` when drop time arrives | P1 |
| DWC-6 | Past drop windows automatically pruned from active memory on startup | P0 |

### 9.10 Multi-Account Coordination

| ID | Requirement | Priority |
|----|-------------|----------|
| MAC-1 | Config supports multiple retailer accounts per retailer (e.g., 2 Target accounts, 3 Walmart accounts) | P0 |
| MAC-2 | Items can be assigned to specific account(s) or spread round-robin across available accounts | P0 |
| MAC-3 | One-purchase-per-account rule enforced: same item cannot be purchased by two accounts in the same drop window | P0 |
| MAC-4 | Account-level session pre-warming runs in parallel across all configured accounts | P0 |
| MAC-5 | Dashboard Multi-Account panel shows per-account health: session valid, cookies fresh, last prewarm time, enabled/disabled status | P1 |
| MAC-6 | Account credential storage: each account stored as a separate config block under `accounts:`; credentials loaded at startup | P0 |

### 9.11 Social Listening

| ID | Requirement | Priority |
|----|-------------|----------|
| SCL-1 | Optional toggle: when `social_listening.enabled = true`, bot monitors Twitter/X for drop-related keywords | P1 |
| SCL-2 | Sources configurable: Twitter/X (API v2), Discord (channel IDs), Email (IMAP) — each independently enableable | P1 |
| SCL-3 | Keywords defined per monitored item in config (e.g., ["Charizard Elite Trainer Box", "Pokemon restock", "ETB restock"]) | P1 |
| SCL-4 | Social signal triggers prewarm for matching item/retailer; does not auto-checkout — requires operator confirmation for first use | P1 |
| SCL-5 | Discord: listen to specific channel IDs, not entire server; message content matched against item keywords | P1 |
| SCL-6 | Twitter/X: stream filtered tweets matching keywords; auto-parse tweet for URLs and item names | P1 |
| SCL-7 | All social listening is read-only; bot does not post, reply, or interact with social platforms | P0 |
| SCL-8 | `social_listening.mock = true` for testing without live API credentials | P2 |

### 9.13 Drop Countdown Timer

| ID | Requirement | Priority |
|----|-------------|----------|
| DCT-1 | Operator can manually enter a drop time for a known event via dashboard "Schedule Drop" form — date/time picker with timezone | P0 |
| DCT-2 | Bot computes time until drop; when `time_until_drop <= prewarm_minutes`, auto-starts session pre-warming | P0 |
| DCT-3 | Countdown displayed in dashboard (Section 9.10) and fired via `DROP_WINDOW_APPROACHING` webhook | P1 |
| DCT-4 | If drop time is within 5 minutes and session is not pre-warmed, fire urgent `PREWARM_URGENT` webhook | P0 |
| DCT-5 | Supports one-shot drops (single event) and recurring drops (cron-like schedule, v2.1+) | P0 |

### 9.14 Operational Reliability

| ID | Requirement | Priority |
|----|-------------|----------|
| OP-1 | **Crash Recovery**: on abnormal exit (signal, unhandled exception), persist current checkout state to `state.json` — item, retailer, stage reached, timestamps | P0 |
| OP-2 | On restart, load `state.json`; if order was already placed, skip that item; if checkout was in progress, resume from last known good stage | P0 |
| OP-3 | **Health Check Endpoint**: `GET /health` returns HTTP 200 + JSON `{status, active_items, session_health, last_event_at, uptime_seconds}` | P0 |
| OP-4 | Health check endpoint does not require authentication; intended for operator's own monitoring (port monitoring, uptime robot) | P0 |
| OP-5 | **Config Hot-Reload**: `POST /api/config/reload` triggers full config re-parse and validation; if valid, applies changes; if invalid, logs error and continues with previous config | P1 |
| OP-6 | Dashboard shows daemon uptime and last restart time; if daemon is not running, dashboard shows clear "Daemon Offline — restart required" banner with a prominent "Restart Daemon" button | P0 |

### 9.15 Adapter Plugin Architecture

| ID | Requirement | Priority |
|----|-------------|----------|
| ADP-1 | Retailer adapters (Target, Walmart, BestBuy) are loaded via a plugin registry at startup — no hardcoded retailer list | P0 |
| ADP-2 | Plugin discovery: adapters in `src/monitor/retailers/` are auto-loaded if they inherit from `RetailerAdapter` base class | P0 |
| ADP-3 | Adding a new retailer (e.g., GameStop) requires: create `src/monitor/retailers/gamestop.py` implementing `RetailerAdapter`, add entry to `config.yaml` — zero changes to core monitoring loop | P0 |
| ADP-4 | Adapter plugin can declare dependencies (e.g., specific CAPTCHA handler) in its class metadata | P2 |
| ADP-5 | Dashboard "About" page lists all loaded retailer adapter plugins with their name, version, and enabled/disabled status | P1 |

---

## 10. Non-Functional Requirements

### 10.1 Performance

| Requirement | Target |
|-------------|--------|
| Stock detection latency | < 1s for Target/Walmart; < 500ms for Best Buy |
| Checkout completion (Target) | < 10s end-to-end |
| Checkout completion (Walmart) | < 15s end-to-end |
| Checkout completion (Best Buy) | < 5s end-to-end |
| Memory footprint (idle, pre-warmed) | < 512 MB |
| Browser instances per retailer | 1 (shared session) |

### 10.2 Reliability

| Requirement | Target |
|-------------|--------|
| Uptime during monitoring window | 99% (network failures excluded) |
| Checkout success rate (pre-warmed) | ≥ 85% |
| Webhook delivery reliability | ≥ 99% after retries |
| Crash recovery | Restart from last known good state; do not re-purchase already-ordered items |
| Bot daemon auto-restart | Supervisor/systemd restarts daemon within 10s of crash; dashboard shows "Daemon Offline" banner during downtime |

### 10.3 Security

| Requirement | Priority |
|-------------|----------|
| Dashboard PIN/password hashed (argon2 or bcrypt) before storage — never stored in plaintext | P0 |
| All dashboard API endpoints require valid session cookie — no endpoint is publicly accessible | P0 |
| Sensitive config fields (card_number, cvv, CVV) masked in dashboard UI (`****1234`) and never written to logs | P0 |
| `state.db` and `auth.db` stored in bot's working directory with OS-level file permissions | P0 |
| Session cookies: httpOnly, sameSite=strict, expire after 8 hours of inactivity | P1 |
| All webhook URLs validated as HTTPS | P0 |
| No external network calls except to configured retailers, 2Captcha, and notification endpoints | P0 |
| Browser sandboxed; no access to local filesystem beyond config/logs | P0 |
| Dashboard does not serve files from the filesystem beyond its own assets (no path traversal) | P0 |
| Card CVV never stored post-checkout | P0 |
| API keys for 2Captcha loaded from environment variables in production | P1 |

### 10.4 Scalability

| Requirement | Notes |
|-------------|-------|
| Multiple items monitored concurrently | Supported in v1 |
| Multiple retailers monitored concurrently | Supported in v1 |
| Multiple accounts coordinated (shared item pool) | v2.0+ |
| Horizontal scaling (multiple machines sharing state) | v2.1+ via shared Redis or file lock |

---

## 11. Validation & Business Rules

| Rule | Description |
|------|-------------|
| One active cart per retailer | Only one item checked out per retailer at a time |
| Pre-warm required before checkout | Must pre-warm session at least N minutes (config.per-tailer) before drop window |
| Retry budget | Max 2 checkout retries per item per monitoring session |
| Captcha timeout | If CAPTCHA not solved within 120s, abort and alert |
| Payment retry | On decline, wait 2s then retry once; on second decline, abort |
| Config validation | Startup fails if required fields missing or invalid; no silent defaults |
| Timeout per checkout step | Each checkout sub-step times out at 30s; overall checkout at 60s |

---

## 12. Edge Cases & Exception Handling

| Scenario | Handling |
|----------|----------|
| Network connection drops mid-checkout | Retry checkout from cart (re-verify item still in cart) |
| Retailer page structure changes | Log error, fire SESSION_EXPIRED, alert operator, do not silently continue |
| Payment declines on retry | Fire PAYMENT_DECLINED webhook, do not attempt further retries |
| Item goes out of stock during cart wait | Fire CHECKOUT_FAILED with stage="stock_verify", retry if retries remaining |
| CAPTCHA solve times out | Fire CAPTCHA_REQUIRED → alert, skip item or retry on next stock detection |
| Queue/waiting room blocks > 60s | Fire QUEUE_DETECTED, fire QUEUE_CLEARED when through, continue checkout |
| Session cookie expires mid-checkout | Re-authenticate (pre-warmed credentials), restart checkout from cart |
| Multiple operators start same item simultaneously | First-to-acquire lock wins; others receive SESSION_EXPIRED |
| Config file modified while running | Hot-reload not supported; operator must restart |
| Disk full / cannot write logs | Log to stdout only, emit warning, continue operation |

---

## 13. Dependencies & External Services

| Service | Purpose | Auth | SLA Required |
|---------|---------|------|--------------|
| Target.com | Retailer | Account credentials | 99.9% |
| Walmart.com | Retailer | Account credentials | 99.9% |
| BestBuy.com | Retailer | Account credentials | 99.9% |
| 2Captcha.com | CAPTCHA auto-solve (Turnstile, reCAPTCHA, hCaptcha) | API key | 95% solve rate |
| FastAPI | Web framework — serves dashboard + API on localhost | — | Python |
| Uvicorn | ASGI server — runs the FastAPI dashboard server | — | Ships with FastAPI |
| SQLite | Local state (`state.db`) + auth (`auth.db`); WAL mode for concurrency | — | Built into Python |
| argon2 or bcrypt | Password hashing for dashboard PIN/password | — | Python library |
| SSE | Real-time event push from daemon to dashboard | — | Built into FastAPI |
| Discord webhook | Notifications | Webhook URL | Best effort |
| Telegram Bot API | Notifications | Bot token + chat ID | Best effort |
| Residential proxy pool | Anti-detection (v2.0) | IP:port:user:pass | 99% uptime |

---

## 14. Phases & Implementation Sequencing

### Phase 1 — Target MVP (v1.0)

**Goal:** Single-retailer proof of concept, fastest path to working checkout.

Deliverables:
- [ ] `RetailerAdapter` base class
- [ ] `TargetAdapter` with stock monitoring via Playwright
- [ ] `CartManager` for Target cart API
- [ ] `CheckoutFlow` for Target checkout
- [ ] `DiscordWebhook` notifications
- [ ] Web Dashboard: login, main status view (daemon status, active items, session health), start/stop buttons with confirmation, real-time event log via SSE, dry-run output panel, config validation
- [ ] Config schema with Target retailer
- [ ] UA rotation (pool of 50)
- [ ] Jitter on check intervals (±20%)

**Exit Criteria:** Dry-run checkout on Target completes in < 10s with all events firing correctly.

---

### Phase 2 — Walmart + Evasion (v1.1 → v1.2)

**Goal:** Add second retailer and advanced evasion.

Deliverables:
- [ ] `WalmartAdapter` (full checkout + login flow)
- [ ] `BestBuyAdapter` (full checkout + Turnstile handling)
- [ ] Browser fingerprint randomization
- [ ] Proxy rotation (v2.0)
- [ ] Queue/waiting room handling (all retailers)
- [ ] `TelegramWebhook` notifications
- [ ] Per-retailer pre-warming

**Exit Criteria:** Bot detects stock on Walmart and Best Buy in < 1s; full checkout dry-run completes on both.

---

### Phase 3 — Production Hardening (v2.0)

**Goal:** Production-ready with multi-retailer, advanced anti-detection, operational tooling.

Deliverables:
- [ ] Proxy rotation with residential proxy pool
- [ ] 2Captcha integration (reCAPTCHA, hCaptcha, Turnstile)
- [ ] Multi-account coordination (shared item pool, one-purchase-per-account rule)
- [ ] Session pre-warming with scheduled warm-up before drop window
- [ ] Structured logging (JSON) with log rotation
- [ ] Health check endpoint (`/health`) for deployment monitoring
- [ ] Config hot-reload via `POST /api/config/reload` (dashboard "Reload Config" button)
- [ ] Crash recovery (persist state to disk)
- [ ] Operational dashboard: replaced by primary web dashboard (Section 9.7)

**Exit Criteria:** 85%+ success rate on dry-run across all three retailers; all webhook events fire; no hardcoded values.

---

## 15. Testing Requirements

| Test Type | Coverage Target | Framework |
|-----------|----------------|-----------|
| Unit tests | Core logic: config validation, jitter, UA rotation, state machine | pytest |
| Retailer adapter unit tests | Mocked responses, each adapter method | pytest + responses library |
| Integration tests | End-to-end dry-run against live retailer pages (opt-in, tagged `integration`) | pytest |
| CAPTCHA integration tests | Mock 2Captcha responses, verify token injection | pytest |
| Evasion tests | Verify fingerprint randomization, UA uniqueness | pytest |
| Config validation tests | Valid and invalid configs; verify error messages | pytest |

**Integration tests run only when explicitly enabled (`pytest --run-integration`).** They interact with live retailer pages and may place orders.

---

## 16. QA Acceptance Criteria

| # | Criterion | Test Method |
|---|-----------|-------------|
| 1 | Bot daemon starts and `config.yaml` is valid | Dashboard "Validate Config" shows green checkmark |
| 2 | Dry-run completes checkout on Target without placing order | Manual test with dry-run flag |
| 3 | All 12 webhook events fire in correct sequence | Webhook endpoint captures event sequence |
| 4 | Stock detection responds within 1s of item going live | Time from simulated IS state to STOCK_DETECTED event |
| 5 | Payment credentials are never logged or printed to stdout | Code review + log file grep |
| 6 | Checkout fails gracefully when item is OOS after cart add | Simulate OOS after cart, verify error handling |
| 7 | CAPTCHA solve completes within 120s or times out correctly | Mock 2Captcha slow response |
| 8 | Multiple items monitored simultaneously without interference | Run with ≥3 items, verify correct routing |
| 9 | Session pre-warming caches cookies and reuses them | Inspect network logs for auth requests |
| 10 | Crash during checkout does not duplicate order on restart | Kill process mid-checkout, restart, verify no duplicate |
| 11 | Config schema validation rejects missing required fields | Supply invalid config, verify startup error |
| 12 | Logs contain timestamps, event types, and item names | Inspect log output |

---

## 17. Deployment & Environment Requirements

| Environment | Configuration Source | Secrets Source |
|-------------|---------------------|----------------|
| Development | `config.yaml` in repo root | Direct in config.yaml |
| Production | `config.yaml` (managed by operator via dashboard) | Environment variables |

### Operator Setup (Non-Technical, No Terminal Required)

1. **Download and run** the installer/executable for your OS
2. **First launch**: browser automatically opens to `http://localhost:8080/setup`
3. **Setup Wizard**: step-by-step flow:
   - Set dashboard PIN/password (minimum 6 digits)
   - Add first retailer account (Target, Walmart, or Best Buy)
   - Enter shipping address
   - Enter payment method (card number, expiry, CVV — stored in `config.yaml`)
   - Configure CAPTCHA mode (auto / manual / smart — see Section 9.4.1)
4. **Validate Config**: click "Test Config" → green checkmark confirms all credentials valid
5. **Start Monitoring**: select item(s) and retailer(s) → click "Start Monitoring"
6. **Dashboard**: real-time status visible at `http://localhost:8080` — green = healthy, yellow = degraded, red = error

**Daemon runs in background**: no terminal window needs to stay open. A shortcut/app alias is created in the Start Menu / Applications folder.

### Daemon Management

| Scenario | How it works |
|----------|-------------|
| Operator opens dashboard | Browser → `http://localhost:8080` → login → dashboard UI |
| Operator closes browser | Bot keeps running in background |
| Bot crashes | Supervisor/systemd auto-restarts within 10s; dashboard shows "Daemon Offline" banner |
| Machine restarts | Supervisor auto-starts daemon on boot (user login not required) |
| Need to restart daemon | "Restart Daemon" button in dashboard header |

### File Permissions

```bash
chmod 600 config.yaml   # Owner read/write only
chmod 600 auth.db       # SQLite auth DB — contains hashed PIN, no plaintext
chmod 600 state.db      # SQLite state DB
chmod 600 poke_drop.log # Rotate regularly (10MB max, 5 backups)
```

### Process Supervisor (Required for Production)

The daemon must run under a supervisor to auto-restart on crash:

**macOS / Linux (launchd / systemd):**
```plist
<!-- com.pokedrop.bot.plist (macOS) -->
<Label>com.pokedrop.bot</Label>
<ProgramArguments>/usr/bin/python3 /path/to/src/daemon.py</ProgramArguments>
<RunAtLoad/>
<KeepAlive/>
```

**Windows:** Use a simple wrapper or Windows Task Scheduler with "Run on startup" and restart on failure.

---

## 18. Logging, Monitoring & Observability

| Requirement | Implementation |
|-------------|----------------|
| Log format | Structured JSON to `logs/pokedrop.log`; plain text to rotating file |
| Log levels | DEBUG (form field values), INFO (lifecycle events), WARNING (retriable errors), ERROR (fatal) |
| Log rotation | Python `logging.handlers.RotatingFileHandler`, 10MB max, 5 backups |
| Key log events | MONITOR_START, STOCK_DETECTED, CART_ADDED, CHECKOUT_START, CHECKOUT_SUCCESS, CHECKOUT_FAILED, ERROR |
| Bot state DB | All state written to `state.db` (SQLite WAL mode) — dashboard reads from same DB |
| Event history | Last 500 events stored in `state.db events` table; accessible via dashboard event history page |
| Real-time dashboard | SSE stream at `GET /api/events/stream` pushes live events to dashboard UI |
| Health check | `GET /health` returns `{status, active_items, session_health, last_event_at, uptime_seconds}` |
| Daemon offline detection | Dashboard polls `GET /health` every 5s; if unreachable, shows "Daemon Offline" banner |

---

## 19. Analytics & Event Tracking

| Event | Purpose |
|-------|---------|
| CHECKOUT_SUCCESS | Track success rate over time |
| CHECKOUT_FAILED + stage | Identify bottleneck stages |
| CAPTCHA solve_time_ms | Track cost and latency per solve |
| STOCK_DETECTED count | Measure drop window awareness |

No personally identifiable data beyond item name, retailer, and order ID is tracked or exported.

---

## 20. Support & Operational Considerations

| Topic | Guidance |
|-------|----------|
| **Bot does not complete purchase** | Check dashboard event log for CHECKOUT_FAILED stage; common causes: payment decline, session expired, CAPTCHA timeout |
| **Blocked by retailer** | Run dry-run from dashboard to verify; change IP via proxy rotation; reduce check frequency |
| **CAPTCHA cost too high** | Open CAPTCHA panel in dashboard; reduce daily budget cap or switch to manual mode |
| **Config not loading** | Click "Validate Config" in dashboard Settings — shows specific field-level errors |
| **Monitoring not starting** | Check daemon status in dashboard header (green/red); if offline, click "Restart Daemon" |
| **Session pre-warming** | Must run at least 10 minutes before drop window; pre-warmed sessions expire after 2 hours |
| **Dashboard shows "Daemon Offline"** | Click "Restart Daemon" button in header; if problem persists, check `logs/pokedrop.log` for errors |
| **Forgot PIN/password** | Edit `auth.db` manually (see README recovery instructions) or delete `auth.db` to reset — dashboard will run setup wizard again |

---

## 21. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Retailer blocks IP after repeated requests | High | Medium | Proxy rotation (v2.0), respect rate limits, reduce check frequency |
| CAPTCHA on every request | Medium | High | 2Captcha integration, budget ~$0.50–$2.00 per solve |
| Retailer changes page structure (XPath, API) | High | High | Modular adapter pattern isolates changes to one retailer module |
| Payment processor flags as fraud | Low | High | Randomized delay, saved payment method, correct billing address |
| Anti-bot (Turnstile/Cloudflare) blocks all automation | High | High | Playwright stealth mode, fingerprint randomization, proxy rotation |
| ToS violation / account ban | Medium | High | Use separate account for bot; do not use on primary account |
| Disk fills with logs | Low | Low | Log rotation (10MB × 5 backups) |
| Checkout race with other bots | High | Medium | Pre-warm sessions, fastest checkout path, 1-Click when available |
| Web server crash (daemon keeps running) | Low | Low | Daemon runs separately; dashboard is client-only; restart button restores access |
| Dashboard accessible to other users on same machine | Low (localhost only) | High | PIN required on every session; no external interface binding |
| SQLite DB corruption | Low | Medium | WAL mode; bot continues if DB is read-only; operator can restore from backup |
| Operator loses PIN/password | Medium | High | Recovery: delete `auth.db`, restart — setup wizard runs again (see README) |

---

## 22. Legal & Compliance

- Users are responsible for complying with retailer Terms of Service.
- Users are responsible for complying with applicable federal, state, and local laws.
- This tool is provided as-is. The authors accept no liability for account bans, purchase disputes, or legal consequences.
- Retailer credentials must not be shared or committed to version control.
- PCI-DSS compliance is not claimed; use a dedicated card with limit for自动化 purchases.

---

## 23. v1 vs v2 vs v4 Comparison

| Feature | v1.0 | v2.0 | v4.0 (this doc) |
|---------|------|------|-----------------|
| Retailers | Target (1) | Target + Walmart + Best Buy | All three + extensible adapter |
| Stock Monitoring | HTTP GET + Playwright | Playwright (all) | Playwright (all) + session reuse |
| Check Interval | 500ms fixed | Per-retailer config | 100–500ms per retailer + jitter |
| Evasion | UA rotation only | UA + fingerprint + proxy | UA + fingerprint + proxy + respect robots.txt |
| CAPTCHA Solving | No | 2Captcha (reCAPTCHA only) | 2Captcha + Manual Mode + Smart Routing |
| CAPTCHA Budget Tracker | No | No | Yes — daily cap, per-retailer cap, solve time alerts |
| Notifications | Discord | Discord + Telegram | Discord + Telegram + retry queue |
| Session Pre-warm | No | Basic | Full cookie/token caching with expiry |
| Checkout Retries | No | 1 retry | Configurable N retries (default 2) |
| Queue Handling | No | Basic detection | Detection + auto-wait + QUEUE_CLEARED events |
| Dry-run Mode | Yes | Yes | Yes + stage-resumable on crash |
| Health Check | No | No | Yes (`/health` endpoint) |
| Crash Recovery | No | No | Persist state, no duplicate orders |
| Config Validation | Basic | Basic | Full schema validation + env var overrides |
| Multi-account | No | Yes (basic) | Yes + one-purchase-per-account enforcement |
| Primary Interface | CLI (terminal commands) | CLI | **Web Dashboard (localhost)** |
| TUI | Yes — Rich/Textual terminal UI | Yes | **Removed — replaced by web dashboard** |
| Web Framework | No | No | **FastAPI + Uvicorn (localhost)** |
| Local DB | No | No | **SQLite (state.db + auth.db)** |
| Auth Mechanism | OS file permissions (chmod) | OS file permissions | **App-level PIN/password + session cookie** |
| Config Hot-Reload | SIGHUP signal | SIGHUP signal | **POST /api/config/reload (dashboard button)** |
| Deployment | Terminal commands | Terminal commands | **Installer + browser (no terminal)** |
| Drop Window Calendar | No | No | Yes — scheduled drops with auto-prewarm |
| Session Health Dashboard (TUI) | No | No | **Removed — replaced by web dashboard** |
| Social Listening | No | No | Yes — Twitter/X, Discord, Email (optional) |
| Drop Countdown Timer | No | No | Yes — manual entry with prewarm trigger |
| Adapter Plugin Architecture | No | No | Yes — load retailers as plugins |
| CAPTCHA Budget Tracker | No | No | Yes — daily cap, per-retailer cap, solve time alerts |
| CAPTCHA Manual Mode + Smart Routing | No | No | Yes — operator can pause and solve manually |
| Web Dashboard | No | Future | **Primary interface (v4.0)** |
| Success Rate (est.) | 60–70% | 80–85% | 85–90% |

---

## 24. Definitions & Glossary

| Term | Definition |
|------|------------|
| **OOS → IS** | Out-of-stock to in-stock state transition |
| **1-Click** | Retailer express checkout using saved shipping/payment |
| **Pre-warming** | Loading retailer session (cookies, auth tokens) before drop window |
| **Queue/Waiting Room** | Retailer-implemented rate limiter that holds users before checkout |
| **Turnstile** | Cloudflare's CAPTCHA replacement (used by Best Buy) |
| **Stealth Mode** | Playwright configuration that hides automation signals |
| **Dry-run** | Full checkout flow without placing order; validates config and flow |
| **Adapter** | Retailer-specific implementation of the `RetailerAdapter` base class |
| **Daemon** | Background process running the bot (src/daemon.py); handles all monitoring, cart, checkout, evasion logic — has no UI of its own |
| **Dashboard** | Web-based operator interface served by dashboard/server.py at `http://localhost:8080`; all bot interaction goes through here — operator never interacts with daemon directly |
| **SSE (Server-Sent Events)** | Technology that pushes real-time events from daemon to dashboard without polling; daemon writes event to state.db and pushes via SSE stream |
| **Localhost-only** | Service bound to 127.0.0.1 — accessible only from the same machine; not exposed to the internet or local network |
| **WAL mode** | SQLite Write-Ahead Logging mode — allows concurrent read access while writing; required for dashboard daemon to access state.db simultaneously |
| **Auth DB** | SQLite database (`auth.db`) storing hashed operator PIN/password and session cookies |
| **State DB** | SQLite database (`state.db`) storing bot state, event history, command queue (WAL mode enabled) |
| **Jitter** | Random variance added to timing to appear more human-like |

---

*END OF PRD*
