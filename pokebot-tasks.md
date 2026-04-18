# PokeDrop Bot — Task Backlog
**Version:** 1.0  
**Generated:** 2026-04-18  
**PRD Reference:** PokeBot_PRD.md v4.0  

---

## Phases Overview

| Phase | Scope | Duration |
|-------|-------|----------|
| Phase 1 | Bot Core (Stock Monitoring, Cart, Checkout) | ~1 week |
| Phase 1.5 | Daemon + DB (Infrastructure) | ~2–3 days |
| Phase 2 | Dashboard (Web UI, Config, TUI replacement) | ~1 week |
| Phase 3 | Advanced Features (CAPTCHA, Drop Calendar, Multi-Account, Social, Countdown) | ~1 week |
| Phase 4 | Hardening + Polish (Testing, Security, Reliability) | ~3–4 days |

---

## Phase 1 — Bot Core

### Phase 1.1 — Shared Infrastructure

---

**SHARED-T01** ✅ DONE
- **Title:** Set up project structure and dependencies
- **Feature Area:** `shared/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** —
- **Description:** Create directory structure per Section 7.1, set up `requirements.txt` with pinned deps (httpx≥0.27, playwright≥1.40, pyyaml≥6.0, fastapi≥0.110, uvicorn≥0.27, aiohttp≥3.9, pytest≥8.0, mypy≥1.8, argon2-cffi, responses), create `pyproject.toml` with package metadata.
- **Acceptance Criteria:**
  - [x] `requirements.txt` exists and lists all core dependencies
  - [x] `pyproject.toml` exists with package metadata
  - [x] `config.example.yaml` template exists
  - [x] `src/` directory tree created per PRD Section 7.1
  - [x] All `__init__.py` files present
  - [x] All subdirectories created
  - [x] Tests added in `tests/test_shared/test_project_structure.py`
  - [x] pytest: 13 passed
  - [x] mypy: no issues

---

**SHARED-T02** ✅ DONE
- **Title:** Implement SQLite state.db schema
- **Feature Area:** `shared/db.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T01
- **Description:** Create `shared/db.py` with WAL-mode SQLite helpers for `state.db` and `auth.db`. Define tables: `events` (id, event, item, retailer, timestamp, order_id, error, attempt), `command_queue` (id, command, args, created_at, processed_at, status), `session_state` (retailer, cookies_json, auth_token, cart_token, prewarmed_at, is_valid), `drop_windows` (id, item, retailer, drop_datetime, prewarm_minutes, enabled). Use sqlite3 with WAL mode, connection pooling. PRD Sections 8.1, 8.2.
- **Acceptance Criteria:**
  - [x] DatabaseManager class with WAL mode and connection pooling
  - [x] All tables created with correct schemas
  - [x] Events table with indexed queries
  - [x] Command queue with claim/complete pattern
  - [x] Session state save/load/invalidate
  - [x] Drop windows CRUD + past pruning
  - [x] CAPTCHA budget tracking
  - [x] Tests: 31 passed
  - [x] mypy: no issues

---

**SHARED-T03** ✅ DONE
- **Title:** Define shared dataclasses/models
- **Feature Area:** `shared/models.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T01
- **Description:** Implement all dataclasses from PRD Section 8.1: `MonitoredItem`, `RetailerAdapter`, `CheckoutConfig`, `ShippingInfo`, `PaymentInfo`, `WebhookEvent`, `SessionState`. Use `dataclasses` with type hints. PRD Section 8.1.
- **Acceptance Criteria:**
  - [x] All dataclasses implemented (MonitoredItem, RetailerAdapterConfig, CheckoutConfig, ShippingInfo, PaymentInfo, WebhookEvent, SessionState, DropWindow, CaptchaSolveResult, StockStatus)
  - [x] All enums defined (CaptchaMode, CaptchaType, CheckoutStage, RetailerName)
  - [x] Abstract RetailerAdapter base class with all abstract methods
  - [x] Tests: 23 passed
  - [x] mypy: no issues

---

**SHARED-T04** ✅ DONE
- **Title:** Implement config loading and validation
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T01, SHARED-T03
- **Description:** Create `bot/config.py` to load and validate `config.yaml`. Implement schema validation for all required fields (retailers, items, shipping, payment, CAPTCHA). Raise clear errors on missing/invalid fields. Support environment variable overrides (`POKEDROP_2CAPTCHA_KEY`, `POKEDROP_DISCORD_URL`, etc.). PRD Sections 9.8, 11.
- **Acceptance Criteria:**
  - [x] Config class with from_file() factory and _validate() schema validation
  - [x] Field-level ConfigError messages
  - [x] Environment variable overrides for secrets (POKEDROP_CC_NUMBER, POKEDROP_2CAPTCHA_KEY, etc.)
  - [x] mask_secrets() for safe API responses
  - [x] get_enabled_retailers() helper
  - [x] Tests: 56 passed
  - [x] mypy: no issues

---

**SHARED-T05** ✅ DONE
- **Title:** Implement structured logging with SSE stream
- **Feature Area:** `bot/logger.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T01
- **Description:** Create `bot/logger.py` with structured JSON logging to `logs/poke_drop.log`. Use `RotatingFileHandler` (10MB, 5 backups). Implement log levels: DEBUG (form fields masked), INFO (lifecycle events), WARNING, ERROR. Also emit events to SSE stream for dashboard consumption. PRD Sections 10.1, 18.
- **Acceptance Criteria:**
  - [x] Logger class with RotatingFileHandler (10MB, 5 backups) to logs/poke_drop.log
  - [x] Structured JSON log lines with timestamp + level + event + kwargs
  - [x] Sensitive field masking: card_number/cvv/password/tokens always redacted at INFO/WARNING/ERROR; card_number shows last 4 at DEBUG
  - [x] Human-readable console output
  - [x] In-memory SSE event queue (max 1000 events) via Logger.get_sse_queue()
  - [x] All webhook event types from PRD Section 8.2 supported
  - [x] Tests: 50 passed
  - [x] mypy: no issues

---

**SHARED-T06** ✅ DONE
- **Title:** Implement crash recovery (state.json persistence)
- **Feature Area:** `shared/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02, SHARED-T03
- **Description:** Implement crash recovery: on abnormal exit (signal, unhandled exception), persist current checkout state to `state.json` — item, retailer, stage reached, timestamps. On restart, load `state.json` and either skip already-ordered items or resume from last known good stage. PRD Section 9.14 (OP-1, OP-2).
- **Acceptance Criteria:**
  - [x] CrashRecovery context manager with signal handlers (SIGTERM, SIGINT, SIGHUP)
  - [x] Persists state.json on abnormal exit (signal, unhandled exception)
  - [x] Clears state.json on normal exit
  - [x] CrashRecoveryState dataclass with item, retailer, stage, timestamps, order_id, error
  - [x] update() API for stage transitions during checkout
  - [x] load() and clear() for restart recovery
  - [x] Tests: 21 passed
  - [x] mypy: no issues

---

### Phase 1.2 — Retailer Adapters (Base + Target MVP)

---

**ADAPTER-T01**
- **Title:** Implement RetailerAdapter base class
- **Feature Area:** `bot/monitor/retailers/base.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Create abstract `RetailerAdapter` base class with all abstract methods: `login()`, `check_stock()`, `add_to_cart()`, `get_cart()`, `checkout()`, `handle_captcha()`, `check_queue()`. Include common utilities: session cookie management, prewarm logic, HTTP client setup via httpx. PRD Sections 9.1, 9.2, 9.3.
- **Acceptance Criteria:**
  - [x] Abstract `RetailerAdapter(ABC)` base class with all abstract methods implemented
  - [x] HTTP client setup via `httpx.AsyncClient` with connection pooling and timeouts
  - [x] Session state management: `save_session_state()`, `invalidate_session()`, `is_prewarmed()`
  - [x] Jitter helper: `apply_jitter(base_interval_ms, jitter_percent)` returning seconds
  - [x] Retry with backoff: `retry_with_backoff()` with exponential backoff
  - [x] Rate limit detection and retry: `handle_rate_limit()` for HTTP 429
  - [x] Stock check with retry: `stock_check_with_retry()` wrapper
  - [x] Subclass hook: `get_retailer_config()` for retailer-specific config access
  - [x] Tests: 27 passed
  - [x] mypy: no issues

---

**ADAPTER-T02**
- **Title:** Implement TargetAdapter (full checkout)
- **Feature Area:** `bot/monitor/retailers/target.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01
- **Description:** Implement `TargetAdapter` extending `RetailerAdapter`. Handle: Playwright headless browser login to target.com, stock detection via page monitoring (OOS→IS), cart API + UI fallback, full checkout flow (shipping, payment, order review, submit), 1-Click checkout path. Implement queue/waiting room detection. PRD Sections 9.1 (MON-1 to MON-11), 9.2 (CART-1 to CART-8), 9.3 (CO-1 to CO-10). Phase 1 exit criteria adapter.

---

**ADAPTER-T03**
- **Title:** Implement WalmartAdapter
- **Feature Area:** `bot/monitor/retailers/walmart.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01
- **Description:** Implement `WalmartAdapter` extending `RetailerAdapter`. Handle: Playwright login to walmart.com, stock detection, cart management, checkout flow, queue detection. PRD Sections 9.1, 9.2, 9.3.

---

**ADAPTER-T04**
- **Title:** Implement BestBuyAdapter with Turnstile
- **Feature Area:** `bot/monitor/retailers/bestbuy.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01
- **Description:** Implement `BestBuyAdapter` extending `RetailerAdapter`. Handle: Playwright login to bestbuy.com, Turnstile CAPTCHA detection and handling, stock detection, cart, checkout. PRD Sections 9.1, 9.2, 9.3.

---

**ADAPTER-T05**
- **Title:** Implement adapter plugin discovery registry
- **Feature Area:** `bot/monitor/retailers/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T01, ADAPTER-T02
- **Description:** Implement plugin discovery: auto-load adapters from `src/monitor/retailers/` that inherit from `RetailerAdapter`. Create a registry mapping retailer name → adapter class. Validate adapter interface on load. PRD Section 9.15 (ADP-1, ADP-2, ADP-3).

---

### Phase 1.3 — Evasion

---

**EVASION-T01** ✅ DONE
- **Title:** Implement User-Agent rotation pool
- **Feature Area:** `bot/evasion/user_agents.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T01
- **Description:** Create `bot/evasion/user_agents.py` with pool of ≥50 real User-Agent strings from real browsers (Chrome, Firefox, Safari, Edge). Implement rotation strategy (random per request). PRD Section 9.5 (EV-1).
- **Acceptance Criteria:**
  - [x] Pool of ≥50 real UA strings from Chrome, Firefox, Safari, Edge, and other browsers
  - [x] `get_random_user_agent()` returns a random UA from the pool per call
  - [x] `iter_user_agents()` yields all UAs in the pool
  - [x] `get_user_agent_for_browser(browser)` returns UA for specific browser family (chrome/firefox/safari/edge/opera/brave/android/iphone/ipad)
  - [x] Rotation strategy: uniform random per request
  - [x] Tests: 42 passed
  - [x] mypy: no issues

---

**EVASION-T02** ✅ DONE
- **Title:** Implement Playwright fingerprint randomization
- **Feature Area:** `bot/evasion/fingerprint.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T01
- **Description:** Implement `bot/evasion/fingerprint.py`: randomize viewport (width, height), timezone, locale, hardware concurrency, device memory. Configure Playwright stealth mode to hide automation signals. PRD Section 9.5 (EV-2).
- **Acceptance Criteria:**
  - [x] BrowserFingerprint dataclass with viewport, locale, timezone_id, user_agent, hardware_concurrency, device_memory, device_scale_factor
  - [x] Viewport pool: ≥10 realistic desktop/mobile viewport sizes
  - [x] Locale pool: ≥10 real browser locales (en-*, de-*, fr-*, etc.)
  - [x] Timezone pool: ≥10 IANA timezone IDs
  - [x] Hardware concurrency pool: multiple realistic CPU core counts
  - [x] Device memory pool: multiple realistic memory values in GB
  - [x] get_random_fingerprint() generates all randomized values from pools
  - [x] get_automation_mask_script() injects JS to spoof: navigator.webdriver=false, navigator.hardwareConcurrency, navigator.deviceMemory, Permissions API, connection info, canvas noise
  - [x] Tests: 31 passed
  - [x] mypy: no issues

---

**EVASION-T03**
- **Title:** Implement proxy rotation
- **Feature Area:** `bot/evasion/proxy.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T04
- **Description:** Implement proxy rotation from residential proxy pool. Load proxy list from config. Rotate per request or per session. Handle proxy auth. Detect and retry on proxy failure. PRD Section 9.5 (EV-4).

---

**EVASION-T04** ✅ DONE
- **Title:** Implement jitter on check intervals
- **Feature Area:** `bot/evasion/jitter.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Implement jitter module: add randomized variance ±N% (default 20%) to each stock check interval. Configurable per retailer. PRD Section 9.1 (MON-6).
- **Acceptance Criteria:**
  - [x] `apply_jitter(base_interval_ms, jitter_percent)` with ±N% variance
  - [x] `jitter_interval_seconds()` wrapper for seconds input
  - [x] `get_jitter_range()` helper returning (min, max) without randomizing
  - [x] Configurable jitter_percent per retailer (from config)
  - [x] Default 20% jitter when not specified
  - [x] Validates jitter_percent 0–100 and base_interval_ms ≥ 0
  - [x] Tests: 27 passed
  - [x] mypy: no issues

---

**EVASION-T05**
- **Title:** Implement IP rate limit detection and backoff
- **Feature Area:** `bot/evasion/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Detect HTTP 429 or other rate limit responses from retailers. Apply exponential backoff retry. Log rate limit events. PRD Section 9.5 (EV-5).

---

**EVASION-T06**
- **Title:** Respect retailer robots.txt
- **Feature Area:** `bot/evasion/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Before monitoring, fetch and parse retailer's robots.txt. Do not crawl disallowed paths. Cache robots.txt for session duration. PRD Section 9.5 (EV-3).

---

### Phase 1.4 — Session Management

---

**SESSION-T01**
- **Title:** Implement session pre-warmer
- **Feature Area:** `bot/session/prewarmer.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Implement session pre-warming: load retailer page, authenticate with credentials, cache all cookies and auth tokens, verify session validity. Pre-warm N minutes before drop window. Cache session with expiry (2 hours). PRD Sections 9.1 (MON-7), 9.10 (MAC-4).

---

**SESSION-T02**
- **Title:** Implement session persistence and reuse
- **Feature Area:** `bot/session/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SESSION-T01, SHARED-T02
- **Description:** Persist and reuse browser session cookies across checks. Store in `state.db` per retailer. Check expiry before each monitoring cycle; re-authenticate if expired. PRD Section 9.1 (MON-8), 9.1 (MON-10).

---

### Phase 1.5 — Checkout

---

**CHECKOUT-T01**
- **Title:** Implement CartManager
- **Feature Area:** `bot/checkout/cart_manager.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Implement cart management: add item via retailer API (preferred) or UI Playwright automation (fallback). Verify item is in cart before proceeding. Handle errors (item OOS, quantity limit). Prevent duplicate adds for same SKU. Implement `max_cart_quantity` enforcement (CART-7) and retailer purchase limit precedence (CART-8). PRD Section 9.2 (CART-1 to CART-8).

---

**CHECKOUT-T02**
- **Title:** Implement CheckoutFlow orchestrator
- **Feature Area:** `bot/checkout/checkout_flow.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** CHECKOUT-T01, PAYMENT-T01, SHIPPING-T01
- **Description:** Implement `CheckoutFlow`: orchestrate multi-step checkout per retailer. Auto-fill shipping and payment from config. Handle order review step. Apply randomized human-like delay (300ms ±50ms). Submit order and capture confirmation number. Implement retry logic (configurable N, default 2). Handle all failure modes from PRD Section 12. PRD Sections 9.3 (CO-1 to CO-10).

---

**CHECKOUT-T03**
- **Title:** Implement PaymentHandler
- **Feature Area:** `bot/checkout/payment.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Implement payment form autofill. Handle payment decline (retry once after 2s delay, abort on second decline). Fire PAYMENT_DECLINED webhook. Mask sensitive fields (card_number, cvv) in all logs. PRD Sections 9.3 (CO-2, CO-6), 10.3 (Security).

---

**CHECKOUT-T04**
- **Title:** Implement ShippingInfo autofill
- **Feature Area:** `bot/checkout/shipping.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Implement shipping form autofill from `ShippingInfo` config. Apply billing address same as shipping by default. PRD Section 9.3 (CO-1, CO-3).

---

### Phase 1.6 — Notifications

---

**NOTIF-T01**
- **Title:** Implement Discord webhook notifications
- **Feature Area:** `bot/notifications/discord.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T05
- **Description:** Implement `DiscordWebhook`: send POST to Discord webhook URL with embed-formatted payload. Include ISO-8601 timestamp and event type. Implement retry with exponential backoff (up to 3 retries). Queue events if network unavailable. Fire all events from PRD Section 8.2 webhook catalog. PRD Sections 9.6 (NOT-1, NOT-3, NOT-4, NOT-6).

---

**NOTIF-T02**
- **Title:** Implement Telegram webhook notifications
- **Feature Area:** `bot/notifications/telegram.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** NOTIF-T01
- **Description:** Implement `TelegramWebhook`: send formatted messages via Telegram Bot API. Same retry and queue behavior as Discord. PRD Sections 9.6 (NOT-2, NOT-3, NOT-4, NOT-6).

---

**NOTIF-T03**
- **Title:** Implement generic Webhook base class
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T05
- **Description:** Create base `WebhookClient` class with retry logic (exponential backoff, 3 retries), event queuing, HTTPS URL validation. Both Discord and Telegram inherit from this. PRD Sections 9.6 (NOT-3, NOT-4).

---

### Phase 1.7 — Stock Monitor Orchestration

---

**MON-T01**
- **Title:** Implement StockMonitor orchestration loop
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T02, ADAPTER-T03, ADAPTER-T04, CHECKOUT-T02, SESSION-T01, SESSION-T02
- **Description:** Implement `StockMonitor`: main orchestration loop. Load all configured items and retailers. Start monitoring per item. Detect OOS→IS transitions (MON-2). Route to checkout flow on stock detection. Handle graceful shutdown (MON-11): stop monitoring loop, close browser, persist state. PRD Sections 9.1, state machine Section 7.2.

---

**MON-T02**
- **Title:** Implement SKU-based stock detection
- **Feature Area:** `bot/monitor/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Implement SKU-based detection: exact match against known SKUs from config. Support both SKU-based (MON-3) and keyword-based (MON-4) detection per item. PRD Section 9.1 (MON-3, MON-4).

---

### Phase 1.8 — Daemon Entry Point

---

**DAEMON-T01**
- **Title:** Implement daemon.py entry point
- **Feature Area:** `daemon.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** MON-T01, SHARED-T02, SHARED-T04, SHARED-T05, SHARED-T06
- **Description:** Create `daemon.py`: background entry point that runs silently (no TUI). Load config, initialize logging, connect to state.db, start stock monitor loop. Register signal handlers for graceful shutdown (SIGTERM, SIGINT). Run under supervisor-compatible init. PRD Section 7.

---

## Phase 1.5 — Dashboard Core

### Phase 2.1 — Dashboard Auth

---

**AUTH-T01**
- **Title:** Implement PIN/password authentication
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T02
- **Description:** Implement `dashboard/auth.py`: PIN/password login with argon2 hashing. Store hashed PIN in `auth.db`. Session cookie management (httpOnly, sameSite=strict). 8-hour inactivity expiry. Role enforcement: Operator (full access) vs Viewer (read-only). PRD Sections 5, 9.7 (DSH-15), 10.3 (Security).

---

**AUTH-T02**
- **Title:** Implement session management middleware
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Implement FastAPI middleware for session validation on all `/api/*` routes (except `/login` and `/health`). Return 401 for invalid/expired sessions. Viewer role blocks all write operations. PRD Sections 5, 9.7 (DSH-15).

---

### Phase 2.2 — Dashboard Backend Routes

---

**ROUTE-T01**
- **Title:** Implement /api/status route
- **Feature Area:** `dashboard/routes/status.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/status`: return daemon state from `state.db` — daemon online/offline, active items list, per-retailer session health (green/yellow/red), last event timestamp, uptime seconds. PRD Section 9.7 (DSH-2).

---

**ROUTE-T02**
- **Title:** Implement /api/config routes (GET/PATCH)
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `GET /api/config` (fetch full config, masking sensitive fields) and `PATCH /api/config` (update config.yaml from form data, validate before saving). Sensitive fields masked as `****1234`. PRD Sections 9.8 (CFG-9, CFG-10), 9.7 (DSH-7).

---

**ROUTE-T03**
- **Title:** Implement /api/events/stream SSE route
- **Feature Area:** `dashboard/routes/events.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/events/stream` SSE endpoint: stream real-time events from daemon to dashboard. Daemon writes events to `state.db` and pushes via SSE. Dashboard JS consumes SSE and updates live event log. < 500ms latency target. PRD Sections 9.7 (DSH-3), 3 (Dashboard real-time latency < 500ms).

---

**ROUTE-T04**
- **Title:** Implement /api/monitor/start and /stop routes
- **Feature Area:** `dashboard/routes/monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02, SHARED-T02
- **Description:** Implement `POST /api/monitor/start` and `POST /api/monitor/stop`. Write commands to `state.db` command queue. Return confirmation. Both require confirmation dialog on frontend (DSH-4). PRD Section 9.7 (DSH-4).

---

**ROUTE-T05**
- **Title:** Implement /api/dryrun route
- **Feature Area:** `dashboard/routes/dryrun.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02, CHECKOUT-T02
- **Description:** Implement `POST /api/dryrun`: trigger full checkout flow without placing order. Stream output to a terminal panel via SSE. Validate config before running. PRD Sections 9.7 (DSH-6), 14 (Phase 1 exit criteria).

---

**ROUTE-T06**
- **Title:** Implement /health health check route
- **Feature Area:** `dashboard/routes/health.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Implement `GET /health`: returns HTTP 200 + JSON `{status, active_items, session_health, last_event_at, uptime_seconds}`. Does NOT require authentication. Used for daemon offline detection. PRD Sections 9.14 (OP-3, OP-4), 18.

---

**ROUTE-T07**
- **Title:** Implement /api/config/validate route
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `POST /api/config/validate`: runs full config validation, returns pass/fail with specific field-level error messages. PRD Sections 9.7 (DSH-8), 9.8 (CFG-2).

---

**ROUTE-T08**
- **Title:** Implement /api/config/reload hot-reload route
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `POST /api/config/reload`: re-reads config.yaml from disk, validates, and applies. If invalid, logs error and continues with previous config. PRD Sections 9.8 (CFG-8), 9.14 (OP-5).

---

**ROUTE-T09**
- **Title:** Implement /api/events/history route
- **Feature Area:** `dashboard/routes/events.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/events/history`: return last 500 events from `state.db` with filters (event type, retailer, item). PRD Sections 9.7 (DSH-12).

---

**ROUTE-T10**
- **Title:** Implement /api/daemon/restart route
- **Feature Area:** `dashboard/routes/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Implement `POST /api/daemon/restart`: signal daemon to restart. Write restart command to state.db. Dashboard shows "Daemon Offline" banner during restart. PRD Section 9.7 (DSH-16).

---

### Phase 2.3 — Dashboard Frontend

---

**FRONTEND-T01**
- **Title:** Implement dashboard login screen
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** AUTH-T01, ROUTE-T01
- **Description:** Implement dashboard login screen at `http://localhost:8080`. PIN/password form. Redirect to main dashboard on success. Shows on first launch. PRD Sections 9.7 (DSH-1), 9.7 (DSH-17).

---

**FRONTEND-T02**
- **Title:** Implement main status view
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T01, ROUTE-T03
- **Description:** Implement main status view: daemon online/offline indicator (green/red header), active items list, per-retailer session health (green/yellow/red), last event timestamp. PRD Section 9.7 (DSH-2).

---

**FRONTEND-T03**
- **Title:** Implement real-time event log panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T03
- **Description:** Implement SSE-powered live event log in dashboard: shows timestamp, event type, item, retailer for each event. Auto-scrolls. < 500ms update latency. PRD Sections 9.7 (DSH-3), 3.

---

**FRONTEND-T04**
- **Title:** Implement Start/Stop Monitoring buttons with confirmation
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T04
- **Description:** Implement "Start Monitoring" and "Stop Monitoring" buttons. Both require browser confirmation dialog to prevent accidental clicks. PRD Section 9.7 (DSH-4).

---

**FRONTEND-T05**
- **Title:** Implement item/retailer selector
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T02
- **Description:** Implement item selector: dropdown or card grid to select which item(s) and retailer(s) to monitor before starting. PRD Section 9.7 (DSH-5).

---

**FRONTEND-T06**
- **Title:** Implement dry-run output terminal panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T05
- **Description:** Implement "Run Dry Run" button and terminal output panel: full checkout flow output streamed via SSE to a terminal-style panel in the dashboard. PRD Sections 9.7 (DSH-6), 14.

---

**FRONTEND-T07**
- **Title:** Implement Settings page (config form)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ROUTE-T02, ROUTE-T07
- **Description:** Implement Settings page: all config.yaml fields editable via form. Retailer accounts, shipping, payment, CAPTCHA mode, daily budget. Inline field validation. No raw YAML editing. PRD Sections 9.7 (DSH-7), 9.8 (CFG-9, CFG-10).

---

**FRONTEND-T08**
- **Title:** Implement CAPTCHA panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02
- **Description:** Implement CAPTCHA panel: shows current mode (auto/manual/smart), daily spend vs. budget cap, per-retailer spend breakdown, solve time alerts. PRD Section 9.7 (DSH-9).

---

**FRONTEND-T09**
- **Title:** Implement Drop Window Calendar
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02, PHASE3-T01
- **Description:** Implement Drop Window Calendar: list upcoming drop events (datetime, timezone), add/edit/delete drop windows, auto-prewarm status per drop, per-drop `max_cart_quantity` field. PRD Sections 9.7 (DSH-10), 9.9.

---

**FRONTEND-T10**
- **Title:** Implement Multi-Account panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02
- **Description:** Implement Multi-Account panel: all configured accounts per retailer shown with session health, last prewarm time, enabled/disabled toggle. PRD Sections 9.7 (DSH-11), 9.10.

---

**FRONTEND-T11**
- **Title:** Implement Viewer role (read-only) UI
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Viewer role sees status, session health, event history, config summary. Start/stop/dry-run buttons hidden. No settings changes permitted. PRD Section 9.7 (DSH-15).

---

**FRONTEND-T12**
- **Title:** Implement Setup Wizard (first launch)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** AUTH-T01
- **Description:** Implement step-by-step Setup Wizard on first launch: set PIN/password → add first retailer account → enter shipping → enter payment → configure CAPTCHA mode. Inline help text. PRD Sections 9.7 (DSH-17), 5.

---

**FRONTEND-T13**
- **Title:** Implement Daemon Offline banner and Restart button
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T06, ROUTE-T10
- **Description:** Dashboard polls `/health` every 5s. If unreachable, shows prominent "Daemon Offline — restart required" banner with "Restart Daemon" button. PRD Sections 9.14 (OP-6), 18.

---

**FRONTEND-T14**
- **Title:** Implement logout functionality
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Implement operator logout button: ends session, clears cookie, returns to PIN/password login. PRD Section 9.7 (DSH-13).

---

**FRONTEND-T15**
- **Title:** Implement Event History page
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ROUTE-T09
- **Description:** Implement Event History page: searchable log of past events (last 500), filters by event type, retailer, item. PRD Section 9.7 (DSH-12).

---

**FRONTEND-T16**
- **Title:** Implement responsive layout (tablet 1024px+)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** FRONTEND-T02
- **Description:** Make dashboard responsive for tablet-sized screens (1024px minimum). Test on various viewport sizes. PRD Section 9.7 (DSH-14).

---

### Phase 2.4 — Dashboard Server

---

**SERVER-T01**
- **Title:** Implement FastAPI dashboard server
- **Feature Area:** `dashboard/server.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T01 through ROUTE-T10, AUTH-T02, FRONTEND-T01
- **Description:** Create `dashboard/server.py`: FastAPI app serving dashboard at `http://localhost:8080`. Mount static files. Include all routes. Uvicorn runs this. PRD Section 7.

---

**SERVER-T02**
- **Title:** Integrate dashboard with daemon via command queue
- **Feature Area:** `dashboard/server.py`, `daemon.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SERVER-T01, SHARED-T02, DAEMON-T01
- **Description:** Dashboard sends commands (start/stop/dry-run) by writing to `state.db` command queue table. Daemon polls command queue or uses file lock signal. Implement command/response pattern. PRD Section 7.1 (Daemon ↔ Dashboard communication).

---

## Phase 3 — Advanced Features

### Phase 3.1 — CAPTCHA Handling

---

**CAPTCHA-T01**
- **Title:** Implement CAPTCHA detection (reCAPTCHA, hCaptcha, Turnstile)
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Detect reCAPTCHA, hCaptcha, and Cloudflare Turnstile challenges on retailer pages. Use Playwright to identify CAPTCHA challenge presence and type. PRD Section 9.4 (CAP-1).

---

**CAPTCHA-T02**
- **Title:** Implement 2Captcha API integration
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T01, SHARED-T04
- **Description:** Implement 2Captcha integration: submit challenge with site key and page URL. Poll for solution with exponential backoff (max 120s timeout). Inject solution token into page. Log solve time in milliseconds. PRD Sections 9.4 (CAP-2, CAP-3, CAP-4, CAP-5).

---

**CAPTCHA-T03**
- **Title:** Implement Manual CAPTCHA Mode
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T01, NOTIF-T01
- **Description:** Implement manual CAPTCHA mode: when enabled, bot pauses on CAPTCHA challenge, fires `CAPTCHA_PENDING_MANUAL` webhook to Discord/Telegram with pause URL. Waits for operator to solve in browser. Resumes on completion or timeout (configurable, default 120s). PRD Sections 9.4 (CAP-8).

---

**CAPTCHA-T04**
- **Title:** Implement Smart CAPTCHA Routing
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T02, CAPTCHA-T03
- **Description:** Implement smart routing mode: Turnstile → auto-solve via 2Captcha (low cost, high pass rate); reCAPTCHA/hCaptcha → manual mode with operator alert. Default mode. PRD Sections 9.4 (CAP-9), 9.4.1 (smart mode table).

---

**CAPTCHA-T05**
- **Title:** Implement CAPTCHA Budget Tracker
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P2
- **Complexity:** M
- **Dependencies:** CAPTCHA-T02
- **Description:** Implement CAPTCHA budget tracker: daily budget cap ($5 default), per-retailer cap override, solve time alert threshold (60s default). Log cumulative daily spend. Fire webhook if daily cap exceeded. PRD Sections 9.4 (CAP-7), 9.4.2 (budget tracker table).

---

### Phase 3.2 — Drop Window Calendar

---

**PHASE3-T01**
- **Title:** Implement drop window data model and storage
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Extend config schema to support `drop_windows:` list. Each window: item name, retailer, drop datetime (ISO-8601 with timezone), prewarm minutes before, enabled flag. Validate on startup. Store in config.yaml. PRD Sections 9.9 (DWC-1, DWC-3), 11.

---

**PHASE3-T02**
- **Title:** Implement drop window auto-prewarm logic
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** PHASE3-T01, SESSION-T01
- **Description:** Implement auto-prewarm: when countdown reaches `prewarm_minutes` for a drop window, automatically start session pre-warming. Multiple drop windows can be active simultaneously. PRD Sections 9.9 (DWC-2, DWC-4).

---

**PHASE3-T03**
- **Title:** Implement past drop window pruning
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T01
- **Description:** On startup, automatically prune past drop windows from active memory. PRD Section 9.9 (DWC-6).

---

**PHASE3-T04**
- **Title:** Implement DROP_WINDOW webhook events
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** PHASE3-T02, NOTIF-T01
- **Description:** Fire `DROP_WINDOW_APPROACHING` webhook at prewarm start and `DROP_WINDOW_OPEN` when drop time arrives. PRD Section 9.9 (DWC-5).

---

### Phase 3.3 — Drop Countdown Timer

---

**DCT-T01**
- **Title:** Implement manual drop time scheduling form
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T01
- **Description:** Implement "Schedule Drop" form: date/time picker with timezone selection. Operator enters known drop event. PRD Sections 9.13 (DCT-1), 9.7 (DSH-10).

---

**DCT-T02**
- **Title:** Implement countdown computation and prewarm trigger
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T02
- **Description:** Compute time until drop. When `time_until_drop <= prewarm_minutes`, auto-start session pre-warming. PRD Section 9.13 (DCT-2).

---

**DCT-T03**
- **Title:** Implement urgent PREWARM_URGENT webhook
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** DCT-T02, NOTIF-T01
- **Description:** If drop time is within 5 minutes and session is not pre-warmed, fire urgent `PREWARM_URGENT` webhook. PRD Section 9.13 (DCT-4).

---

**DCT-T04**
- **Title:** Implement recurring drop support (one-shot + cron-like)
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** PHASE3-T01
- **Description:** Support one-shot drops (single event) and recurring drops (cron-like schedule). PRD Section 9.13 (DCT-5).

---

### Phase 3.4 — Multi-Account Coordination

---

**MAC-T01**
- **Title:** Implement multi-account config structure
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Extend config to support multiple retailer accounts per retailer under `accounts:`. Each account stored as separate config block with credentials. PRD Sections 9.10 (MAC-1, MAC-6).

---

**MAC-T02**
- **Title:** Implement item-to-account assignment
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** MAC-T01
- **Description:** Items can be assigned to specific account(s) or spread round-robin across available accounts. Implement assignment logic. PRD Section 9.10 (MAC-2).

---

**MAC-T03**
- **Title:** Implement one-purchase-per-account enforcement
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** MAC-T02, SHARED-T02
- **Description:** Enforce one-purchase-per-account rule: same item cannot be purchased by two accounts in the same drop window. Track purchase state in state.db. PRD Section 9.10 (MAC-3).

---

**MAC-T04**
- **Title:** Implement parallel account pre-warming
- **Feature Area:** `bot/session/prewarmer.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SESSION-T01, MAC-T01
- **Description:** Account-level session pre-warming runs in parallel across all configured accounts using async. PRD Section 9.10 (MAC-4).

---

### Phase 3.5 — Social Listening

---

**SOCIAL-T01**
- **Title:** Implement Twitter/X social listening
- **Feature Area:** `bot/social/`
- **Priority:** P1
- **Complexity:** L
- **Dependencies:** SHARED-T04, NOTIF-T01
- **Description:** Implement Twitter/X listening via API v2: stream filtered tweets matching keywords. Parse tweet for URLs and item names. Keywords defined per monitored item. Fire social signal events. PRD Sections 9.11 (SCL-1, SCL-3, SCL-6).

---

**SOCIAL-T02**
- **Title:** Implement Discord channel social listening
- **Feature Area:** `bot/social/`
- **Priority:** P1
- **Complexity:** M
- **Dependencies:** NOTIF-T01
- **Description:** Listen to specific Discord channel IDs (not entire server). Match message content against item keywords. Read-only, no posting. PRD Sections 9.11 (SCL-2, SCL-5).

---

**SOCIAL-T03**
- **Title:** Implement Email IMAP social listening
- **Feature Area:** `bot/social/`
- **Priority:** P1
- **Complexity:** M
- **Dependencies:** SHARED-T04
- **Description:** Implement email IMAP listening: connect to IMAP server, watch inbox for emails matching item keywords. Parse subject/body for drop info. PRD Sections 9.11 (SCL-2).

---

**SOCIAL-T04**
- **Title:** Implement social signal → prewarm trigger
- **Feature Area:** `bot/social/`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SOCIAL-T01, DCT-T02
- **Description:** Social signal triggers prewarm for matching item/retailer. Requires operator confirmation for first use (never auto-checkout). PRD Section 9.11 (SCL-4).

---

**SOCIAL-T05**
- **Title:** Implement social listening mock mode
- **Feature Area:** `bot/social/`
- **Priority:** P2
- **Complexity:** S
- **Dependencies:** SOCIAL-T01
- **Description:** Implement `social_listening.mock = true` for testing without live API credentials. PRD Section 9.11 (SCL-8).

---

### Phase 3.6 — Queue/Waiting Room Handling

---

**QUEUE-T01**
- **Title:** Implement queue detection and auto-wait
- **Feature Area:** `bot/monitor/retailers/`
- **Priority:** P1
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Detect retailer queue/waiting room redirects. Fire `QUEUE_DETECTED` webhook. Auto-wait until queue clears. Fire `QUEUE_CLEARED` when through. Continue checkout. Timeout at 60s. PRD Sections 9.1 (MON-9), 12 (Queue/waiting room edge case).

---

### Phase 3.7 — Session Expiry Handling

---

**SESSION-T03**
- **Title:** Implement automatic session re-authentication
- **Feature Area:** `bot/session/`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SESSION-T02, ADAPTER-T02
- **Description:** Detect session expiration mid-checkout. Automatically re-authenticate using pre-warmed credentials. Restart checkout from cart. Fire `SESSION_EXPIRED` webhook on failure. PRD Sections 9.1 (MON-10), 12 (Session cookie expires edge case).

---

### Phase 3.8 — Dashboard "About" Page

---

**ABOUT-T01**
- **Title:** Implement dashboard About page with adapter plugin list
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ADAPTER-T05
- **Description:** Implement "About" page listing all loaded retailer adapter plugins: name, version, enabled/disabled status. PRD Section 9.15 (ADP-5).

---

## Phase 4 — Hardening + Polish

### Phase 4.1 — Testing

---

**TEST-T01**
- **Title:** Write unit tests for core bot logic
- **Feature Area:** `tests/test_bot/`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** PHASE1-ALL
- **Description:** Unit tests for: config validation (valid/invalid configs), jitter calculation, UA rotation uniqueness, state machine transitions, checkout retry logic. Target 80%+ coverage. pytest framework. PRD Section 15.

---

**TEST-T02**
- **Title:** Write retailer adapter unit tests with mocked responses
- **Feature Area:** `tests/test_bot/`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Adapter unit tests with mocked HTTP responses (responses library). Test each adapter method: login, check_stock, add_to_cart, checkout. Verify correct form field values sent. PRD Section 15.

---

**TEST-T03**
- **Title:** Write API route tests (FastAPI TestClient)
- **Feature Area:** `tests/test_dashboard/`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SERVER-T01
- **Description:** API route tests using FastAPI TestClient. Test: auth (login success/fail, session expiry, role enforcement), status endpoint, config GET/PATCH, monitor start/stop, health check. PRD Section 15.

---

**TEST-T04**
- **Title:** Write CAPTCHA integration tests with mocked 2Captcha
- **Feature Area:** `tests/test_bot/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** CAPTCHA-T02
- **Description:** Mock 2Captcha API responses. Verify token submission and injection. Test slow solve timeout (mock 120s+ delay). Test budget tracking. PRD Section 15.

---

**TEST-T05**
- **Title:** Write evasion tests
- **Feature Area:** `tests/test_bot/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** EVASION-T01, EVASION-T02
- **Description:** Verify UA rotation produces unique strings from pool. Verify fingerprint randomization produces different values across calls. Verify no automation signals leak. PRD Section 15.

---

**TEST-T06**
- **Title:** Write config validation tests
- **Feature Area:** `tests/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Test valid and invalid configs. Verify error messages are field-specific. Test environment variable overrides. PRD Section 15.

---

**TEST-T07**
- **Title:** Write integration tests (opt-in)
- **Feature Area:** `tests/`
- **Priority:** P1
- **Complexity:** XL
- **Dependencies:** TEST-T01 through TEST-T06
- **Description:** End-to-end dry-run tests against live retailer pages (opt-in via `pytest --run-integration`). May place orders. Test full flow: stock detection → cart → checkout. Only run manually. PRD Section 15.

---

### Phase 4.2 — Security Hardening

---

**SEC-T01**
- **Title:** Audit and mask all sensitive fields
- **Feature Area:** `shared/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** CHECKOUT-T03, SHARED-T04
- **Description:** Audit all logging and output paths. Ensure card_number, cvv, CVV, API keys are always masked (`****1234`) and never written to logs or stdout. CVV never stored post-checkout. PRD Sections 10.3, 16 (criterion 5).

---

**SEC-T02**
- **Title:** Implement httpOnly sameSite=strict session cookies
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Set httpOnly, sameSite=strict on all session cookies. 8-hour inactivity expiry. PRD Section 10.3 (Session cookies).

---

**SEC-T02**
- **Title:** Enforce OS-level file permissions on sensitive files
- **Feature Area:** `shared/`, `config.yaml`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02
- **Description:** Document and enforce `chmod 600` on `config.yaml`, `auth.db`, `state.db`. Add startup check that verifies permissions. PRD Section 17.

---

**SEC-T03**
- **Title:** Validate all webhook URLs are HTTPS
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** NOTIF-T03
- **Description:** Reject webhook URLs that are not HTTPS. Log warning. PRD Section 10.3 (Security).

---

**SEC-T04**
- **Title:** Implement dashboard path traversal protection
- **Feature Area:** `dashboard/server.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SERVER-T01
- **Description:** Dashboard serves only its own assets. No filesystem path traversal possible. Validate all file paths. PRD Section 10.3 (Security).

---

### Phase 4.3 — Logging & Observability

---

**LOG-T01**
- **Title:** Set up log rotation (10MB × 5 backups)
- **Feature Area:** `bot/logger.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T05
- **Description:** Configure `RotatingFileHandler`: 10MB max file size, 5 backup files. PRD Sections 10.3 (disk fill mitigation), 18.

---

**LOG-T02**
- **Title:** Type check with mypy (strict mode)
- **Feature Area:** `src/`
- **Priority:** P1
- **Complexity:** M
- **Dependencies:** PHASE1-ALL
- **Description:** Run mypy ≥1.8 with strict mode across all source files. Fix type errors. PRD Section 6 (type checking).

---

### Phase 4.4 — Non-Essential JS Blocking

---

**EVASION-T07**
- **Title:** Block non-essential JS (ads, analytics, tracking)
- **Feature Area:** `bot/evasion/`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Configure Playwright to block non-essential resources: ads, analytics, tracking pixels. Only load essential page assets. PRD Section 9.5 (EV-6).

---

### Phase 4.5 — Clear Cart Between Attempts

---

**CHECKOUT-T05**
- **Title:** Implement cart clearing between checkout attempts
- **Feature Area:** `bot/checkout/cart_manager.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** CHECKOUT-T01
- **Description:** On checkout failure, clear cart before retry. Verify cart is empty before adding new item. PRD Section 9.2 (CART-5).

---

### Phase 4.6 — Webhook Queue

---

**NOTIF-T04**
- **Title:** Implement webhook event queuing for network outages
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** NOTIF-T03
- **Description:** Queue webhook events if network is temporarily unavailable. Retry queued events when network recovers. PRD Section 9.6 (NOT-5).

---

### Phase 4.7 — Config Environment Variable Overrides

---

**CFG-T01**
- **Title:** Implement environment variable overrides for secrets
- **Feature Area:** `bot/config.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Load secrets from environment variables: `POKEDROP_2CAPTCHA_KEY`, `POKEDROP_DISCORD_URL`, `POKEDROP_TELEGRAM_TOKEN`, `POKEDROP_TELEGRAM_CHAT_ID`. Config file values are fallback. Production: env vars override config. PRD Section 9.8 (CFG-3), 10.3 (API keys from env vars).

---

---

## Dependency Graph Summary

```
SHARED-T01 → SHARED-T02, SHARED-T03, SHARED-T05
SHARED-T02 → SHARED-T06, SESSION-T02, MON-T01, CHECKOUT-T01, AUTH-T01
SHARED-T03 → SHARED-T04, ADAPTER-T01
SHARED-T04 → ADAPTER-T01, EVASION-T04, CAPTCHA-T02, CAPTCHA-T05, MAC-T01, SOCIAL-T01
SHARED-T05 → NOTIF-T03

ADAPTER-T01 → ADAPTER-T02, ADAPTER-T03, ADAPTER-T04, ADAPTER-T05
ADAPTER-T02 → EVASION-T01, EVASION-T02, EVASION-T03, EVASION-T05, EVASION-T06
ADAPTER-T05 → ADAPTER-T02, ABOUT-T01
EVASION-T01 → EVASION-T02
EVASION-T02 → ADAPTER-T02

SESSION-T01 → SESSION-T02, MAC-T04, PHASE3-T02
SESSION-T02 → SESSION-T03

CHECKOUT-T01 → CHECKOUT-T02, CHECKOUT-T05
CHECKOUT-T02 → CHECKOUT-T03, SHIPPING-T01
CHECKOUT-T03 → SEC-T01
PAYMENT-T01 → SEC-T01 (implicit via masked logging)

CAPTCHA-T01 → CAPTCHA-T02, CAPTCHA-T03
CAPTCHA-T02 → CAPTCHA-T04, CAPTCHA-T05
CAPTCHA-T03 → CAPTCHA-T04
CAPTCHA-T04 → CAPTCHA-T05

MON-T01 → DAEMON-T01
DAEMON-T01 → SERVER-T02
SERVER-T01 → SERVER-T02
SERVER-T02 → DAEMON-T01

AUTH-T01 → AUTH-T02, FRONTEND-T01, FRONTEND-T12, FRONTEND-T14
AUTH-T02 → ROUTE-T01 through ROUTE-T10, FRONTEND-T11

ROUTE-T01 → FRONTEND-T02
ROUTE-T02 → FRONTEND-T05, FRONTEND-T07, FRONTEND-T08, FRONTEND-T09, FRONTEND-T10
ROUTE-T03 → FRONTEND-T03
ROUTE-T04 → FRONTEND-T04
ROUTE-T05 → FRONTEND-T06
ROUTE-T06 → FRONTEND-T13
ROUTE-T07 → FRONTEND-T07
ROUTE-T09 → FRONTEND-T15
ROUTE-T10 → FRONTEND-T13

PHASE3-T01 → PHASE3-T02, PHASE3-T03, DCT-T01, DCT-T04
PHASE3-T02 → PHASE3-T04, DCT-T02, DCT-T03
PHASE3-T03 → (no dependents)
DCT-T01 → DCT-T02
DCT-T02 → DCT-T03

MAC-T01 → MAC-T02, MAC-T04
MAC-T02 → MAC-T03
MAC-T03 → (no dependents)
MAC-T04 → (no dependents)

SOCIAL-T01 → SOCIAL-T04, SOCIAL-T05
SOCIAL-T02 → SOCIAL-T04
SOCIAL-T03 → SOCIAL-T04

TEST-T01 → TEST-T07 (implicit)
PHASE1-ALL → TEST-T01, TEST-T02, TEST-T03, TEST-T04, TEST-T05, TEST-T06
```

---

## Priority Summary

### P0 Tasks (MVP — Must Complete)
| Task ID | Title | Feature Area | Complexity |
|---------|-------|--------------|------------|
| SHARED-T01 | Project structure + deps | shared/ | S |
| SHARED-T02 | SQLite state.db schema | shared/db.py | M |
| SHARED-T03 | Shared dataclasses/models | shared/models.py | S |
| SHARED-T04 | Config loading + validation | bot/config.py | M |
| SHARED-T05 | Structured logging + SSE | bot/logger.py | S |
| SHARED-T06 | Crash recovery | shared/ | S |
| ADAPTER-T01 | RetailerAdapter base class | retailers/base.py | M |
| ADAPTER-T02 | TargetAdapter | retailers/target.py | L |
| ADAPTER-T03 | WalmartAdapter | retailers/walmart.py | L |
| ADAPTER-T04 | BestBuyAdapter | retailers/bestbuy.py | L |
| ADAPTER-T05 | Adapter plugin registry | retailers/ | S |
| EVASION-T01 | UA rotation pool | evasion/user_agents.py | S |
| EVASION-T02 | Fingerprint randomization | evasion/fingerprint.py | M |
| EVASION-T03 | Proxy rotation | evasion/proxy.py | M |
| EVASION-T04 | Jitter on intervals | evasion/jitter.py | S |
| EVASION-T05 | IP rate limit backoff | evasion/ | S |
| EVASION-T06 | Respect robots.txt | evasion/ | S |
| SESSION-T01 | Session pre-warmer | session/prewarmer.py | M |
| SESSION-T02 | Session persistence/reuse | session/ | S |
| CHECKOUT-T01 | CartManager | checkout/cart_manager.py | M |
| CHECKOUT-T02 | CheckoutFlow orchestrator | checkout/checkout_flow.py | L |
| CHECKOUT-T03 | PaymentHandler | checkout/payment.py | S |
| CHECKOUT-T04 | ShippingInfo autofill | checkout/shipping.py | S |
| NOTIF-T01 | Discord webhook | notifications/discord.py | S |
| NOTIF-T02 | Telegram webhook | notifications/telegram.py | S |
| NOTIF-T03 | Webhook base class | notifications/webhook.py | S |
| MON-T01 | StockMonitor loop | monitor/stock_monitor.py | L |
| MON-T02 | SKU-based detection | monitor/ | S |
| DAEMON-T01 | daemon.py entry point | daemon.py | M |
| AUTH-T01 | PIN/password auth | dashboard/auth.py | M |
| AUTH-T02 | Session middleware | dashboard/auth.py | S |
| ROUTE-T01 | /api/status | routes/status.py | S |
| ROUTE-T02 | /api/config GET/PATCH | routes/config.py | M |
| ROUTE-T03 | /api/events/stream SSE | routes/events.py | S |
| ROUTE-T04 | /api/monitor/start, /stop | routes/monitor.py | S |
| ROUTE-T05 | /api/dryrun | routes/dryrun.py | S |
| ROUTE-T06 | /health | routes/health.py | S |
| ROUTE-T07 | /api/config/validate | routes/config.py | S |
| ROUTE-T08 | /api/config/reload | routes/config.py | S |
| ROUTE-T09 | /api/events/history | routes/events.py | S |
| ROUTE-T10 | /api/daemon/restart | routes/ | S |
| FRONTEND-T01 | Login screen | templates/index.html | M |
| FRONTEND-T02 | Main status view | templates/index.html | M |
| FRONTEND-T03 | Real-time event log | templates/index.html | S |
| FRONTEND-T04 | Start/Stop buttons | templates/index.html | S |
| FRONTEND-T05 | Item/retailer selector | templates/index.html | S |
| FRONTEND-T06 | Dry-run terminal panel | templates/index.html | S |
| FRONTEND-T07 | Settings page (config form) | templates/index.html | L |
| FRONTEND-T08 | CAPTCHA panel | templates/index.html | M |
| FRONTEND-T09 | Drop Window Calendar | templates/index.html | M |
| FRONTEND-T10 | Multi-Account panel | templates/index.html | M |
| FRONTEND-T11 | Viewer role (read-only) | templates/index.html | S |
| FRONTEND-T12 | Setup Wizard | templates/index.html | M |
| FRONTEND-T13 | Daemon Offline banner | templates/index.html | S |
| FRONTEND-T14 | Logout | templates/index.html | S |
| SERVER-T01 | FastAPI dashboard server | dashboard/server.py | M |
| SERVER-T02 | Dashboard-daemon integration | dashboard/server.py | M |
| CAPTCHA-T01 | CAPTCHA detection | checkout/captcha.py | S |
| CAPTCHA-T02 | 2Captcha integration | checkout/captcha.py | M |
| CAPTCHA-T03 | Manual CAPTCHA mode | checkout/captcha.py | M |
| CAPTCHA-T04 | Smart CAPTCHA routing | checkout/captcha.py | M |
| PHASE3-T01 | Drop window data model | bot/config.py | S |
| PHASE3-T02 | Drop window auto-prewarm | monitor/stock_monitor.py | M |
| PHASE3-T03 | Past drop pruning | bot/config.py | S |
| DCT-T01 | Manual drop scheduling form | templates/index.html | S |
| DCT-T02 | Countdown + prewarm trigger | monitor/stock_monitor.py | S |
| DCT-T03 | PREWARM_URGENT webhook | notifications/webhook.py | S |
| DCT-T04 | Recurring drops | bot/config.py | M |
| MAC-T01 | Multi-account config | bot/config.py | S |
| MAC-T02 | Item-to-account assignment | monitor/stock_monitor.py | S |
| MAC-T03 | One-purchase-per-account | monitor/stock_monitor.py | S |
| MAC-T04 | Parallel pre-warming | session/prewarmer.py | S |
| SEC-T01 | Mask sensitive fields | shared/ | S |
| SEC-T03 | HTTPS webhook validation | notifications/webhook.py | S |
| SEC-T04 | Path traversal protection | dashboard/server.py | S |
| LOG-T01 | Log rotation | bot/logger.py | S |
| TEST-T01 | Unit tests (core) | tests/test_bot/ | L |
| TEST-T02 | Adapter unit tests | tests/test_bot/ | M |
| TEST-T03 | API route tests | tests/test_dashboard/ | M |
| TEST-T04 | CAPTCHA integration tests | tests/test_bot/ | S |
| TEST-T05 | Evasion tests | tests/test_bot/ | S |
| TEST-T06 | Config validation tests | tests/ | S |

### P1 Tasks (Post-MVP — Important)
| Task ID | Title | Complexity |
|---------|-------|------------|
| CAPTCHA-T05 | CAPTCHA budget tracker | M |
| PHASE3-T04 | DROP_WINDOW webhook events | S |
| SOCIAL-T01 | Twitter/X listening | L |
| SOCIAL-T02 | Discord channel listening | M |
| SOCIAL-T03 | Email IMAP listening | M |
| SOCIAL-T04 | Social signal → prewarm | S |
| QUEUE-T01 | Queue detection + auto-wait | M |
| SESSION-T03 | Auto re-authentication | S |
| ABOUT-T01 | About page with adapter list | S |
| FRONTEND-T15 | Event history page | S |
| FRONTEND-T16 | Responsive layout | S |
| EVASION-T07 | Block non-essential JS | S |
| CHECKOUT-T05 | Cart clearing between attempts | S |
| NOTIF-T04 | Webhook queuing | S |
| CFG-T01 | Env var overrides for secrets | S |
| TEST-T07 | Integration tests (opt-in) | XL |
| LOG-T02 | mypy strict mode | M |
| SEC-T02 | httpOnly sameSite=strict cookies | S |

### P2 Tasks (Nice to Have)
| Task ID | Title | Complexity |
|---------|-------|------------|
| SOCIAL-T05 | Social listening mock mode | S |
| CAPTCHA-T05 | Daily cumulative spend log | M |

---

*Backlog generated from PokeBot_PRD.md v4.0. All PRD section references are from the source document.*
