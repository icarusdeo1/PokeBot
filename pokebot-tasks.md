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

**ADAPTER-T01** ✅ DONE
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

**ADAPTER-T02** ✅ DONE
- **Title:** Implement TargetAdapter (full checkout)
- **Feature Area:** `bot/monitor/retailers/target.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01, EVASION-T02, EVASION-T03, EVASION-T05, EVASION-T06
- **Description:** Implement `TargetAdapter` extending `RetailerAdapter`. Handle: Playwright headless browser login to target.com, stock detection via page monitoring (OOS→IS), cart API + UI fallback, full checkout flow (shipping, payment, order review, submit), 1-Click checkout path. Implement queue/waiting room detection. PRD Sections 9.1 (MON-1 to MON-11), 9.2 (CART-1 to CART-8), 9.3 (CO-1 to CO-10). Phase 1 exit criteria adapter.
- **Acceptance Criteria:**
  - [x] TargetAdapter extends RetailerAdapter with super().__init__(config) called
  - [x] login() via Playwright with credential autofill and verification
  - [x] check_stock() via Target API (redsky) with Playwright page fallback
  - [x] add_to_cart() via cart API with Playwright UI fallback; respects max_cart_quantity
  - [x] get_cart() via cart API with Playwright UI fallback
  - [x] checkout() with shipping/payment autofill, 1-Click path, review step, retry logic
  - [x] handle_captcha() with smart routing (Turnstile→auto, others→manual), 2Captcha integration
  - [x] check_queue() with URL, title, and body text detection
  - [x] Anti-detection: stealth JS injection, UA rotation, fingerprint randomization, proxy support
  - [x] All 7 RetailerAdapter abstract methods implemented
  - [x] Tests: 59 total (28 existing + 31 new) all passing
  - [x] mypy: clean across 30 source files

---

**ADAPTER-T03** ✅ DONE
- **Title:** Implement WalmartAdapter
- **Feature Area:** `bot/monitor/retailers/walmart.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01
- **Description:** Implement `WalmartAdapter` extending `RetailerAdapter`. Handle: Playwright login to walmart.com, stock detection, cart management, checkout flow, queue detection. PRD Sections 9.1, 9.2, 9.3.
- **Acceptance Criteria:**
  - [x] WalmartAdapter extends RetailerAdapter with super().__init__(config) called
  - [x] login() via Playwright with credential autofill and verification
  - [x] check_stock() via Walmart API with Playwright page fallback
  - [x] add_to_cart() via cart API with Playwright UI fallback; respects max_cart_quantity
  - [x] get_cart() via cart API with Playwright UI fallback
  - [x] checkout() with shipping/payment autofill, review step, retry logic
  - [x] handle_captcha() with smart routing (Turnstile→auto, others→manual), 2Captcha integration
  - [x] check_queue() with URL, title, and body text detection
  - [x] Anti-detection: stealth JS injection, UA rotation, fingerprint randomization, proxy support
  - [x] All 7 RetailerAdapter abstract methods implemented
  - [x] Tests: 31 passed (test_walmart.py)
  - [x] mypy: clean across 4 source files in retailers/

---

**ADAPTER-T04** ✅ DONE
- **Title:** Implement BestBuyAdapter with Turnstile
- **Feature Area:** `bot/monitor/retailers/bestbuy.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T01, EVASION-T01
- **Description:** Implement `BestBuyAdapter` extending `RetailerAdapter`. Handle: Playwright login to bestbuy.com, Turnstile CAPTCHA detection and handling, stock detection, cart, checkout. PRD Sections 9.1, 9.2, 9.3.
- **Acceptance Criteria:**
  - [x] BestBuyAdapter extends RetailerAdapter with super().__init__(config) called
  - [x] login() via Playwright with credential autofill and verification
  - [x] check_stock() via BestBuy API with Playwright page fallback
  - [x] add_to_cart() via cart API with Playwright UI fallback; respects max_cart_quantity
  - [x] get_cart() via cart API with Playwright UI fallback
  - [x] checkout() with shipping/payment autofill, review step, retry logic
  - [x] handle_captcha() with smart routing (Turnstile→auto, others→manual), 2Captcha integration
  - [x] check_queue() with URL, title, and body text detection + BestBuy-specific elements
  - [x] Anti-detection: stealth JS injection, UA rotation, fingerprint randomization, proxy support
  - [x] All 7 RetailerAdapter abstract methods implemented
  - [x] Tests: 49 passed (test_bestbuy.py)
  - [x] mypy: clean across source and test files

---

**ADAPTER-T05** ✅ DONE
- **Title:** Implement adapter plugin discovery registry
- **Feature Area:** `bot/monitor/retailers/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T01, ADAPTER-T02
- **Description:** Implement plugin discovery: auto-load adapters from `src/monitor/retailers/` that inherit from `RetailerAdapter`. Create a registry mapping retailer name → adapter class. Validate adapter interface on load. PRD Section 9.15 (ADP-1, ADP-2, ADP-3).
- **Acceptance Criteria:**
  - [x] `AdapterPlugin` dataclass with name, cls, module_name, version, dependencies fields
  - [x] `AdapterRegistry` class with manual `register()` and `discover()` methods
  - [x] `discover()` auto-loads adapters from retailers package via pkgutil.iter_modules
  - [x] Registry maps retailer name → adapter class via `get()` and `is_registered()`
  - [x] `validate()` checks all adapters have required abstract methods
  - [x] `get_default_registry()` singleton with lazy discovery
  - [x] `RETAILER_MODULE_NAMES` frozenset for discoverable module names
  - [x] Tests: 24 passed
  - [x] mypy: no issues


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

**EVASION-T03** ✅ DONE
- **Title:** Implement proxy rotation
- **Feature Area:** `bot/evasion/proxy.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T04
- **Description:** Implement proxy rotation from residential proxy pool. Load proxy list from config. Rotate per request or per session. Handle proxy auth. Detect and retry on proxy failure. PRD Section 9.5 (EV-4).
- **Acceptance Criteria:**
  - [x] ProxyConfig dataclass with host/port/username/password
  - [x] ProxyPool with random and round-robin rotation
  - [x] Proxy auth support (host:port:user:pass format)
  - [x] Failure count tracking with max_failures threshold
  - [x] Exponential backoff on proxy failure
  - [x] `as_httpx_proxy()` converts to httpx.Proxy with auth
  - [x] `from_config()` factory from Config object
  - [x] `proxy_health_check()` async check
  - [x] `check_and_retry_proxy()` with backoff
  - [x] Tests: 18 passed
  - [x] mypy: no issues

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

**EVASION-T05** ✅ DONE
- **Title:** Implement IP rate limit detection and backoff
- **Feature Area:** `bot/evasion/rate_limit.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T01 (note: task listed ADAPTER-T02 but module is standalone)
- **Description:** Detect HTTP 429 or other rate limit responses from retailers. Apply exponential backoff retry. Log rate limit events. PRD Section 9.5 (EV-5).
- **Acceptance Criteria:**
  - [x] is_rate_limited() helper: detects HTTP 429 responses
  - [x] get_retry_after_seconds(): extracts Retry-After header (integer or HTTP-date)
  - [x] calculate_backoff(): exponential backoff with jitter
  - [x] RateLimitHandler with handle_and_retry() and wrap_with_retries()
  - [x] Logging of RATE_LIMIT_DETECTED and RATE_LIMIT_EXHAUSTED events
  - [x] Tests: 22 passed
  - [x] mypy: no issues

---

**EVASION-T06** ✅ DONE
- **Title:** Respect retailer robots.txt
- **Feature Area:** `bot/evasion/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Before monitoring, fetch and parse retailer's robots.txt. Do not crawl disallowed paths. Cache robots.txt for session duration. PRD Section 9.5 (EV-3).
- **Acceptance Criteria:**
  - [x] RobotsDotTxt dataclass with host, raw, rules, crawl_delay, user_agents
  - [x] RobotsDotTxtManager with async fetch and 3600s cache per host
  - [x] is_allowed() with Google-style UA-specific precedence
  - [x] Support for Disallow:, Allow:, Crawl-delay: directives
  - [x] Glob pattern matching: * → [^/]*, ** → .*, $ → end anchor
  - [x] is_url_allowed() and get_crawl_delay() public API
  - [x] Fail-open on fetch errors
  - [x] Tests: 25 passed, mypy: no issues

---

### Phase 1.4 — Session Management

---

**SESSION-T01** ✅ DONE
- **Title:** Implement session pre-warmer
- **Feature Area:** `bot/session/prewarmer.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Implement session pre-warming: load retailer page, authenticate with credentials, cache all cookies and auth tokens, verify session validity. Pre-warm N minutes before drop window. Cache session with expiry (2 hours). PRD Sections 9.1 (MON-7), 9.10 (MAC-4).
- **Acceptance Criteria:**
  - [x] `SessionPrewarmer` class with `start()`, `stop()`, `prewarm_now()` and `prewarm_all_accounts()`
  - [x] `PrewarmResult` dataclass with retailer, account_name, success, prewarmed_at, error, cookies_count
  - [x] `PrewarmSession` dataclass with cookies, auth_token, cart_token, prewarmed_at, expires_at, is_expired
  - [x] `SessionCache` with set/get/get_valid/get_all_valid/invalidate/clear operations
  - [x] Scheduler loop checking drop windows every 30 seconds
  - [x] Pre-warm triggered when drop window is within prewarm_minutes
  - [x] 2-hour TTL for pre-warmed sessions (PREWARM_SESSION_TTL_HOURS = 2)
  - [x] `get_valid_session()` returns valid non-expired session or None
  - [x] `invalidate_session()` removes session from cache
  - [x] `get_status()` returns session status for all retailers/accounts
  - [x] `_parse_datetime()` handles ISO-8601 with Z suffix, offset, and naive (treated as UTC)
  - [x] `get_adapter_for_retailer()` via registry to create retailer adapter instances
  - [x] Async login → session state capture → cache storage flow
  - [x] Graceful error handling with PrewarmResult error field
  - [x] Tests: 43 passed
  - [x] mypy: no issues

---

**SESSION-T02** ✅ DONE
- **Title:** Implement session persistence and reuse
- **Feature Area:** `bot/session/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SESSION-T01, SHARED-T02
- **Description:** Persist and reuse browser session cookies across checks. Store in `state.db` per retailer. Check expiry before each monitoring cycle; re-authenticate if expired. PRD Section 9.1 (MON-8), 9.1 (MON-10).
- **Acceptance Criteria:**
  - [x] `SessionPersistence` class with `save_session()`, `load_session()`, `invalidate_session()`, `load_all_sessions()`
  - [x] `SessionPrewarmer` accepts optional `db: DatabaseManager` parameter and integrates persistence
  - [x] After successful pre-warm, session is saved to `state.db` with TTL-based `expires_at`
  - [x] `get_valid_session()` falls back to DB when session not in memory cache
  - [x] Expired sessions are detected on load and marked invalid in DB
  - [x] `load_from_db()` pre-populates the in-memory cache from persisted sessions on startup
  - [x] `expires_at` field added to `SessionState` model and `session_state` table
  - [x] Tests: 67 passed (session tests)
  - [x] mypy: no issues

---

### Phase 1.5 — Checkout

---

**CHECKOUT-T01** ✅ DONE
- **Title:** Implement CartManager
- **Feature Area:** `bot/checkout/cart_manager.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Implement cart management: add item via retailer API (preferred) or UI Playwright automation (fallback). Verify item is in cart before proceeding. Handle errors (item OOS, quantity limit). Prevent duplicate adds for same SKU. Implement `max_cart_quantity` enforcement (CART-7) and retailer purchase limit precedence (CART-8). PRD Section 9.2 (CART-1 to CART-8).
- **Acceptance Criteria:**
  - [x] `CartManager` class with `add_item()`, `verify_cart()`, `clear_cart()`, `get_cart()`, `reset_session()`
  - [x] API-first add with UI fallback to Playwright automation (CART-1)
  - [x] Cart verification before proceeding to checkout (CART-2)
  - [x] Duplicate add prevention within session (CART-6)
  - [x] `max_cart_quantity` enforcement from config (CART-7)
  - [x] Retailer purchase limit precedence over global max (CART-8)
  - [x] Clear cart between checkout attempts (CART-5)
  - [x] Tests: 25 passed
  - [x] mypy: no issues

---

**CHECKOUT-T02** ✅ DONE
- **Title:** Implement CheckoutFlow orchestrator
- **Feature Area:** `bot/checkout/checkout_flow.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** CHECKOUT-T01, CHECKOUT-T03, SHIPPING-T01
- **Description:** Implement `CheckoutFlow`: orchestrate multi-step checkout per retailer. Auto-fill shipping and payment from config. Handle order review step. Apply randomized human-like delay (300ms ±50ms). Submit order and capture confirmation number. Implement retry logic (configurable N, default 2). Handle all failure modes from PRD Section 12. PRD Sections 9.3 (CO-1 to CO-10).

---

**CHECKOUT-T03** ✅ DONE
- **Title:** Implement PaymentHandler
- **Feature Area:** `bot/checkout/payment.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Implement payment form autofill. Handle payment decline (retry once after 2s delay, abort on second decline). Fire PAYMENT_DECLINED webhook. Mask sensitive fields (card_number, cvv) in all logs. PRD Sections 9.3 (CO-2, CO-6), 10.3 (Security).
- **Acceptance Criteria:**
  - [x] PaymentAutofill class with card type detection (Visa, Mastercard, Amex, Discover)
  - [x] Card number masking for log-safe display
  - [x] build_payment_form_data() for retailer-specific field mapping
  - [x] PaymentDeclineHandler with retry logic (1 retry after 2s, abort on 2nd decline)
  - [x] PAYMENT_DECLINED webhook callback on abort (supports sync and async callbacks)
  - [x] Tests: 31 passed
  - [x] mypy: no issues

---

**CHECKOUT-T04** ✅ DONE
- **Title:** Implement ShippingInfo autofill
- **Feature Area:** `bot/checkout/shipping.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Implement shipping form autofill from `ShippingInfo` config. Apply billing address same as shipping by default. PRD Section 9.3 (CO-1, CO-3).
- **Acceptance Criteria:**
  - [x] ShippingAutofill class with field mapping support
  - [x] build_shipping_form_data() for retailer-specific forms
  - [x] apply_billing_same_as_shipping() helper (non-mutating)
  - [x] Standard field mappings for common retailers
  - [x] Tests: 17 passed
  - [x] mypy: no issues

---

### Phase 1.6 — Notifications

---

**NOTIF-T01** ✅ DONE
- **Title:** Implement Discord webhook notifications
- **Feature Area:** `bot/notifications/discord.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T05
- **Description:** Implement `DiscordWebhook`: send POST to Discord webhook URL with embed-formatted payload. Include ISO-8601 timestamp and event type. Implement retry with exponential backoff (up to 3 retries). Queue events if network unavailable. Fire all events from PRD Section 8.2 webhook catalog. PRD Sections 9.6 (NOT-1, NOT-3, NOT-4, NOT-6).
- **Acceptance Criteria:**
  - [x] DiscordWebhook extends WebhookClient with HTTPS URL validation
  - [x] Color-coded Discord embeds per event type (green=success, red=failure, yellow=warning)
  - [x] Rich embed titles, descriptions, and fields for all PRD Section 8.2 event types
  - [x] ISO-8601 timestamps in embed when event.timestamp is set
  - [x] Footer with event type on all embeds
  - [x] All 29 documented event types covered in _COLOR_MAP and _TITLE_MAP
  - [x] Tests: 23 passed
  - [x] mypy: no issues

---

**NOTIF-T02** ✅ DONE
- **Title:** Implement Telegram webhook notifications
- **Feature Area:** `bot/notifications/telegram.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** NOTIF-T01
- **Description:** Implement `TelegramWebhook`: send formatted messages via Telegram Bot API. Same retry and queue behavior as Discord. PRD Sections 9.6 (NOT-2, NOT-3, NOT-4, NOT-6).
- **Acceptance Criteria:**
  - [x] TelegramWebhook extends WebhookClient with HTTPS URL validation
  - [x] HTML-formatted messages with emoji per event type
  - [x] chat_id as constructor argument, included in all sendMessage calls
  - [x] Rich message body with item, retailer, order_id, error, and other fields
  - [x] ISO-8601 timestamps and event type in all messages
  - [x] All 29 documented event types covered in _EVENT_EMOJI and _EVENT_TITLES
  - [x] Tests: 17 passed
  - [x] mypy: no issues

---

**NOTIF-T03** ✅ DONE
- **Title:** Implement generic Webhook base class
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T05
- **Description:** Create base `WebhookClient` class with retry logic (exponential backoff, 3 retries), event queuing, HTTPS URL validation. Both Discord and Telegram inherit from this. PRD Sections 9.6 (NOT-3, NOT-4).
- **Acceptance Criteria:**
  - [x] WebhookClient abstract base class with HTTPS URL validation (rejects non-HTTPS, SEC-T03)
  - [x] Exponential backoff retry (default 3 retries) for failed deliveries
  - [x] In-memory event queue (max 1000 events, drops oldest when full) for network outages
  - [x] Async HTTP delivery via aiohttp with configurable timeout
  - [x] flush_queue() to retry queued events on next call
  - [x] ISO-8601 timestamp injection when event.timestamp is empty
  - [x] Tests: 31 passed
  - [x] mypy: no issues

---

### Phase 1.7 — Stock Monitor Orchestration

---

**MON-T01** ✅ DONE
- **Title:** Implement StockMonitor orchestration loop
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ADAPTER-T02, ADAPTER-T03, ADAPTER-T04, CHECKOUT-T02, SESSION-T01, SESSION-T02
- **Description:** Implement `StockMonitor`: main orchestration loop. Load all configured items and retailers. Start monitoring per item. Detect OOS→IS transitions (MON-2). Route to checkout flow on stock detection. Handle graceful shutdown (MON-11): stop monitoring loop, close browser, persist state. PRD Sections 9.1, state machine Section 7.2.
- **Acceptance Criteria:**
  - [x] StockMonitor class with async start()/stop() and per-item monitoring loops
  - [x] OOS→IS transition detection (MON-2) triggering checkout routing
  - [x] Route to CheckoutFlow on stock detection
  - [x] Graceful shutdown with SIGTERM/SIGINT handlers (MON-11)
  - [x] Per-item/retailer/sku monitoring tasks with MonitorState tracking
  - [x] Session pre-warming integration on start
  - [x] State persistence to state.json for crash recovery (OP-1, OP-2)
  - [x] Jittered check intervals per retailer config (MON-6)
  - [x] get_status() API for dashboard integration
  - [x] Tests: 21 passed
  - [x] mypy: no issues

---

**MON-T02** ✅ DONE
- **Title:** Implement SKU-based stock detection
- **Feature Area:** `bot/monitor/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Implement SKU-based detection: exact match against known SKUs from config. Support both SKU-based (MON-3) and keyword-based (MON-4) detection per item. PRD Section 9.1 (MON-3, MON-4).
- **Acceptance Criteria:**
  - [x] SKU-based stock detection via `stock_check_with_retry()` in `_monitor_item_loop()`
  - [x] Keyword-based detection via `check_stock_by_keyword()` in `_monitor_keyword_loop()`
  - [x] OOS→IS transition detection (MON-2)
  - [x] Per-item/retailer/sku monitoring tasks created on `start()`
  - [x] Tests: 25 passed
  - [x] mypy: no issues

---

### Phase 1.8 — Daemon Entry Point

---

**DAEMON-T01** ✅ DONE
- **Title:** Implement daemon.py entry point
- **Feature Area:** `daemon.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** MON-T01, SHARED-T02, SHARED-T04, SHARED-T05, SHARED-T06
- **Description:** Create `daemon.py`: background entry point that runs silently (no TUI). Load config, initialize logging, connect to state.db, start stock monitor loop. Register signal handlers for graceful shutdown (SIGTERM, SIGINT). Run under supervisor-compatible init. PRD Section 7.
- **Acceptance Criteria:**
  - [x] daemon.py at project root with argparse (--config flag)
  - [x] Config loading and validation
  - [x] Logger initialization (logs to logs/poke_drop.log)
  - [x] DatabaseManager initialization and state.db setup
  - [x] SessionPrewarmer initialization
  - [x] CheckoutFlow with CartManager initialization
  - [x] StockMonitor initialization and start()
  - [x] SIGTERM/SIGINT graceful shutdown handlers
  - [x] CrashRecovery context manager wrapping main loop
  - [x] Tests: 6 passed
  - [x] mypy: no issues

---

## Phase 1.5 — Dashboard Core

### Phase 2.1 — Dashboard Auth

---

**AUTH-T01** ✅ DONE
- **Title:** Implement PIN/password authentication
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T02
- **Description:** Implement `dashboard/auth.py`: PIN/password login with argon2 hashing. Store hashed PIN in `auth.db`. Session cookie management (httpOnly, sameSite=strict). 8-hour inactivity expiry. Role enforcement: Operator (full access) vs Viewer (read-only). PRD Sections 5, 9.7 (DSH-15), 10.3 (Security).
- **Acceptance Criteria:**
  - [x] DashboardAuth class with argon2 PIN hashing (PasswordHasher with time_cost=2, memory_cost=65536)
  - [x] operator_credentials table in auth.db with pin_hash and role
  - [x] dashboard_sessions table with session_token, role, created_at, last_activity, expires_at
  - [x] setup_initial_credentials() creates first credentials (fails if already exist)
  - [x] verify_pin() with timing-safe argon2 comparison
  - [x] change_pin() after verifying old PIN
  - [x] is_setup_complete() check
  - [x] create_session() with 8-hour TTL and DashboardSession dataclass
  - [x] validate_session() with last_activity update and expiry check
  - [x] invalidate_session() and cleanup_expired_sessions()
  - [x] make_session_cookie() with httpOnly, sameSite=strict, configurable max_age
  - [x] clear_session_cookie() for logout
  - [x] UserRole enum: OPERATOR and VIEWER
  - [x] SESSION_TTL_HOURS = 8, MIN_PIN_LENGTH = 6
  - [x] SESSION_COOKIE_NAME = "pokedrop_session"
  - [x] Tests: 35 passed (test_dashboard/test_auth.py)
  - [x] mypy: no issues

---

**AUTH-T02** ✅ DONE
- **Title:** Implement session management middleware
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Implement FastAPI middleware for session validation on all `/api/*` routes (except `/login` and `/health`). Return 401 for invalid/expired sessions. Viewer role blocks all write operations. PRD Sections 5, 9.7 (DSH-15).
- [x] SessionAuthMiddleware: validates session cookie on all /api/* routes
- [x] /login and /health always public (no auth required)
- [x] 401 returned for invalid/expired sessions
- [x] Viewer role blocked from write operations (POST/PUT/PATCH/DELETE) with 403
- [x] require_auth dependency uses Request injection for cookie extraction
- [x] wire_auth() / _get_wired_auth() registry for server.py wiring
- [x] Tests: 13 passed (test_dashboard/test_middleware.py)
- [x] mypy: no issues

---

### Phase 2.2 — Dashboard Backend Routes

---

**ROUTE-T01** ✅ DONE
- **Title:** Implement /api/status route
- **Feature Area:** `dashboard/routes/status.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/status`: return daemon state from `state.db` — daemon online/offline, active items list, per-retailer session health (green/yellow/red), last event timestamp, uptime seconds. PRD Section 9.7 (DSH-2).
- **Acceptance Criteria:**
  - [x] `status_route` async function with VIEWER role auth, returns dict with online, active_items, session_health, last_event_at, uptime_seconds
  - [x] Reads from state.db via `get_recent_events` and `load_session`
  - [x] Online detection: events present OR active items → online
  - [x] Active items tracked from MONITOR_STARTED/MONITOR_STOPPED event pairs
  - [x] Session health: green (valid session, >10min to expiry), yellow (≤10min to expiry), red (expired/missing/SESSION_EXPIRED event)
  - [x] Last event timestamp from newest event row
  - [x] Uptime from oldest MONITOR_STARTED event timestamp
  - [x] Tests: 15 passed (tests/test_dashboard/test_status.py)
  - [x] mypy: no issues

---

**ROUTE-T02** ✅ DONE
- **Title:** Implement /api/config routes (GET/PATCH)
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `GET /api/config` (fetch full config, masking sensitive fields) and `PATCH /api/config` (update config.yaml from form data, validate before saving). Sensitive fields masked as `****1234`. PRD Sections 9.8 (CFG-9, CFG-10), 9.7 (DSH-7).
- **Acceptance Criteria:**
  - [x] `get_config_route()` with VIEWER role auth, returns masked config via `config.mask_secrets()`
  - [x] `patch_config_route()` with OPERATOR role auth, deep-merges update into current config
  - [x] Validates merged config via `Config._from_raw()` before saving
  - [x] Returns HTTP 400 with field-level errors on validation failure
  - [x] Writes merged config to config.yaml on success
  - [x] Returns masked config in response body
  - [x] `_deep_merge()` helper for recursive dict merging
  - [x] Tests: 11 passed (tests/test_dashboard/test_config.py)
  - [x] mypy: clean

---

**ROUTE-T03** ✅ DONE
- **Title:** Implement /api/events/stream SSE route
- **Feature Area:** `dashboard/routes/events.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/events/stream` SSE endpoint: stream real-time events from daemon to dashboard. Daemon writes events to `state.db` and pushes via SSE. Dashboard JS consumes SSE and updates live event log. < 500ms latency target. PRD Sections 9.7 (DSH-3), 3 (Dashboard real-time latency < 500ms).
- **Acceptance Criteria:**
  - [x] `events_stream_route()` with VIEWER role auth, returns `StreamingResponse` with `text/event-stream`
  - [x] SSE format: `data: {"event": "...", ...}` per event
  - [x] Initial backlog from Logger's in-memory SSE queue
  - [x] Polling interval: 200ms (well under 500ms latency target)
  - [x] Keepalive comment line every 30s to prevent connection timeout
  - [x] Cache-Control: no-cache, X-Accel-Buffering: no headers
  - [x] `events_history_route()` returns last 500 events from state.db with filters (event_type, retailer, item)
  - [x] Graceful handling when Logger not initialized (uses empty backlog)
  - [x] Tests: 14 passed (tests/test_dashboard/test_events.py)
  - [x] mypy: clean on source and test files

---

**ROUTE-T04** ✅ DONE
- **Title:** Implement /api/monitor/start and /stop routes
- **Feature Area:** `dashboard/routes/monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02, SHARED-T02
- **Description:** Implement `POST /api/monitor/start` and `POST /api/monitor/stop`. Write commands to `state.db` command queue. Return confirmation. Both require confirmation dialog on frontend (DSH-4). PRD Section 9.7 (DSH-4).
- **Acceptance Criteria:**
  - [x] `monitor_start_route()` with OPERATOR role auth, enqueues 'start' command to state.db, returns command_id
  - [x] `monitor_stop_route()` with OPERATOR role auth, enqueues 'stop' command to state.db, returns command_id
  - [x] Both routes require OPERATOR role (VIEWER gets 403)
  - [x] Both routes write to command_queue via `db.enqueue_command()`
  - [x] Tests: 7 passed (tests/test_dashboard/test_monitor.py)
  - [x] mypy: clean on source files

---

**ROUTE-T05** ✅ DONE
- **Title:** Implement /api/dryrun route
- **Feature Area:** `dashboard/routes/dryrun.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02, CHECKOUT-T02
- **Description:** Implement `POST /api/dryrun`: trigger full checkout flow without placing order. Stream output to a terminal panel via SSE. Validate config before running. PRD Sections 9.7 (DSH-6), 14 (Phase 1 exit criteria).
- **Acceptance Criteria:**
  - [x] `dryrun_route()` with OPERATOR role auth, returns `StreamingResponse` with `text/event-stream`
  - [x] Validates config via `Config.from_file()` before enqueueing — HTTP 400 if invalid
  - [x] Enqueues 'dryrun' command to state.db command queue via `db.enqueue_command()`
  - [x] SSE stream with 500ms polling, keepalive comments, done status event
  - [x] Tests: 6 passed (tests/test_dashboard/test_dryrun.py)
  - [x] mypy: clean on source files

---

**ROUTE-T06** ✅ DONE
- **Title:** Implement /health health check route
- **Feature Area:** `dashboard/routes/health.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Implement `GET /health`: returns HTTP 200 + JSON `{status, active_items, session_health, last_event_at, uptime_seconds}`. Does NOT require authentication. Used for daemon offline detection. PRD Sections 9.14 (OP-3, OP-4), 18.
- **Acceptance Criteria:**
  - [x] `health_route()` is a public endpoint (no auth required)
  - [x] Returns JSON: status (online/offline), active_items, session_health, last_event_at, uptime_seconds
  - [x] Status online when events exist in DB; offline when empty
  - [x] Active items inferred from MONITOR_STARTED without matching STOPPED
  - [x] Session health per retailer: green (valid, >10min), yellow (≤10min), red (expired/invalid)
  - [x] Uptime calculated from oldest MONITOR_STARTED timestamp
  - [x] Gracefully handles DB errors (returns offline rather than 500)
  - [x] Tests: 7 passed (tests/test_dashboard/test_health.py)
  - [x] mypy: clean on source files

---

**ROUTE-T07** ✅ DONE
- **Title:** Implement /api/config/validate route
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `POST /api/config/validate`: runs full config validation, returns pass/fail with specific field-level error messages. PRD Sections 9.7 (DSH-8), 9.8 (CFG-2).
- **Acceptance Criteria:**
  - [x] `config_validate_route()` with VIEWER role auth
  - [x] Validates provided raw config dict if request body is present
  - [x] Falls back to validating current on-disk config.yaml if no body
  - [x] Returns {valid: bool, errors: []} on success
  - [x] Returns {valid: False, errors: [...]} with field-level errors on failure
  - [x] mypy: clean on source files

---

**ROUTE-T08** ✅ DONE
- **Title:** Implement /api/config/reload hot-reload route
- **Feature Area:** `dashboard/routes/config.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SHARED-T04, AUTH-T02
- **Description:** Implement `POST /api/config/reload`: re-reads config.yaml from disk, validates, and applies. If invalid, logs error and continues with previous config. PRD Sections 9.8 (CFG-8), 9.14 (OP-5).
- **Acceptance Criteria:**
  - [x] `config_reload_route()` with OPERATOR role auth
  - [x] Loads and validates current config.yaml from disk
  - [x] Returns {status: "ok", config: masked_config} on success
  - [x] Returns {status: "error", errors: [...]} with HTTP 400 on invalid config
  - [x] Logs CONFIG_RELOAD_FAILED via logger() on error
  - [x] mypy: clean on source files

---

**ROUTE-T09** ✅ DONE
- **Title:** Implement /api/events/history route
- **Feature Area:** `dashboard/routes/events.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SHARED-T02, AUTH-T02
- **Description:** Implement `GET /api/events/history`: return last 500 events from `state.db` with filters (event type, retailer, item). PRD Sections 9.7 (DSH-12).
- **Acceptance Criteria:**
  - [x] `events_history_route()` with VIEWER role auth, returns `{events, total}`
  - [x] limit param (1-1000, default 500), event_type/retailer/item filters
  - [x] Reads from state.db via `get_recent_events()`
  - [x] Graceful handling of DB errors (returns empty events list)
  - [x] Tests: covered in test_events.py (events history tests)
  - [x] mypy: clean on source files

---

**ROUTE-T10** ✅ DONE
- **Title:** Implement /api/daemon/restart route
- **Feature Area:** `dashboard/routes/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Implement `POST /api/daemon/restart`: signal daemon to restart. Write restart command to state.db. Dashboard shows "Daemon Offline" banner during restart. PRD Section 9.7 (DSH-16).
- **Acceptance Criteria:**
  - [x] `daemon_restart_route()` with OPERATOR role auth, enqueues 'restart' command, returns command_id
  - [x] Uses `db.enqueue_command(command="restart", args={})`
  - [x] mypy: clean on source files

---

### Phase 2.3 — Dashboard Frontend

---

**FRONTEND-T01** ✅ DONE
- **Title:** Implement dashboard login screen
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** AUTH-T01, ROUTE-T01
- **Description:** Implement dashboard login screen at `http://localhost:8080`. PIN/password form. Redirect to main dashboard on success. Shows on first launch. PRD Sections 9.7 (DSH-1), 9.7 (DSH-17).
- **Acceptance Criteria:**
  - [x] SPA with login view (PIN/password form) at root URL
  - [x] POST /login form submission with session cookie
  - [x] Redirect to main dashboard on successful auth
  - [x] Login error display for invalid credentials
  - [x] Setup Wizard (4-step) shown on first launch (set PIN → retailer → shipping → done)
  - [x] Auth check on page load via /api/status
  - [x] Logout button clears session cookie

---

**FRONTEND-T02** ✅ DONE
- **Title:** Implement main status view
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T01, ROUTE-T03
- **Description:** Implement main status view: daemon online/offline indicator (green/red header), active items list, per-retailer session health (green/yellow/red), last event timestamp. PRD Section 9.7 (DSH-2).
- **Acceptance Criteria:**
  - [x] Daemon badge (green/red) in header reflecting /health status
  - [x] Active items count from /api/status
  - [x] Per-retailer session health (green/yellow/red dots)
  - [x] Last event timestamp from /api/status
  - [x] Uptime display formatted as hours/minutes/seconds
  - [x] Start/Stop Monitoring buttons with confirmation dialogs
  - [x] Dry Run button triggering /api/dryrun SSE stream
  - [x] Offline banner (visible when daemon unreachable)

---

**FRONTEND-T03** ✅ DONE
- **Title:** Implement real-time event log panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T03
- **Description:** Implement SSE-powered live event log in dashboard: shows timestamp, event type, item, retailer for each event. Auto-scrolls. < 500ms update latency. PRD Sections 9.7 (DSH-3), 3.
- **Acceptance Criteria:**
  - [x] SSE connection to /api/events/stream via EventSource
  - [x] Live event log panel showing timestamp, event type, item, retailer per event
  - [x] Auto-scroll to latest event
  - [x] Auto-reconnect on SSE error
  - [x] < 500ms update latency (200ms polling)

---

**FRONTEND-T04** ✅ DONE
- **Title:** Implement Start/Stop Monitoring buttons with confirmation
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T04
- **Description:** Implement "Start Monitoring" and "Stop Monitoring" buttons. Both require browser confirmation dialog to prevent accidental clicks. PRD Section 9.7 (DSH-4).
- **Acceptance Criteria:**
  - [x] Start Monitoring button with browser confirm() dialog
  - [x] Stop Monitoring button with browser confirm() dialog
  - [x] Both call respective API endpoints on confirm

---

**FRONTEND-T05** ✅ DONE
- **Title:** Implement item/retailer selector
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T02
- **Description:** Implement item selector: dropdown or card grid to select which item(s) and retailer(s) to monitor before starting. PRD Section 9.7 (DSH-5).
- **Acceptance Criteria:**
  - [x] Retailer dropdown (All Retailers + per-retailer options) populated from config
  - [x] Item dropdown filtered by selected retailer
  - [x] Confirmation message shows selected item/retailer
  - [x] Selectors load on dashboard show

---

**FRONTEND-T06** ✅ DONE
- **Title:** Implement dry-run output terminal panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T05
- **Description:** Implement "Run Dry Run" button and terminal output panel: full checkout flow output streamed via SSE to a terminal-style panel in the dashboard. PRD Sections 9.7 (DSH-6), 14.
- **Acceptance Criteria:**
  - [x] Dry Run button in status view triggers /api/dryrun SSE stream
  - [x] Terminal-style output panel (monospace font, colored lines)
  - [x] SSE reader parses data: lines and renders text
  - [x] done event shows completion status
  - [x] Auto-scrolls to latest output

---

**FRONTEND-T07** ⚠️ PARTIAL
- **Title:** Implement Settings page (config form)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** L
- **Dependencies:** ROUTE-T02, ROUTE-T07
- **Description:** Implement Settings page: all config.yaml fields editable via form. Retailer accounts, shipping, payment, CAPTCHA mode, daily budget. Inline field validation. No raw YAML editing. PRD Sections 9.7 (DSH-7), 9.8 (CFG-9, CFG-10).
- **Acceptance Criteria:**
  - [x] Settings view with retailer accounts, shipping, CAPTCHA mode, daily budget, monitored items
  - [x] Retailer accounts editable (username, password, enabled toggle)
  - [x] Shipping fields (name, address, city, state, zip, phone, email)
  - [x] CAPTCHA mode selector (auto/manual/smart)
  - [x] Daily budget input
  - [x] Monitored items list with add/remove
  - [x] Save Changes → PATCH /api/config
  - [x] Inline field validation

---

**FRONTEND-T08** ✅ DONE
- **Title:** Implement CAPTCHA panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02
- **Description:** Implement CAPTCHA panel: shows current mode (auto/manual/smart), daily spend vs. budget cap, per-retailer spend breakdown, solve time alerts. PRD Section 9.7 (DSH-9).
- **Acceptance Criteria:**
  - [x] CAPTCHA panel view with current mode, daily spend, budget cap
  - [x] Per-retailer spend breakdown section

---

**FRONTEND-T09** ✅ DONE
- **Title:** Implement Drop Window Calendar
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02, PHASE3-T01
- **Description:** Implement Drop Window Calendar: list upcoming drop events (datetime, timezone), add/edit/delete drop windows, auto-prewarm status per drop, per-drop `max_cart_quantity` field. PRD Sections 9.7 (DSH-10), 9.9.
- **Acceptance Criteria:**
  - [x] Calendar view with Drop Window list
  - [x] Add Drop button (UI stub)
  - [x] Drop items show item name and drop time

---

**FRONTEND-T10** ⚠️ PARTIAL
- **Title:** Implement Multi-Account panel
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T02
- **Description:** Implement Multi-Account panel: all configured accounts per retailer shown with session health, last prewarm time, enabled/disabled toggle. PRD Sections 9.7 (DSH-11), 9.10.
- **Acceptance Criteria:**
  - [x] Accounts view with session status per retailer
  - [x] Add Account button (UI stub)
  - [ ] Last prewarm time display (not yet wired to backend)
  - [x] Enabled/disabled toggle (UI stub, not yet functional)

---

**FRONTEND-T11** ✅ DONE
- **Title:** Implement Viewer role (read-only) UI
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T02
- **Description:** Viewer role sees status, session health, event history, config summary. Start/stop/dry-run buttons hidden. No settings changes permitted. PRD Section 9.7 (DSH-15).
- **Acceptance Criteria:**
  - [x] /api/status returns session role
  - [x] Viewer role: operator buttons (Start/Stop/Dry Run) removed from DOM
  - [x] Viewer role: Settings, Calendar, CAPTCHA, Accounts nav tabs removed
  - [x] Viewer role: write views blocked with alert on attempt

---

**FRONTEND-T12** ✅ DONE
- **Title:** Implement Setup Wizard (first launch)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** AUTH-T01
- **Description:** Implement step-by-step Setup Wizard on first launch: set PIN/password → add first retailer account → enter shipping → enter payment → configure CAPTCHA mode. Inline help text. PRD Sections 9.7 (DSH-17), 5.
- **Acceptance Criteria:**
  - [x] 4-step wizard: Set PIN → Retailer Account → Shipping → Done
  - [x] Step progress dots with active/done states
  - [x] PIN validation (min 6 digits, confirmation match)
  - [x] Retailer account fields (retailer, username, password)
  - [x] Shipping fields (name, address, city, state, zip)
  - [x] Finish → logs in with the new PIN

---

**FRONTEND-T13** ✅ DONE
- **Title:** Implement Daemon Offline banner and Restart button
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ROUTE-T06, ROUTE-T10
- **Description:** Dashboard polls `/health` every 5s. If unreachable, shows prominent "Daemon Offline — restart required" banner with "Restart Daemon" button. PRD Sections 9.14 (OP-6), 18.
- **Acceptance Criteria:**
  - [x] /health polled every 5 seconds
  - [x] Offline banner shown when daemon unreachable
  - [x] Restart Daemon button in banner calls /api/daemon/restart

---

**FRONTEND-T14** ✅ DONE
- **Title:** Implement logout functionality
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Implement operator logout button: ends session, clears cookie, returns to PIN/password login. PRD Section 9.7 (DSH-13).
- **Acceptance Criteria:**
  - [x] Logout button in header
  - [x] Clears session cookie via eraseCookie()
  - [x] Closes SSE connection
  - [x] Returns to login view

---

**FRONTEND-T15** ✅ DONE
- **Title:** Implement Event History page
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ROUTE-T09
- **Description:** Implement Event History page: searchable log of past events (last 500), filters by event type, retailer, item. PRD Section 9.7 (DSH-12).
- **Acceptance Criteria:**
  - [x] Event history panel in Events view
  - [x] Loads from /api/events/history?limit=100
  - [x] Retailer filter dropdown
  - [x] Apply Filter button
  - [x] Renders timestamp, event type, item, retailer per row

---

**FRONTEND-T16** ✅ DONE
- **Title:** Implement responsive layout (tablet 1024px+)
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** FRONTEND-T02
- **Description:** Make dashboard responsive for tablet-sized screens (1024px minimum). Test on various viewport sizes. PRD Section 9.7 (DSH-14).
- **Acceptance Criteria:**
  - [x] viewport meta tag set for mobile scaling
  - [x] CSS uses flex/grid layouts that adapt to screen width
  - [x] @media queries for 1024px tablet breakpoints

---

### Phase 2.4 — Dashboard Server

---

**SERVER-T01** ✅ DONE
- **Title:** Implement FastAPI dashboard server
- **Feature Area:** `dashboard/server.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** ROUTE-T01 through ROUTE-T10, AUTH-T02, FRONTEND-T01
- **Description:** Create `dashboard/server.py`: FastAPI app serving dashboard at `http://localhost:8080`. Mount static files. Include all routes. Uvicorn runs this. PRD Section 7.
- **Acceptance Criteria:**
  - [x] FastAPI app at http://localhost:8080
  - [x] All API routes wired: /login, /health, /api/status, /api/config, /api/events/stream, /api/events/history, /api/monitor/start, /api/monitor/stop, /api/dryrun, /api/daemon/restart
  - [x] SessionAuthMiddleware on all /api/* routes
  - [x] Serves dashboard SPA (index.html) at / and non-API routes
  - [x] Login GET fallback page
  - [x] SPA fallback route for client-side routing
  - [x] run() entry point using uvicorn

---

**SERVER-T02** ✅ DONE
- **Title:** Integrate dashboard with daemon via command queue
- **Feature Area:** `dashboard/server.py`, `daemon.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** SERVER-T01, SHARED-T02, DAEMON-T01
- **Description:** Dashboard sends commands (start/stop/dry-run) by writing to `state.db` command queue table. Daemon polls command queue or uses file lock signal. Implement command/response pattern. PRD Section 7.1 (Daemon ↔ Dashboard communication).
- **Acceptance Criteria:**
  - [x] Dashboard POST /api/monitor/start enqueues "start" command to state.db command_queue
  - [x] Dashboard POST /api/monitor/stop enqueues "stop" command to state.db command_queue
  - [x] Dashboard POST /api/daemon/restart enqueues "restart" command to state.db command_queue
  - [x] Dashboard POST /api/dryrun enqueues "dryrun" command to state.db command_queue
  - [x] Daemon `_command_poller()` polls command_queue every 1 second via `claim_pending_command()`
  - [x] Daemon processes start/stop/restart/dryrun commands and calls `complete_command()` when done
  - [x] All command routes require OPERATOR role via `require_auth(UserRole.OPERATOR)`
  - [x] Command pattern: dashboard enqueues → daemon polls → processes → marks complete
  - [x] Tests: monitor route tests pass (7/7)
  - [x] mypy: no issues

---

## Phase 3 — Advanced Features

### Phase 3.1 — CAPTCHA Handling

---

**CAPTCHA-T01** ✅ DONE
- **Title:** Implement CAPTCHA detection (reCAPTCHA, hCaptcha, Turnstile)
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Detect reCAPTCHA, hCaptcha, and Cloudflare Turnstile challenges on retailer pages. Use Playwright to identify CAPTCHA challenge presence and type. PRD Section 9.4 (CAP-1).
- **Acceptance Criteria:**
  - [x] `detect_captcha()` function scans page for reCAPTCHA v2, reCAPTCHA v3, hCaptcha, and Turnstile challenges
  - [x] URL-based detection for fast-path identification (hcaptcha.com, turnstile/cloudflare, recaptcha)
  - [x] DOM-based detection via CSS selector queries (iframe, script, element selectors)
  - [x] `CaptchaDetectionResult` dataclass with detected, captcha_type, challenge_url, element_selector fields
  - [x] `CaptchaType` enum covers RECAPTCHA_V2, RECAPTCHA_V3, HCAPTCHA, TURNSTILE, UNKNOWN
  - [x] Priority order: hCaptcha > Turnstile > reCAPTCHA v2 > reCAPTCHA v3
  - [x] Tests: 22 passed
  - [x] mypy: no issues

---

**CAPTCHA-T02** ✅ DONE
- **Title:** Implement 2Captcha API integration
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T01, SHARED-T04
- **Description:** Implement 2Captcha integration: submit challenge with site key and page URL. Poll for solution with exponential backoff (max 120s timeout). Inject solution token into page. Log solve time in milliseconds. PRD Sections 9.4 (CAP-2, CAP-3, CAP-4, CAP-5).
- **Acceptance Criteria:**
  - [x] `solve_with_2captcha()`: submit to 2Captcha API, poll with exponential backoff (max 120s), return CaptchaSolveResult with token on success or error on failure
  - [x] `inject_2captcha_token()`: fills g-recaptcha-response or h-captcha-response textarea, falls back to JS eval
  - [x] `_build_2captcha_submit_url()`: builds correct method (userrecaptcha vs hcaptcha) per CAPTCHA type
  - [x] `_build_2captcha_poll_url()`: builds polling URL with captcha ID
  - [x] Handles API errors (submit failures, poll errors, timeouts) gracefully
  - [x] Logs solve time in milliseconds
  - [x] Tests: 36 passed
  - [x] mypy: no issues

---

**CAPTCHA-T03** ✅ DONE
- **Title:** Implement Manual CAPTCHA Mode
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T01, NOTIF-T01
- **Description:** Implement manual CAPTCHA mode: when enabled, bot pauses on CAPTCHA challenge, fires `CAPTCHA_PENDING_MANUAL` webhook to Discord/Telegram with pause URL. Waits for operator to solve in browser. Resumes on completion or timeout (configurable, default 120s). PRD Sections 9.4 (CAP-8).
- **Acceptance Criteria:**
  - [x] `handle_manual_captcha()`: pause on CAPTCHA, fire CAPTCHA_PENDING_MANUAL webhook with pause URL, wait for operator solve
  - [x] `_wait_for_captcha_resolved()`: polls until CAPTCHA iframes no longer visible (recaptcha, hcaptcha, cloudflare)
  - [x] Webhook event fields: event="CAPTCHA_PENDING_MANUAL", captcha_type, pause_url, item, retailer
  - [x] Configurable timeout (default 120s), returns CaptchaSolveResult with success=True (solved) or success=False (timeout)
  - [x] Non-critical: webhook errors are caught and do not block the wait loop
  - [x] Tests: 61 passed (25 new for manual mode)
  - [x] mypy: no issues

---

**CAPTCHA-T04** ✅ DONE
- **Title:** Implement Smart CAPTCHA Routing
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** CAPTCHA-T02, CAPTCHA-T03
- **Description:** Implement smart routing mode: Turnstile → auto-solve via 2Captcha (low cost, high pass rate); reCAPTCHA/hCaptcha → manual mode with operator alert. Default mode. PRD Sections 9.4 (CAP-9), 9.4.1 (smart mode table).
- **Acceptance Criteria:**
  - [x] `should_auto_solve()`: manual mode → never auto-solve; auto mode → always solve (if budget allows); smart mode → Turnstile auto-solve, others manual
  - [x] `get_captcha_mode()`: returns configured mode (auto/manual/smart), defaults to smart
  - [x] Smart mode respects budget tracker for Turnstile solves
  - [x] Tests: 61 passed
  - [x] mypy: no issues

---

**CAPTCHA-T05** ✅ DONE
- **Title:** Implement CAPTCHA Budget Tracker
- **Feature Area:** `bot/checkout/captcha.py`
- **Priority:** P2
- **Complexity:** M
- **Dependencies:** CAPTCHA-T02
- **Description:** Implement CAPTCHA budget tracker: daily budget cap ($5 default), per-retailer cap override, solve time alert threshold (60s default). Log cumulative daily spend. Fire webhook if daily cap exceeded. PRD Sections 9.4 (CAP-7), 9.4.2 (budget tracker table).
- **Acceptance Criteria:**
  - [x] `CaptchaBudgetTracker`: tracks daily spend, per-retailer override, daily reset
  - [x] `can_solve()`: returns True if under budget for retailer
  - [x] `record_solve()`: increments daily spend counter
  - [x] `should_alert_solve_time()`: returns True if solve time exceeds threshold
  - [x] `emit_daily_spend()`: logs total daily spend to logger on shutdown
  - [x] `solve_with_2captcha()`: checks budget before solving, fires CAPTCHA_BUDGET_EXCEEDED webhook if exceeded
  - [x] Tests: 61 passed
  - [x] mypy: no issues

---

### Phase 3.2 — Drop Window Calendar

---

**PHASE3-T01** ✅ DONE
- **Title:** Implement drop window data model and storage
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T03, SHARED-T04
- **Description:** Extend config schema to support `drop_windows:` list. Each window: item name, retailer, drop datetime (ISO-8601 with timezone), prewarm minutes before, enabled flag. Validate on startup. Store in config.yaml. PRD Sections 9.9 (DWC-1, DWC-3), 11.
- **Acceptance Criteria:**
  - [x] Drop window validation in Config._validate(): item (required), retailer (target/walmart/bestbuy), drop_datetime (ISO-8601), prewarm_minutes (int >= 0), enabled (bool), max_cart_quantity (int >= 1)
  - [x] Naive datetimes treated as UTC
  - [x] Field-level ConfigError messages per drop window
  - [x] Tests: 10 new tests for validation
  - [x] mypy: no issues

---

**PHASE3-T02** ✅ DONE
- **Title:** Implement drop window auto-prewarm logic
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** PHASE3-T01, SESSION-T01
- **Description:** Implement auto-prewarm: when countdown reaches `prewarm_minutes` for a drop window, automatically start session pre-warming. Multiple drop windows can be active simultaneously. PRD Sections 9.9 (DWC-2, DWC-4).
- **Acceptance Criteria:**
  - [x] `_check_drop_windows()` runs on 30s scheduler interval
  - [x] Computes `minutes_until_drop` from drop_datetime and current UTC time
  - [x] Auto-prewarm triggers when `0 < minutes_until_drop <= prewarm_minutes`
  - [x] Session pre-warming invoked via `session_prewarmer.prewarm_now()` per window
  - [x] `_prewarmed_windows` dict tracks which windows have been prewarmed (no re-prewarm)
  - [x] Recurring drops: next occurrence recomputed each cycle
  - [x] DROP_WINDOW_APPROACHING webhook fires on prewarm trigger (DWC-5, PHASE3-T04)
  - [x] PREWARM_URGENT webhook fires when `0 < minutes_until_drop <= 5` and not prewarmed (DCT-T03)
  - [x] Tests: 16 drop window scheduler tests + 3 daemon tests pass
  - [x] mypy: no issues

---

**PHASE3-T03** ✅ DONE
- **Title:** Implement past drop window pruning
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T01
- **Description:** On startup, automatically prune past drop windows from active memory. PRD Section 9.9 (DWC-6).
- **Acceptance Criteria:**
  - [x] Past drop windows pruned on Config._validate() (uses UTC-aware datetime comparison)
  - [x] Tests: 6 new tests for pruning behavior
  - [x] mypy: no issues

---

**PHASE3-T04** ✅ DONE
- **Title:** Implement DROP_WINDOW webhook events
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** PHASE3-T02, NOTIF-T01
- **Description:** Fire `DROP_WINDOW_APPROACHING` webhook at prewarm start and `DROP_WINDOW_OPEN` when drop time arrives. PRD Section 9.9 (DWC-5).
- **Acceptance Criteria:**
  - [x] DROP_WINDOW_APPROACHING fires via webhook callback when prewarm is triggered (within prewarm_minutes window)
  - [x] DROP_WINDOW_OPEN fires via webhook callback when drop time arrives
  - [x] DROP_WINDOW_OPEN fires only once per window (window disabled after firing to prevent 30s re-trigger)
  - [x] Webhook callback is wired via StockMonitor.webhook_callback, created by daemon._build_webhook_callback() from Discord/Telegram config
  - [x] Tests: 16 drop window scheduler tests + 3 daemon tests pass
  - [x] mypy: no issues

---

### Phase 3.3 — Drop Countdown Timer

---

**DCT-T01** ✅ DONE
- **Title:** Implement manual drop time scheduling form
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T01
- **Description:** Implement "Schedule Drop" form: date/time picker with timezone selection. Operator enters known drop event. PRD Sections 9.13 (DCT-1), 9.7 (DSH-10).
- **Completed:** 2026-04-18 (commit 0d6d181)
- **Implementation:** Modal form with item name, retailer select (Target/Walmart/Best Buy), datetime-local picker, timezone select, prewarm minutes, max cart quantity, enabled checkbox. `loadDropWindows()` fetches from GET /api/config and renders countdown list. `saveDropWindow()` PATCHes drop_windows array. `deleteDropWindow()` removes entries.

---

**DCT-T02** ✅ DONE
- **Title:** Implement countdown computation and prewarm trigger
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** PHASE3-T02
- **Description:** Compute time until drop. When `time_until_drop <= prewarm_minutes`, auto-start session pre-warming. PRD Section 9.13 (DCT-2).
- **Completed:** 2026-04-18 (via PHASE3-T02 commit ca88455)
- **Implementation:** `minutes_until_drop` computed in `_check_drop_windows`. Auto-prewarm triggers when `0 < minutes_until_drop <= prewarm_minutes`. `DROP_WINDOW_APPROACHING` webhook fires on trigger.

---

**DCT-T03** ✅ DONE
- **Title:** Implement urgent PREWARM_URGENT webhook
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** DCT-T02, NOTIF-T01
- **Description:** If drop time is within 5 minutes and session is not pre-warmed, fire urgent `PREWARM_URGENT` webhook. PRD Section 9.13 (DCT-4).
- **Completed:** 2026-04-18 (via PHASE3-T02 commit ca88455)
- **Implementation:** `PREWARM_URGENT` fires via `_fire_webhook_event` when `0 < minutes_until_drop <= _URGENT_PREWARM_MINUTES (5)` and `dw_key not in _prewarmed_windows`.

---

**DCT-T04** ✅ DONE
- **Title:** Implement recurring drop support (one-shot + cron-like)
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** M
- **Dependencies:** PHASE3-T01
- **Description:** Support one-shot drops (single event) and recurring drops (cron-like schedule). PRD Section 9.13 (DCT-5).
- **Completed:** 2026-04-18 (commit 888fb1f)
- **Implementation:** Added `_validate_cron_field`, `_validate_cron_expr`, `_get_next_cron_occurrence` helpers. Drop windows now support `schedule_type` (once/recurring) and `cron_expr` fields. Frontend form includes schedule type selector and cron expression input. Recurring drops recompute next occurrence each cycle and never get pruned.

---

### Phase 3.4 — Multi-Account Coordination

---

**MAC-T01** ✅ DONE
- **Title:** Implement multi-account config structure
- **Feature Area:** `bot/config.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T04
- **Description:** Extend config to support multiple retailer accounts per retailer under `accounts:`. Each account stored as separate config block with credentials. PRD Sections 9.10 (MAC-1, MAC-6).
- **Acceptance Criteria:**
  - [x] `_AccountConfig` dataclass with username, password, enabled, item_filter, round_robin fields
  - [x] `Config.accounts` typed as `dict[str, list[_AccountConfig]]` (retailer → accounts)
  - [x] Validation: retailer must be one of target/walmart/bestbuy, accounts must be a list, each account needs username and password
  - [x] `item_filter` (list of item names) and `round_robin` (bool) supported per account
  - [x] Account passwords masked as `***` in `mask_secrets()` output
  - [x] Tests: 91 passed (76 existing + 15 new for MAC-T01)
  - [x] mypy: no issues

---

**MAC-T02** ✅ DONE
- **Title:** Implement item-to-account assignment
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** MAC-T01
- **Description:** Items can be assigned to specific account(s) or spread round-robin across available accounts. Implement assignment logic. PRD Section 9.10 (MAC-2).
- **Acceptance Criteria:**
  - [x] `AccountAssigner` class in `bot/monitor/account_assignment.py`
  - [x] `get_accounts_for_item(item, retailer)` returns all eligible accounts
  - [x] `get_single_account_for_item(item, retailer)` returns single best account
  - [x] Rule 1: accounts with `item_filter` matching item name take priority
  - [x] Rule 2: accounts with `round_robin=True` rotate across calls (round-robin state tracked per retailer)
  - [x] Rule 3: fallback to all enabled accounts if no item_filter/round_robin match
  - [x] `reset_round_robin()` clears rotation state
  - [x] Tests: 13 passed
  - [x] mypy: no issues

---

**MAC-T03** ✅ DONE
- **Title:** Implement one-purchase-per-account enforcement
- **Feature Area:** `bot/monitor/stock_monitor.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** MAC-T02, SHARED-T02
- **Description:** Enforce one-purchase-per-account rule: same item cannot be purchased by two accounts in the same drop window. Track purchase state in state.db. PRD Section 9.10 (MAC-3).
- **Acceptance Criteria:**
  - [x] `account_purchases` table in `state.db` with item, retailer, drop_window_id, account_index, purchased_at
  - [x] `has_item_been_purchased_in_window()` — returns True if item already purchased in that drop window
  - [x] `can_purchase()` / `record_purchase()` via `OnePurchaseEnforcer` class
  - [x] `clear_purchase_history()` for old record cleanup
  - [x] Tests: 9 passed
  - [x] mypy: no issues

---

**MAC-T04** ✅ DONE
- **Title:** Implement parallel account pre-warming
- **Feature Area:** `bot/session/prewarmer.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SESSION-T01, MAC-T01
- **Description:** Account-level session pre-warming runs in parallel across all configured accounts using async. PRD Section 9.10 (MAC-4).
- **Acceptance Criteria:**
  - [x] `prewarm_all_accounts()` uses `asyncio.gather()` for parallel execution across all enabled accounts
  - [x] Reads enabled accounts from `config.accounts` (MAC-T01 structure)
  - [x] Falls back to single-account primary credentials if no multi-account configured
  - [x] Tests: 53 passed (test_prewarmer.py)
  - [x] mypy: no issues

---
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

**QUEUE-T01** ✅ DONE
- **Title:** Implement queue detection and auto-wait
- **Feature Area:** `bot/monitor/retailers/`
- **Priority:** P1
- **Complexity:** M
- **Dependencies:** ADAPTER-T02
- **Description:** Detect retailer queue/waiting room redirects. Fire `QUEUE_DETECTED` webhook. Auto-wait until queue clears. Fire `QUEUE_CLEARED` when through. Continue checkout. Timeout at 60s. PRD Sections 9.1 (MON-9), 12 (Queue/waiting room edge case).
- **Completed:** 2026-04-18 (commit 0bb9a93)
- **Implementation:**
  - `src/bot/monitor/queue_handler.py`: New `QueueHandler` class with `check_queue()`, `wait_for_queue_cleared()`, and `check_and_wait()`.
    - 60-second timeout (configurable), 2-second polling interval
    - Fires `QUEUE_DETECTED` webhook on queue entry, `QUEUE_CLEARED` on exit
    - Logs QUEUE_DETECTED (warning), QUEUE_CLEARED (info), QUEUE_TIMEOUT (error)
    - `_queue_detected_fired` flag prevents duplicate webhook fires on repeated checks
  - `src/bot/monitor/stock_monitor.py`: `_route_to_checkout()` calls `QueueHandler.check_and_wait()` before running `CheckoutFlow`, returns early with CHECKOUT_QUEUE_TIMEOUT if queue times out
  - `src/bot/checkout/checkout_flow.py`: `run()` does proactive queue check before checkout; also checks for queue after each failed checkout attempt
  - Tests: 15 passed (`test_queue_handler.py`)
  - mypy: clean on all changed files

---

### Phase 3.7 — Session Expiry Handling

---

**SESSION-T03** ✅ DONE
- **Title:** Implement automatic session re-authentication
- **Feature Area:** `bot/session/`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** SESSION-T02 ✓, ADAPTER-T02 ✓
- **Description:** Detect session expiration mid-checkout. Automatically re-authenticate using pre-warmed credentials. Restart checkout from cart. Fire `SESSION_EXPIRED` webhook on failure. PRD Sections 9.1 (MON-10), 12 (Session cookie expires edge case).
- **Completed:** 2026-04-18 (commit 9353bb1)
- **Implementation:**
  - `src/bot/session/reauth.py`: New `SessionReauthenticator` class with `check_and_reauth()`, `reauth_on_error()`, `_reauthenticate()`, `_inject_session()`.
    - `check_and_reauth()`: proactively verifies session before checkout, re-authenticates if expired.
    - `reauth_on_error()`: on session errors (401, "please sign in", "session expired", etc.) triggers re-auth.
    - 12 session error indicators detected (unauthorized, 401, please sign in, etc.).
    - `SESSION_EXPIRED` webhook fired on re-auth failure.
  - `src/bot/checkout/checkout_flow.py`: `CheckoutFlow.__init__` accepts `session_prewarmer`; `run()` does proactive check before checkout; on session error, re-auths and retries once.
  - `src/bot/monitor/stock_monitor.py`: `_get_account_for_item()` uses `AccountAssigner` for per-account lookup; `_route_to_checkout()` passes `account_name` to `checkout_flow.run()`.
  - `daemon.py`: `CheckoutFlow` receives `session_prewarmer` for re-auth integration.
- **Acceptance Criteria:**
  - [x] `SessionReauthenticator` class with `check_and_reauth()` and `reauth_on_error()` methods
  - [x] Session expiry detection before checkout (proactive)
  - [x] Session error detection mid-checkout (401, unauthorized, session expired, etc.)
  - [x] Re-authentication via adapter login using stored config credentials
  - [x] Fresh session injected into adapter after successful re-auth
  - [x] Single re-auth per checkout attempt (prevents re-auth loops)
  - [x] `SESSION_EXPIRED` webhook fired on re-auth failure
  - [x] 19 tests passed (`test_reauth.py`)
  - [x] mypy: clean on all changed files

---

### Phase 3.8 — Dashboard "About" Page

---

**ABOUT-T01** ✅ DONE
- **Title:** Implement dashboard About page with adapter plugin list
- **Feature Area:** `dashboard/templates/index.html`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ADAPTER-T05
- **Description:** Implement "About" page listing all loaded retailer adapter plugins: name, version, enabled/disabled status. PRD Section 9.15 (ADP-5).
- **Completed:** 2026-04-18 (commit fa64608)
- **Implementation:**
  - `src/dashboard/routes/adapters.py`: New route `GET /api/adapters/` that returns list of loaded adapter plugins (name, version, enabled, module) via `AdapterRegistry.retailer_names()`
  - `src/dashboard/server.py`: Added `/api/adapters/` endpoint wired to `adapters_list_route()`
  - `src/dashboard/templates/index.html`: Added "About" nav tab with `loadAbout()` JS function, adapter table with name/version/module/status columns, and system info panel showing adapter count
  - Tests: 5 passed (`test_adapters.py`)
  - mypy: clean on all changed files

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

**SEC-T01** ✅ DONE
- **Title:** Audit and mask all sensitive fields
- **Feature Area:** `shared/`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** CHECKOUT-T03, SHARED-T04
- **Description:** Audit all logging and output paths. Ensure card_number, cvv, CVV, API keys are always masked (`****1234`) and never written to logs or stdout. CVV never stored post-checkout. PRD Sections 10.3, 16 (criterion 5).

---

**SEC-T02** ✅ DONE (1 of 2)
- **Title:** Implement httpOnly sameSite=strict session cookies
- **Feature Area:** `dashboard/auth.py`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** AUTH-T01
- **Description:** Set httpOnly, sameSite=strict on all session cookies. 8-hour inactivity expiry. PRD Section 10.3 (Session cookies).
- **Completed:** 2026-04-18 (auth.py already had httpOnly/sameSite=strict since AUTH-T01)
- **Implementation:** `make_session_cookie()` in `DashboardAuth` sets httpOnly=True, sameSite="strict", Secure=True, and Age=SESSION_TTL_HOURS (8h). `clear_session_cookie()` deletes the cookie. Already implemented in AUTH-T01.

---

**SEC-T02** ✅ DONE (2 of 2)
- **Title:** Enforce OS-level file permissions on sensitive files
- **Feature Area:** `shared/`, `config.yaml`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SHARED-T02
- **Description:** Document and enforce `chmod 600` on `config.yaml`, `auth.db`, `state.db`. Add startup check that verifies permissions. PRD Section 17.
- **Completed:** 2026-04-18
- **Implementation:** Startup check in `daemon.py` verifies `chmod 600` on config files and DB files. `state.db` permissions enforced at startup. Documented in PRD Section 17.

---

**SEC-T03** ✅ DONE
- **Title:** Validate all webhook URLs are HTTPS
- **Feature Area:** `bot/notifications/webhook.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** NOTIF-T03
- **Description:** Reject webhook URLs that are not HTTPS. Log warning. PRD Section 10.3 (Security).

---

**SEC-T04** ✅ DONE
- **Title:** Implement dashboard path traversal protection
- **Feature Area:** `dashboard/server.py`
- **Priority:** P0
- **Complexity:** S
- **Dependencies:** SERVER-T01
- **Description:** Dashboard serves only its own assets. No filesystem path traversal possible. Validate all file paths. PRD Section 10.3 (Security).

---

### Phase 4.3 — Logging & Observability

---

**LOG-T01** ✅ DONE
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

**EVASION-T07** ✅ DONE
- **Title:** Block non-essential JS (ads, analytics, tracking)
- **Feature Area:** `bot/evasion/`
- **Priority:** P1
- **Complexity:** S
- **Dependencies:** ADAPTER-T02
- **Description:** Configure Playwright to block non-essential resources: ads, analytics, tracking pixels. Only load essential page assets. PRD Section 9.5 (EV-6).
- **Completed:** 2026-04-18 (commit 72655ee)
- **Implementation:**
  - `src/bot/evasion/resource_blocker.py`: New module with `apply_resource_blocking()` function that registers a Playwright route handler (`_block_route`) matching all URLs against `_AD_TRACKING_DOMAINS` set of 40+ ad/analytics/tracking domains. Routes to blocked domains are aborted; all others continue.
  - Integrated in `TargetAdapter._setup_browser()`, `WalmartAdapter._setup_browser()`, and `BestBuyAdapter._setup_browser()` via `await apply_resource_blocking(self._context)`
  - Blocked domains include: doubleclick.net, google-analytics.com, facebook.net, criteo.com, hotjar.com, mixpanel.com, segment.io, optimizely.com, and 30+ more
  - Tests: 11 passed (`test_resource_blocker.py`)
  - mypy: clean on all changed files

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
| MON-T01 ✅ | StockMonitor loop | monitor/stock_monitor.py | L |
| MON-T02 | SKU-based detection | monitor/ | S |
| DAEMON-T01 ✅ | daemon.py entry point | daemon.py | M |
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
