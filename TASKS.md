# PokeBot — Task Backlog
**Generated from:** PokeBot_PRD.md v3.0
**Stack:** Python 3.11+ · httpx · Playwright ≥1.40 · 2Captcha · PyYAML ≥6.0 · argparse · aiohttp · pytest ≥8.0 · mypy ≥1.8
**Repo:** greenfield (only PokeBot_PRD.md and prd-to-tasks.md exist)

---

## 0. Detected Stack

**PRD file selected:** `PokeBot_PRD.md` (repo root) — sole H1-marked product requirements document covering full auto-checkout system.

**Stack profile (inferred from PRD, not yet present in greenfield repo):**

| Component | Evidence | Tool |
|-----------|----------|------|
| Language: Python 3.11+ | PRD §6 Tech Stack | — |
| HTTP Client: httpx + asyncio | PRD §6 | `httpx ≥0.27`, `asyncio` stdlib |
| Browser Automation: Playwright | PRD §6 | `playwright ≥1.40` |
| CAPTCHA Solving: 2Captcha | PRD §6 | `2captcha-python` SDK |
| Config: YAML | PRD §6 | `PyYAML ≥6.0` |
| CLI: argparse | PRD §6 | stdlib |
| Notifications: aiohttp | PRD §6 | `aiohttp ≥3.9` |
| Testing: pytest | PRD §6 | `pytest ≥8.0`, `pytest-asyncio` |
| Type Checking: mypy | PRD §6 | `mypy ≥1.8` |

**CLAUDE.md / AGENTS.md overrides:** None present in repo.

---

## 1. PRD Summary & Goals

### Summary
PokeDrop Bot is a high-speed auto-checkout automation tool for Pokemon merchandise drops. It monitors retailer product pages (Target, Walmart, Best Buy) for stock availability via headless Playwright browser, detects OOS→IS transitions, and executes the full purchase flow — cart add, form fill, payment, order confirmation — faster than manual users can compete.

### Explicit Goals
- Detect stock within 500ms–1s of item going live
- Complete checkout: <10s Target, <15s Walmart, <5s Best Buy
- ≥85% success rate on pre-warmed sessions
- Fire all lifecycle webhook events (12 events defined)
- Multi-retailer support with swappable adapter pattern

### Implicit Goals
- The bot must survive retailer anti-bot measures (Turnstile, Cloudflare, JS challenges)
- Pre-warm sessions before drop window to avoid cold-start delays
- Retry logic on transient failures (payment declines, network drops)
- Config must be self-contained — no hardcoded values, zero-touch startup
- Operational transparency via structured logs and webhook events

### Non-Goals
- Bypassing paid CAPTCHA services (only integrating with them)
- Hacking or exploiting retailer systems
- Guaranteed purchase (retailer-side failures are out of bot control)
- Scalping engine / illegal profit extraction

### User Personas
| Persona | JTBD |
|---------|------|
| **Operator** | Configure items/retailers, start/stop monitoring, interpret logs, act on webhook alerts |
| **Viewer** | Read-only status and logs (future) |

---

## 2. Assumptions & Open Questions

### Default Assumptions (flagged for correction)

| # | Assumption | Rationale |
|---|-----------|-----------|
| A1 | Payment credentials stored in plaintext `config.yaml` with `chmod 600` | No secrets manager specified; OS-level permissions as compensating control |
| A2 | Single browser instance per retailer | Memory target <512MB implies 1 session per retailer |
| A3 | Per-retailer pre-warm minimum: 10 minutes | Based on Target queue behavior; faster retailers may need less |
| A4 | Max checkout retries: 2 | Industry standard; avoids duplicates while providing 1 retry |
| A5 | CAPTCHA solve timeout: 120s | 2Captcha typical solve time + buffer |
| A6 | Proxy rotation is Phase 3 (v2.0), not Phase 1 | Requires external proxy service procurement |
| A7 | Health check endpoint is Phase 3 (v2.0) | Operational tooling deferred post-MVP |
| A8 | Card CVV is never stored post-checkout | PCI-DSS surface reduction |
| A9 | Checkout stage-level failure tracking required | `CHECKOUT_FAILED` payload includes `stage` field for observability |
| A10 | No multi-machine coordination in v1–v2 | State is local to single process |

### Open Questions (for JM to resolve)

| # | Question | Impact |
|---|----------|--------|
| O1 | Will a dedicated card with a low limit be used for bot purchases? | Fraud flagging risk |
| O2 | Should the bot support multiple operator accounts sharing the same item? | Multi-account coordination scope |
| O3 | Is there a preferred residential proxy provider for v2.0? | Proxy rotation implementation |
| O4 | What is the expected monthly CAPTCHA solve budget? | Cost tracking and alerting |
| O5 | Should order confirmation IDs be stored locally for deduplication? | Crash recovery completeness |

---

## 3. Architecture Overview

### High-Level Component Map

```
┌─────────────────────────────────────────────────────────┐
│                        CLI (main.py)                     │
│            argparse: start/stop/status/dry-run           │
└────────────────┬──────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│                    Config Loader (config.py)             │
│              YAML schema validation + env overrides        │
└────────────────┬──────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│                 StockMonitor (stock_monitor.py)            │
│        State machine: STANDBY→STOCK_FOUND→CART_READY       │
│              One monitor instance per retailer             │
└────┬──────────────────────┬───────────────────────┬───────┘
     │                      │                       │
┌────▼────────┐    ┌─────────▼────────┐    ┌────────▼────────┐
│RetailerAdapter│   │ RetailerAdapter │    │RetailerAdapter │
│  (target.py)  │   │  (walmart.py)   │    │ (bestbuy.py)   │
│  P0: Phase 1  │   │  P0: Phase 2    │    │  P0: Phase 2    │
└────┬────────┘    └─────────┬────────┘    └────────┬────────┘
     │                         │                      │
┌────▼─────────────────────────▼──────────────────────▼────┐
│              Shared Services (shared across adapters)    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ CartManager  │ │ CheckoutFlow │ │  CaptchaSolver   │  │
│  │ (cart_ops)   │ │(shipping/pay│ │   (2Captcha)     │  │
│  └──────────────┘ └──────────────┘ └──────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ EvasionSvc  │ │ SessionSvc  │ │ NotificationSvc  │  │
│  │(UA/fingerprint│ │(prewarm)   │ │(Discord/Telegram)│  │
│  │  jitter)    │ │             │ │                  │  │
│  └──────────────┘ └──────────────┘ └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
Operator starts bot
        │
        ▼
Config.load() ──[validates schema]──► RetailerAdapter.init()
        │                                        │
        ▼                                        ▼
PreWarmingService.prewarm()              Browser pre-warmed
  - Loads page to cache cookies/tokens    - Auth cookies stored in SessionState
  - Validates session is alive            - Valid for 2 hours
        │
        ▼
StockMonitor.start()
  ┌──────────────────────────────────────────────┐
  │ LOOP (per item, per retailer):               │
  │   check_interval_ms ± jitter%                │
  │   Playwright.evaluate('stock status')        │
  │   OOS → IS transition?                       │
  └──────────────────────────────────────────────┘
        │
   [stock detected]
        │
        ▼
CartManager.add_item()
  - API or UI automation
  - Verify item in cart
  - Fire CART_ADDED webhook
        │
   [cart verified]
        │
        ▼
CheckoutFlow.run()
  ┌──────────────────────────────────────────────┐
  │  SHIPPING step: fill from config             │
  │  PAYMENT step: fill from config              │
  │  CAPTCHA? → CaptchaSolver.solve()            │
  │  QUEUE? → QueueHandler.wait()               │
  │  REVIEW → acknowledge terms                  │
  │  CONFIRM → capture order_id                 │
  └──────────────────────────────────────────────┘
        │
   [order confirmed]
        │
        ▼
WebhookService.send(CHECKOUT_SUCCESS, order_id)
        │
   [failure at any step]
        │
        ▼
WebhookService.send(CHECKOUT_FAILED, stage=step)
  - Retry up to N times
  - Or abort and alert
```

### Build-vs-Buy
| Component | Decision | Rationale |
|-----------|---------|-----------|
| Browser automation | Buy (Playwright) | Headless, anti-detect, cross-browser; no viable OSS替代 for this use case |
| CAPTCHA solving | Buy (2Captcha) | Solving reCAPTCHA/Turnstile programmatically is not viable; 2Captcha is the standard solution |
| HTTP client | Buy (httpx) | Battle-tested async HTTP/2; no reason to reinvent |
| Proxy rotation | Buy (residential proxy pool) | Datacenter IPs are blocked immediately by retailers; residential proxies are required for success |
| Notification webhooks | Build (aiohttp) | Simple POST to Discord/Telegram; no third-party SDK needed |

### Spike Required Before
- **Playwright stealth mode tuning** — verify that Target/Walmart/Best Buy don't detect headless Chromium on first page load
- **Target cart API** — confirm `POST /api/cart/items` works with auth cookies and doesn't require page navigation
- **Best Buy Turnstile** — confirm Playwright can inject Turnstile token programmatically after solve

---

## 4. Epic Map

| ID | Name | Mission | Depends On |
|----|------|---------|-----------|
| **E01** | Foundation & DevEx | Repo setup, tooling, CI pipeline, config scaffolding | None |
| **E02** | Core Domain Models | Dataclasses for all entities; shared types; no business logic yet | E01 |
| **E03** | Retailer Adapter: Target | Full Target.com stock monitoring + cart + checkout MVP | E02 |
| **E04** | Retailer Adapter: Walmart | Full Walmart.com implementation (login + checkout + bot mitigation) | E03 |
| **E05** | Retailer Adapter: Best Buy | Full BestBuy.com implementation (Turnstile + fastest checkout) | E04 |
| **E06** | Evasion & Anti-Detection | UA rotation, fingerprint randomization, proxy rotation | E03 (for testing) |
| **E07** | CAPTCHA Integration | 2Captcha SDK integration for reCAPTCHA/hCaptcha/Turnstile | E05 |
| **E08** | Session & Pre-Warming | SessionState management, cookie caching, scheduled pre-warm | E03 |
| **E09** | Checkout Pipeline | Shared checkout flow: shipping, payment, review, confirm; retry logic | E03 |
| **E10** | Notification Service | Discord + Telegram webhook sender with retry queue | E03 |
| **E11** | CLI & Operator Interface | All CLI commands; config validation; dry-run mode | E02 |
| **E12** | Observability & Operations | Structured logging, log rotation, health endpoint, metrics | E11 |
| **E13** | Testing — Phase 1 | Unit tests for core logic; integration test harness | E03, E11 |
| **E14** | Testing — Phase 2 | Full retailer test suites; E2E with Playwright | E05, E13 |
| **E15** | Production Hardening | Proxy rotation, multi-account, crash recovery, health checks | E06, E07, E08, E09, E10 |
| **E16** | Documentation | README, setup guide, runbook, ADRs | E15 |

**Phase Mapping:**
- **Phase 1 (v1.0 — Target MVP):** E01 → E02 → E03 → E09 (partial) → E10 (Discord) → E11 → E12 → E13
- **Phase 2 (v1.1–v1.2 — Walmart + BestBuy + Evasion):** E04 → E05 → E06 → E07 → E08 → E10 (Telegram) → E14
- **Phase 3 (v2.0 — Production Hardening):** E15 → E16

---

## 5. Task Backlog

---

### Epic E01: Foundation & DevEx

#### E01-T01: Initialize Python project structure
- **Description:** Create the full directory structure from PRD §7.1. Set up `pyproject.toml` with all dependencies pinned. Create `config.example.yaml` as the canonical template.
- **Files:**
  - `pyproject.toml`
  - `requirements.txt`
  - `config.example.yaml`
  - `src/` directory tree
  - `tests/` directory tree
- **Acceptance Criteria:**
  - `pip install -r requirements.txt` succeeds with zero errors
  - `python -c "import poke_drop_bot"` imports the package without error
  - `config.example.yaml` contains all keys from the PRD config schema but no real credentials
- **Technical Notes:** Use `pip-compile` (from `pip-tools`) to generate pinned `requirements.txt` from `pyproject.toml`. This ensures reproducible installs.
- **Dependencies:** None
- **Estimate:** S / **Priority:** P0 / **Labels:** `devex`, `infra`
- **Testing Requirements:** None (infra only)
- **Verification Command:** `pip install -e . && python -c "from src import config, logger; print('OK')"`

---

#### E01-T02: Configure pre-commit hooks
- **Description:** Set up pre-commit for format/lint/type-check on every commit. Include: `ruff` (format + lint), `mypy` (type-check), `pytest` (if tests exist), `detect-secrets` (prevent credential commits).
- **Files:** `.pre-commit-config.yaml`, `ruff.toml` (or `pyproject.toml` [tool.ruff] section)
- **Acceptance Criteria:**
  - Pre-commit runs on `git commit` and blocks commits that fail checks
  - `ruff format` formats all Python files
  - `ruff check --fix` autocorrects safe violations
  - `mypy src/` passes with no errors
  - `detect-secrets scan` catches any accidentally committed secrets
- **Technical Notes:** Use `ruff` over `black+flake8` — it covers both formatting and linting in one tool and is significantly faster.
- **Dependencies:** E01-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `devex`, `security`
- **Testing Requirements:** Verify that pre-commit hooks run successfully on existing files
- **Verification Command:** `pre-commit run --all-files && echo "PASSED"`

---

#### E01-T03: Set up CI pipeline
- **Description:** Configure GitHub Actions workflow for CI: lint → type-check → test → build. Trigger on push to `master` and all PRs.
- **Files:** `.github/workflows/ci.yml`
- **Acceptance Criteria:**
  - CI runs on every push and PR
  - Steps: `ruff check`, `mypy`, `pytest --tb=short`
  - Artifacts: test results uploaded on failure
  - Matrix strategy for Python 3.11, 3.12, 3.13
- **Technical Notes:** Cache `~/.cache/pip` and Playwright browser binaries to speed up CI runs.
- **Dependencies:** E01-T01, E01-T02
- **Estimate:** S / **Priority:** P0 / **Labels:** `devex`, `infra`
- **Testing Requirements:** CI must be self-testing (pass or fail based on actual lint/type/test results)
- **Verification Command:** Push a commit and verify all CI steps pass in the GitHub Actions UI

---

#### E01-T04: Create README.md
- **Description:** Write setup and usage README: installation steps, config instructions, CLI reference, how to run dry-run, how to interpret webhook events.
- **Files:** `README.md`
- **Acceptance Criteria:**
  - New operator can follow README to install, configure, and run dry-run in <15 minutes
  - All CLI commands documented with flags and examples
  - Webhook event table from PRD §8.2 included
  - Troubleshooting section covering common failures (session expired, CAPTCHA timeout, blocked by retailer)
- **Dependencies:** E01-T01, E11-T01 (CLI must be defined first)
- **Estimate:** S / **Priority:** P1 / **Labels:** `docs`
- **Testing Requirements:** None
- **Verification Command:** None (human-reviewed)

---

#### E01-T05: Set up structured logging
- **Description:** Configure `logger.py` with structured JSON output to stdout and plain text with timestamps to file. Log levels: DEBUG (form fields), INFO (lifecycle events), WARNING (retriable errors), ERROR (fatal). Log rotation: 10MB max, 5 backups.
- **Files:** `src/utils/logger.py`
- **Acceptance Criteria:**
  - Structured JSON to stdout when `LOG_FORMAT=json` env var set; otherwise human-readable
  - RotatingFileHandler: 10MB, 5 backups
  - Every log entry contains: `timestamp`, `level`, `event`, `item`, `retailer`, `message`
  - Sensitive fields (card_number, cvv) are NEVER logged at any level
  - `logger.debug("form_fields", extra={"shipping_name": "John D.", "card_last4": "1111"})` does NOT log full card number
- **Technical Notes:** Use `pythonjsonlogger` or a custom JSON formatter. Mask function in logging filter.
- **Dependencies:** E01-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `observability`
- **Testing Requirements:** Write test that captures log output and verifies no card numbers appear in logs
- **Verification Command:** `python -c "from src.utils.logger import get_logger; l = get_logger('test'); l.info('test', extra={'card_number': '4111111111111111'}); import sys; print('check logs above — card number should NOT appear')"`

---

### Epic E02: Core Domain Models

#### E02-T01: Define all dataclasses
- **Description:** Implement Python dataclasses for all entities defined in PRD §8.1: `MonitoredItem`, `RetailerAdapter`, `CheckoutConfig`, `ShippingInfo`, `PaymentInfo`, `WebhookEvent`, `SessionState`. Use `dataclasses.dataclass` with `frozen=True` where appropriate.
- **Files:** `src/models/__init__.py`, `src/models/monitored_item.py`, `src/models/checkout.py`, `src/models/session.py`, `src/models/webhook.py`
- **Acceptance Criteria:**
  - All fields present with correct types
  - `ShippingInfo.email` is optional (defaults to "")
  - `PaymentInfo.card_type` is optional (auto-detected)
  - `WebhookEvent` has all 12 event types as Literal string union
  - `SessionState` has `prewarmed_at: datetime | None = None`
- **Technical Notes:** Use `from __future__ import annotations` for forward references. Use `pydantic` instead if validation is needed at this layer (defer decision to E02-T02).
- **Dependencies:** E01-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Unit tests verifying all fields serialize/deserialize correctly
- **Verification Command:** `python -c "from src.models import MonitoredItem, WebhookEvent; print(WebhookEvent.__dataclass_fields__.keys())"`

---

#### E02-T02: Implement config loader with schema validation
- **Description:** Implement `src/config.py`: load YAML, validate against schema, support environment variable overrides for secrets. Raise `ConfigError` with a clear message on missing or invalid fields. Do NOT use silent defaults for required fields.
- **Files:** `src/config.py`, `src/exceptions.py`
- **Acceptance Criteria:**
  - Loads `config.yaml` from repo root; errors if file not found
  - All required fields enforced; no silent defaults
  - Env var overrides: `POKEDROP_2CAPTCHA_KEY`, `POKEDROP_DISCORD_URL`, `POKEDROP_TELEGRAM_BOT_TOKEN`, `POKEDROP_TELEGRAM_CHAT_ID`
  - `ConfigError` raised with field name and reason on validation failure
  - Validates `check_interval_ms` is between 100 and 5000
  - Validates `human_delay_ms` is between 0 and 5000
  - Validates `retry_max` is between 0 and 5
- **Technical Notes:** Consider using `pydantic` or `datamodel-code-generator` from a YAML schema instead of hand-rolling validation. Pydantic is well-supported in the Python ecosystem and provides type coercion + validation in one place.
- **Dependencies:** E01-T01, E02-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Test with valid config, invalid config (missing fields, wrong types, out-of-range values), and env var override. All should produce correct error messages.
- **Verification Command:** `python -c "from src.config import load_config; load_config()" # should raise ConfigError if config.yaml missing`

---

#### E02-T03: Define webhook event schemas
- **Description:** Define the payload schema for all 12 webhook event types (PRD §8.2). Implement a `WebhookPayload` factory that builds correctly-typed payloads per event.
- **Files:** `src/models/webhook.py`
- **Acceptance Criteria:**
  - `STOCK_DETECTED`: `{event, item, retailer, url, sku, timestamp}`
  - `CHECKOUT_FAILED`: `{event, item, retailer, error, attempt, stage, timestamp}`
  - `CHECKOUT_SUCCESS`: `{event, item, retailer, order_id, total, timestamp}`
  - All other events have correct field subsets
  - ISO-8601 UTC timestamps generated by a shared `utils.time_utils.utc_now()`
- **Dependencies:** E02-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Test payload generation for all 12 events; verify no extra fields; verify timestamps are ISO-8601
- **Verification Command:** `python -c "from src.models.webhook import WebhookPayload; p = WebhookPayload.stock_detected(item='test', retailer='target', url='...', sku='SKU-1'); print(p)"`

---

### Epic E03: Retailer Adapter — Target

#### E03-T01: Implement RetailerAdapter base class
- **Description:** Abstract base class in `src/monitor/retailers/base.py` defining the interface all retailer adapters must implement. Methods: `init_browser()`, `check_stock(item)`, `add_to_cart(item)`, `start_checkout()`, `submit_shipping()`, `submit_payment()`, `confirm_order()`, `handle_captcha()`, `handle_queue()`, `close()`.
- **Files:** `src/monitor/retailers/base.py`
- **Acceptance Criteria:**
  - ABC with `@abstractmethod` on all public methods
  - Shared `__init__(self, config: RetailerConfig, session: SessionState)`
  - `self.browser: playwright.Browser | None = None`
  - `self.page: playwright.Page | None = None`
  - Context manager protocol (`__enter__`, `__exit__`) for browser lifecycle
  - All adapters are instantiated from a factory: `RetailerAdapterFactory.create("target", config, session)`
- **Technical Notes:** The base class should NOT contain any retailer-specific logic — only shared utilities and the interface contract.
- **Dependencies:** E02-T01, E02-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Unit test: subclassing without implementing abstract methods raises `TypeError`
- **Verification Command:** `python -c "from src.monitor.retailers.base import RetailerAdapter; print('abstract base OK')"`

---

#### E03-T02: Implement TargetAdapter — browser setup and session pre-warm
- **Description:** Implement `TargetAdapter` in `src/monitor/retailers/target.py`. Initialize Playwright headless browser with anti-detect configuration. Pre-warm by visiting Target homepage, handling any auth prompts. Cache auth cookies and session tokens in `SessionState`.
- **Files:** `src/monitor/retailers/target.py`
- **Acceptance Criteria:**
  - Browser launched in headless mode with `--disable-blink-features=AutomationControlled`
  - Stealth mode: `navigator.webdriver` set to `undefined`, `navigator.plugins` populated
  - Target.com homepage loaded; cookies captured
  - `SessionState.cookies` persisted after pre-warm
  - Session validity check: GET account page, assert 200
  - Graceful error if login required but no credentials in config
- **Technical Notes:** Use `playwright.sync_api` for synchronous operations or `async_playwright` for async. Async preferred since other parts of the system are async. Target renders auth state client-side — may need to wait for specific DOM elements to confirm login.
- **Dependencies:** E02-T01, E02-T02, E03-T01, E08-T01 (pre-warming service)
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:target`
- **Testing Requirements:** Manual verification: pre-warm completes without error; session cookies are populated; dry-run checkout can proceed without re-authenticating
- **Verification Command:** `pokeDrop prewarm --retailer target` → should output "Session pre-warmed successfully"

---

#### E03-T03: Implement TargetAdapter — stock monitoring
- **Description:** Implement `check_stock()` on TargetAdapter. Use Playwright to navigate to product page and evaluate stock status. Detect OOS→IS transition. Support both SKU-based and keyword-based detection.
- **Files:** `src/monitor/retailers/target.py` (update)
- **Acceptance Criteria:**
  - Navigates to product page URL (constructed from SKU or item URL from config)
  - Evaluates stock status via `page.evaluate()` — exact XPath/text selectors documented in code
  - SKU-based: exact match on `data-sku` attribute or API response
  - Keyword-based: page text search for configured keywords
  - Returns `StockStatus.IN_STOCK`, `StockStatus.OUT_OF_STOCK`, or `StockStatus.UNKNOWN`
  - Logs all stock checks at DEBUG level (including current status)
  - Fires `STOCK_DETECTED` webhook only on OOS→IS transition, not on repeated IS polls
  - Check interval respects `config.check_interval_ms ± config.jitter_percent`
- **Technical Notes:** Target renders stock status client-side via JS. Known selector pattern: `document.querySelector('[data-test="orderPickupButton"] span')` or similar. Confirm actual selectors by inspecting Target product page. **Selector stability is the primary maintenance risk** — document exact selectors in code comments with XPath expressions and the date they were verified.
- **Dependencies:** E03-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:target`
- **Testing Requirements:** Write unit test with mocked Playwright page. Integration test (opt-in, tagged `integration`): verify stock status correctly detected on a live Target product page.
- **Verification Command:** `pytest tests/test_target_adapter.py::TestCheckStock -v`

---

#### E03-T04: Implement TargetAdapter — cart management
- **Description:** Implement `add_to_cart()` on TargetAdapter. Attempt direct cart API (`POST /api/cart/items`) first. Fall back to UI automation (click "Add to Cart" button). Verify item is in cart after addition.
- **Files:** `src/monitor/retailers/target.py` (update)
- **Acceptance Criteria:**
  - API approach: POST to `https://target.com/api/cart/items` with `{"items":[{"skuId": "...", "quantity": 1}]}` and auth cookies
  - UI approach: click "Add to Cart" button, wait for cart confirmation toast
  - Cart verification: navigate to cart page, assert item with correct SKU is present
  - Handles "Item no longer available" error: raise `CartError` with `CartErrorReason.ITEM_UNAVAILABLE`
  - Handles "Cart limit reached": raise `CartError` with `CartErrorReason.CART_LIMIT`
  - Handles quantity restrictions (max 1 per customer): log warning, continue
  - Fires `CART_ADDED` webhook on success
  - Prevents duplicate adds: if item already in cart, skip add and continue to checkout
- **Technical Notes:** Target's cart API may require `x-target-dataplatform` headers. Investigate via network inspection. Cart API response includes a `cartId` needed for checkout — store it in `SessionState.cart_token`.
- **Dependencies:** E03-T03
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:target`
- **Testing Requirements:** Unit test with mocked API response. Integration test (tagged `integration`): add item to cart on Target and verify cart contents.
- **Verification Command:** `pytest tests/test_target_adapter.py::TestCart -v`

---

#### E03-T05: Implement TargetAdapter — checkout flow
- **Description:** Implement `start_checkout()`, `submit_shipping()`, `submit_payment()`, and `confirm_order()` on TargetAdapter. Auto-fill shipping and payment forms from config. Handle order review step. Capture order confirmation number.
- **Files:** `src/monitor/retailers/target.py` (update)
- **Acceptance Criteria:**
  - `start_checkout()`: navigate from cart to checkout; handles any redirect to checkout initiation page
  - `submit_shipping()`: fill all `ShippingInfo` fields from config into Target's shipping form; submit; verify no validation errors
  - `submit_payment()`: fill all `PaymentInfo` fields into payment form; handle billing address same-as-shipping toggle
  - `confirm_order()`: acknowledge any terms/checkboxes; submit order; capture order ID from confirmation page
  - All steps respect `human_delay_ms ± 50ms` randomization
  - All form submissions wait for network idle (not just DOM ready)
  - Checkout step timeout: 30s per step, 60s total. On timeout: abort and fire `CHECKOUT_FAILED` with `stage=step_name`
  - Fires `CHECKOUT_STARTED` on checkout initiation, `CHECKOUT_SUCCESS` on confirmation, `CHECKOUT_FAILED` on any error
  - On payment decline: retry once after 2s delay; on second decline, abort
  - Logs all form field values at DEBUG level (with sensitive fields masked)
- **Technical Notes:** Target's checkout has ~5 steps. Document each step's URL pattern and form field names. Known fields: `addressLine1`, `city`, `state`, `zip`, `phone`. Payment fields: `cardNumber`, `expMonth`, `expYear`, `cvv`. Use `page.fill()` with exact field selectors. Avoid `page.type()` — it's slower and more detectable.
- **Dependencies:** E03-T04
- **Estimate:** L / **Priority:** P0 / **Labels:** `backend`, `retailer:target`
- **Testing Requirements:** `pokeDrop dry-run --item "Pikachu Vinyl Box" --retailer target` — must complete full checkout flow without placing order; all events fired in sequence; no order created
- **Verification Command:** `pokeDrop dry-run --item "test-item" --retailer target && echo "Dry-run completed"`

---

#### E03-T06: Implement TargetAdapter — queue/waiting room detection
- **Description:** Detect Target's virtual queue (redirects to `queue.target.com`). Implement `handle_queue()` that polls the queue page until released.
- **Files:** `src/monitor/retailers/target.py` (update)
- **Acceptance Criteria:**
  - Detect redirect to `queue.target.com` on any checkout navigation
  - Fire `QUEUE_DETECTED` webhook when entering queue
  - Poll queue status every 5s; log queue position if available
  - Fire `QUEUE_CLEARED` webhook when released
  - Timeout after 60s in queue: abort checkout, fire `CHECKOUT_FAILED` with `stage=queue`
  - If queue detected before cart add, wait in queue before adding to cart
- **Technical Notes:** Queue page URL pattern: `https://queue.target.com/...`. May set a cookie `queueposition`. Queue release may be indicated by a redirect back to the original retailer domain.
- **Dependencies:** E03-T05
- **Estimate:** M / **Priority:** P1 / **Labels:** `backend`, `retailer:target`
- **Testing Requirements:** Cannot test queue handling without a live high-traffic drop. Document manual test procedure. Unit test: mock a redirect response and verify `handle_queue()` is invoked.
- **Verification Command:** Manual — requires retailer queue condition

---

### Epic E04: Retailer Adapter — Walmart

#### E04-T01: Implement WalmartAdapter — browser setup, session, login flow
- **Description:** Implement `WalmartAdapter` in `src/monitor/retailers/walmart.py`. Walmart requires account login for checkout. Implement full login flow: navigate to sign-in, fill credentials, handle 2FA if enabled, verify login success.
- **Files:** `src/monitor/retailers/walmart.py`
- **Acceptance Criteria:**
  - Browser pre-warm includes sign-in if `walmart.email` and `walmart.password` in config
  - Login form: fill email/password, submit, wait for post-login redirect
  - 2FA detection: if 2FA challenge present, fire `CAPTCHA_REQUIRED` webhook (2FA is out-of-scope for solving — alert operator)
  - Session persisted to `SessionState` after login
  - Graceful error if login fails (wrong credentials, account locked)
- **Technical Notes:** Walmart login URL: `https://www.walmart.com/account/login`. May require `emaillogin` and `password` fields. Login state confirmed by visiting account page and asserting user name appears.
- **Dependencies:** E03-T01 (base class)
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:walmart`
- **Testing Requirements:** Integration test (tagged `integration`): log into Walmart account, verify session cookies are valid for at least 30 minutes
- **Verification Command:** `pokeDrop prewarm --retailer walmart` → should output "Session pre-warmed successfully" or appropriate error

---

#### E04-T02: Implement WalmartAdapter — stock monitoring
- **Description:** Implement `check_stock()` on WalmartAdapter. Walmart renders stock status client-side via JS. Use Playwright evaluation. Support SKU and keyword detection.
- **Files:** `src/monitor/retailers/walmart.py` (update)
- **Acceptance Criteria:** Same contract as E03-T03 but for Walmart. Stock status selectors documented in code comments with XPath and verification date.
- **Dependencies:** E04-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:walmart`
- **Testing Requirements:** Unit test with mocked Playwright. Integration test (opt-in).
- **Verification Command:** `pytest tests/test_walmart_adapter.py::TestCheckStock -v`

---

#### E04-T03: Implement WalmartAdapter — cart and checkout
- **Description:** Implement `add_to_cart()`, `start_checkout()`, `submit_shipping()`, `submit_payment()`, `confirm_order()` for Walmart. Handle Walmart's specific checkout flow, form field names, and API endpoints.
- **Files:** `src/monitor/retailers/walmart.py` (update)
- **Acceptance Criteria:**
  - Same checkout behavior contract as Target (E03-T05) adapted to Walmart's flow
  - Cart API: investigate `https://www.walmart.com/api/shopping/v3/rollers/items` or similar
  - Walmart checkout has account selection step (select saved address/payment)
  - Payment: support both saved payment and manual entry
  - Order confirmation: capture order number from confirmation page
  - All retry/defer/error handling per PRD §12
- **Technical Notes:** Walmart's bot mitigation is more aggressive than Target. Monitor for JS challenge pages (`/challenge/...` paths). May require `user.id` cookies to be present.
- **Dependencies:** E04-T02
- **Estimate:** L / **Priority:** P0 / **Labels:** `backend`, `retailer:walmart`
- **Testing Requirements:** `pokeDrop dry-run --retailer walmart`
- **Verification Command:** `pokeDrop dry-run --item "test-item" --retailer walmart && echo "Dry-run completed"`

---

#### E04-T04: Implement WalmartAdapter — queue and bot mitigation handling
- **Description:** Handle Walmart's queue/waiting room system and bot mitigation (JS challenges, IP rate limits).
- **Files:** `src/monitor/retailers/walmart.py` (update)
- **Acceptance Criteria:**
  - Detect queue pages (URL pattern: `https://www.walmart.com//ip/{item}/...` with queue parameter or waiting room redirect)
  - Detect JS challenge pages (`/challenge/` paths)
  - On JS challenge: log error, fire `CHECKOUT_FAILED`, alert operator
  - On IP rate limit (HTTP 429): apply exponential backoff, retry up to 3 times
  - All queue events fire correct webhooks
- **Dependencies:** E04-T03
- **Estimate:** M / **Priority:** P1 / **Labels:** `backend`, `retailer:walmart`
- **Testing Requirements:** Cannot simulate Walmart's challenges reliably. Document manual test procedure.
- **Verification Command:** Manual

---

### Epic E05: Retailer Adapter — Best Buy

#### E05-T01: Implement BestBuyAdapter — browser setup and Turnstile handling
- **Description:** Implement `BestBuyAdapter` in `src/monitor/retailers/bestbuy.py`. Best Buy uses Cloudflare Turnstile (not reCAPTCHA). Pre-warm session, detect Turnstile challenges, integrate with CaptchaSolver (E07) to solve via 2Captcha.
- **Files:** `src/monitor/retailers/bestbuy.py`
- **Acceptance Criteria:**
  - Browser pre-warm navigates to BestBuy homepage
  - Turnstile challenge detection: check for `cfcaptcha` iframes or `cloudflare` page elements
  - On Turnstile detected: call `CaptchaSolver.solve_turnstile(site_url, site_key)` before proceeding
  - Session persisted after challenge solved
  - Best Buy is fastest to sell out — checkout must complete in <5s after stock detection
- **Technical Notes:** Best Buy Turnstile site key may be embedded in the page as `data-sitekey`. Cloudflare Turnstile can be solved by 2Captcha using `method: 'turnstile'`. Token must be injected into a specific element or submitted with the next form action.
- **Dependencies:** E03-T01, E07-T01 (CaptchaSolver must exist)
- **Estimate:** L / **Priority:** P0 / **Labels:** `backend`, `retailer:bestbuy`
- **Testing Requirements:** `pokeDrop dry-run --retailer bestbuy`
- **Verification Command:** `pokeDrop dry-run --item "test-item" --retailer bestbuy && echo "Dry-run completed"`

---

#### E05-T02: Implement BestBuyAdapter — stock monitoring (500ms target)
- **Description:** Implement `check_stock()` on BestBuyAdapter. Best Buy is the fastest-selling retailer. Optimize for minimal latency: use direct API call where possible, Playwright fallback for JS rendering.
- **Files:** `src/monitor/retailers/bestbuy.py` (update)
- **Acceptance Criteria:**
  - Check interval default: 250ms (half of Target/Walmart) — configurable
  - Detect stock via Best Buy API (`https://www.bestbuy.com/api/cart/api/v2/add` responds differently for IS vs OOS items — investigate)
  - Fallback: Playwright evaluate on product page
  - OOS→IS transition must be detected within 500ms
  - Jitter: ±10% (tighter than Target's ±20% due to speed requirement)
- **Technical Notes:** Best Buy product pages: `https://www.bestbuy.com/site/{slug}/{sku}.p`. Stock status may be in `data-sku-id` attributes or a JSON blob in the page HTML. Investigate `https://www.bestbuy.com/api/tap/...` endpoints.
- **Dependencies:** E05-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `retailer:bestbuy`, `perf`
- **Testing Requirements:** Performance test: measure time from mock IS signal to STOCK_DETECTED event; must be <500ms
- **Verification Command:** `pytest tests/test_bestbuy_adapter.py::TestCheckStock -v --log-cli-level=INFO`

---

#### E05-T03: Implement BestBuyAdapter — cart and checkout
- **Description:** Implement `add_to_cart()`, `start_checkout()`, `submit_shipping()`, `submit_payment()`, `confirm_order()` for Best Buy. Optimize for <5s checkout end-to-end.
- **Files:** `src/monitor/retailers/bestbuy.py` (update)
- **Acceptance Criteria:**
  - Cart API: investigate `POST https://www.bestbuy.com/api/cart/add` with SKU payload
  - 1-Click checkout: if available (saved address/payment), skip cart page and go directly to express checkout
  - Standard checkout: adapt to Best Buy's specific form field names and step sequence
  - All steps: human_delay_ms reduced to 100ms for Best Buy (speed critical)
  - Checkout total timeout: 30s
  - Fires all correct webhook events
- **Dependencies:** E05-T02
- **Estimate:** L / **Priority:** P0 / **Labels:** `backend`, `retailer:bestbuy`, `perf`
- **Testing Requirements:** `pokeDrop dry-run --retailer bestbuy`
- **Verification Command:** `pokeDrop dry-run --item "test-item" --retailer bestbuy && echo "Dry-run completed"`

---

### Epic E06: Evasion & Anti-Detection

#### E06-T01: Implement UA rotation pool
- **Description:** Implement `src/evasion/user_agents.py`: maintain a pool of ≥50 real-world User-Agent strings. Rotate per-request or per-session. UA strings must be current (Chrome/Edge/Firefox from the last 12 months).
- **Files:** `src/evasion/user_agents.py`
- **Acceptance Criteria:**
  - Pool ≥ 50 UA strings
  - `get_random_ua()` returns a random UA from pool
  - `get_ua_for_retailer(retailer)` returns a retailer-specific UA hint (some retailers serve different content to Chrome vs Firefox)
  - UA strings are real and recent (verify against known browser version strings)
  - No duplicate consecutive UAs (track last returned)
  - All UAs tested to confirm they pass `navigator.userAgent` in headless Chrome
- **Technical Notes:** Source real UA strings from [useragentstring.com](https://www.useragentstring.com) or similar. Store as a static list in the module (not fetched at runtime — external calls are a fingerprinting vector).
- **Dependencies:** E01-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `anti-detection`
- **Testing Requirements:** Test that `get_random_ua()` returns valid UA format; test no immediate duplicates; test all UAs parse correctly with `user_agents` library
- **Verification Command:** `python -c "from src.evasion.user_agents import get_random_ua; ua = get_random_ua(); assert len(ua) > 20; assert 'Chrome' in ua or 'Firefox' in ua or 'Safari' in ua; print('UA OK:', ua[:50])"`

---

#### E06-T02: Implement browser fingerprint randomization
- **Description:** Implement `src/evasion/fingerprint.py`: randomize Playwright browser fingerprint per session. Covers: viewport size, timezone, locale, `navigator.hardwareConcurrency`, `navigator.deviceMemory`, WebGL vendor/renderer, screen resolution.
- **Files:** `src/evasion/fingerprint.py`
- **Acceptance Criteria:**
  - `randomize_fingerprint(context: BrowserContext)` applies fingerprint settings to a Playwright browser context
  - Viewport: random from set of 5 common resolutions (1920×1080, 1366×768, 1536×864, 1440×900, 1280×720)
  - Timezone: random from `["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]` — matches US retailer audience
  - Locale: `en-US` fixed (most US retailers expect this)
  - `navigator.hardwareConcurrency`: random from [2, 4, 8]
  - `navigator.deviceMemory`: random from [2, 4, 8]
  - WebGL vendor/renderer: random from realistic GPU strings (e.g., "Intel Iris OpenGL Engine", "NVIDIA GeForce GTX 1060")
  - All fingerprint settings applied before first navigation
- **Technical Notes:** Do NOT set `navigator.webdriver = false` manually — Playwright does this automatically in stealth mode. Verify with `page.evaluate('navigator.webdriver')` → should be falsy.
- **Dependencies:** E01-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `anti-detection`
- **Testing Requirements:** Verify fingerprint values are set correctly by evaluating `navigator.*` in the page context
- **Verification Command:** `python -c "from playwright.sync_api import sync_playwright; from src.evasion.fingerprint import randomize_fingerprint; p = sync_playwright().start(); ctx = p.chromium.launch(); page = ctx.new_page(); randomize_fingerprint(page); print('fingerprint OK')"`

---

#### E06-T03: Implement jitter/timing randomization
- **Description:** Implement `src/evasion/jitter.py`: add random variance to check intervals and step delays. Covers: check interval jitter, human-like delay between checkout steps, mouse movement simulation (optional, P2).
- **Files:** `src/evasion/jitter.py`
- **Acceptance Criteria:**
  - `add_jitter(base_ms: int, jitter_percent: float) -> int`: returns base_ms ± (base_ms * jitter_percent)
  - `human_delay(base_ms: int) -> int`: adds ±50ms to a human-like delay; minimum 0
  - Jitter applied consistently: interval check jitter = ±20% default, checkout step jitter = ±50ms default
  - Random seed NOT used (each call is independent; no reproducibility needed)
  - All jitter functions are pure (same input → different output on next call is OK)
- **Dependencies:** E01-T01
- **Estimate:** XS / **Priority:** P0 / **Labels:** `backend`, `anti-detection`
- **Testing Requirements:** Test jitter range: if base=1000 and jitter%=20%, result must be 800–1200. Test 100 samples for statistical distribution (should be roughly uniform within range).
- **Verification Command:** `python -c "from src.evasion.jitter import add_jitter; results = [add_jitter(1000, 0.2) for _ in range(100)]; assert all(800 <= r <= 1200 for r in results); print('Jitter OK: min', min(results), 'max', max(results))"`

---

#### E06-T04: Implement proxy rotation (v2.0)
- **Description:** Implement `src/evasion/proxy.py`: rotate residential proxy IPs per request or per session. Load proxy pool from config (`proxies:` YAML list). Support `http://user:pass@host:port` format.
- **Files:** `src/evasion/proxy.py`
- **Acceptance Criteria:**
  - Proxy pool loaded from config; minimum 1 proxy (single proxy is valid)
  - `get_next_proxy()` returns next proxy in round-robin; `get_random_proxy()` returns random
  - Proxy applied per Playwright browser context (each new context = new proxy)
  - On proxy connection failure: skip to next proxy, log error
  - On proxy auth failure: log error, skip to next proxy
  - Health check: verify proxy is working before using for critical operations (checkout)
- **Technical Notes:** Datacenter proxies will be blocked immediately by Target/Walmart/BestBuy. Only residential proxies are acceptable. Recommend Luminati/GeoSurf/BrightData residential pools for production. For testing, use free proxy lists (expect blocks).
- **Dependencies:** E02-T02 (config must support proxy list)
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `anti-detection`, `infra`
- **Testing Requirements:** Unit test with mocked proxy server. Integration test with a real proxy (if available).
- **Verification Command:** `python -c "from src.evasion.proxy import ProxyRotator; p = ProxyRotator(['http://user:pass@proxy.example:8080']); print('Proxy OK:', p.get_next_proxy())"`

---

#### E06-T05: Implement IP rate limit handling
- **Description:** Implement backoff and retry logic when retailer returns HTTP 429 (Too Many Requests) or 403 (Forbidden) indicating rate limiting.
- **Files:** `src/evasion/rate_limit.py` (new module)
- **Acceptance Criteria:**
  - On HTTP 429: apply exponential backoff starting at 2s, doubling on each retry, max 5 retries
  - On HTTP 403: treat as soft block; apply backoff; rotate proxy if available; retry up to 3 times
  - On HTTP 403 after retries: fire `SESSION_EXPIRED` webhook, alert operator
  - All backoff decisions logged at WARNING level
  - Rate limit detection: check response headers (`X-RateLimit-Remaining`, `Retry-After`)
- **Dependencies:** E03-T05 (checkout flow)
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `anti-detection`
- **Testing Requirements:** Unit test: mock HTTP 429 response, verify backoff is applied and retries occur
- **Verification Command:** `pytest tests/test_rate_limit.py -v`

---

### Epic E07: CAPTCHA Integration

#### E07-T01: Implement 2Captcha SDK integration
- **Description:** Implement `src/checkout/captcha.py`: integrate with 2Captcha API. Methods: `solve_recaptcha(site_url, site_key)`, `solve_hcaptcha(site_url, site_key)`, `solve_turnstile(site_url, site_key)`. All methods are async.
- **Files:** `src/checkout/captcha.py`
- **Acceptance Criteria:**
  - `solve_recaptcha(site_url, site_key)` → `str`: submits to 2Captcha, polls for solution, returns token
  - `solve_hcaptcha(site_url, site_key)` → `str`: same interface, different 2Captcha method
  - `solve_turnstile(site_url, site_key)` → `str`: uses 2Captcha `method: 'turnstile'`
  - Polling: every 5s, exponential backoff up to 120s total timeout
  - On timeout: raise `CaptchaTimeoutError`
  - On solve failure: raise `CaptchaSolveError`
  - All solve times logged as `captcha_solve_time_ms` metric
  - API key loaded from `POKEDROP_2CAPTCHA_KEY` environment variable (required)
  - Budget tracking: log cumulative daily solve count and estimated cost
- **Technical Notes:** 2Captcha API endpoint: `http://2captcha.com/res.php?key=YOUR_API_KEY&action=get&id=CAPTCHA_ID`. Use `aiohttp` for async HTTP calls to 2Captcha. Set `soft_id: 123456` to identify PokeDropBot in 2Captcha dashboard.
- **Dependencies:** E01-T01 (aiohttp)
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `captcha`
- **Testing Requirements:** Unit test with mocked 2Captcha responses (success, in-progress, timeout). Integration test (opt-in): solve a real reCAPTCHA on a test page.
- **Verification Command:** `python -c "import asyncio; from src.checkout.captcha import CaptchaSolver; async def t(): s = CaptchaSolver('TEST_KEY'); print('CaptchaSolver instantiated OK'); asyncio.run(t())"`

---

#### E07-T02: Implement CAPTCHA detection on retailer pages
- **Description:** In each RetailerAdapter, implement CAPTCHA challenge detection. Called automatically before and after cart/checkout operations. Covers: reCAPTCHA iframe detection, hCaptcha iframe detection, Cloudflare/Turnstile challenge page detection.
- **Files:** `src/monitor/retailers/target.py`, `src/monitor/retailers/walmart.py`, `src/monitor/retailers/bestbuy.py`
- **Acceptance Criteria:**
  - `detect_captcha(page: Page) -> CaptchaType | None`: returns enum (`RECAPTCHA`, `HCAPTCHA`, `TURNSTILE`, `CLOUDFLARE`, `UNKNOWN`)
  - Detection method: check page URL, page title, DOM for known CAPTCHA iframe selectors, page content for challenge text
  - Fire `CAPTCHA_REQUIRED` webhook when challenge detected
  - Auto-solve based on challenge type: call `CaptchaSolver` with appropriate method
  - Inject solved token into page and retry the intercepted form/button action
  - On CAPTCHA solve: fire `CAPTCHA_SOLVED` webhook with `solve_time_ms`
  - On CAPTCHA timeout: fire `CHECKOUT_FAILED` with `stage=captcha`, alert operator
- **Dependencies:** E07-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `captcha`
- **Testing Requirements:** Manual test: navigate to a retailer page that shows a CAPTCHA challenge (not always available); verify detection and solve flow
- **Verification Command:** `pytest tests/test_captcha.py::TestDetection -v`

---

### Epic E08: Session & Pre-Warming

#### E08-T01: Implement SessionState management
- **Description:** Implement `src/session/session_state.py`: manage `SessionState` dataclass. Methods: `save(path)`, `load(path)`, `is_expired()`, `invalidate()`. Persist session to disk as JSON between bot runs.
- **Files:** `src/session/session_state.py`
- **Acceptance Criteria:**
  - `SessionState` serialized to JSON (file: `~/.poke_drop_bot/sessions/{retailer}.json`)
  - Session expiry: if `prewarmed_at + session_ttl < now`, mark as expired
  - Default TTL: 2 hours for all retailers
  - `save()` called after every successful pre-warm and after any session state change
  - `load()` called on startup to resume any pre-warmed session
  - `is_expired()`: checks TTL; also does a live health check (GET account page) if TTL is near expiry
- **Dependencies:** E02-T01
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Test save/load roundtrip; test expiry detection; test that expired sessions are not used for checkout
- **Verification Command:** `python -c "from src.session.session_state import SessionState; import tempfile; import os; s = SessionState(retailer='target'); path = tempfile.mktemp(); s.save(path); loaded = SessionState.load(path); print('Session OK:', loaded.retailer)"`

---

#### E08-T02: Implement PreWarmingService
- **Description:** Implement `src/session/prewarmer.py`: `PreWarmingService` class. Given a `RetailerAdapter` and a target drop time, warm the session at `drop_time - prewarm_minutes`. Also support manual `pokeDrop prewarm` command.
- **Files:** `src/session/prewarmer.py`
- **Acceptance Criteria:**
  - `prewarm(adapter: RetailerAdapter, minutes_before: int = 10)`: warms session that many minutes before drop
  - Warm actions: load page, authenticate if needed, cache cookies/tokens, verify session alive
  - If drop time unknown: default to `config.prewarm_minutes` from config (default 10)
  - Scheduled pre-warm: run as background task; use `asyncio.sleep()` to wait until correct time
  - Manual pre-warm: `pokeDrop prewarm --retailer target` triggers immediately
  - After warm: update `SessionState.prewarmed_at` and persist
  - If warm fails: log error, fire `SESSION_EXPIRED`, alert operator
  - `PreWarmingScheduler`: accepts a list of drop time + item pairs; schedules all pre-warms
- **Technical Notes:** Use `asyncio.create_task()` for non-blocking scheduled pre-warms. The main monitoring loop should NOT block while waiting for pre-warm. If drop time is in the past, warm immediately.
- **Dependencies:** E03-T02 (Target pre-warm), E08-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `devex`
- **Testing Requirements:** Test pre-warm scheduling: set drop time 5 seconds in future, verify warm happens at correct time. Test that expired sessions trigger re-warm.
- **Verification Command:** `pokeDrop prewarm --retailer target && echo "Pre-warm OK"`

---

### Epic E09: Checkout Pipeline

#### E09-T01: Implement CartManager
- **Description:** Implement `src/checkout/cart_manager.py`: shared cart operations used by all retailer adapters. Methods: `add_item(adapter, item)`, `verify_cart(adapter, item)`, `clear_cart(adapter)`.
- **Files:** `src/checkout/cart_manager.py`
- **Acceptance Criteria:**
  - `add_item()`: delegates to retailer-specific adapter implementation
  - `verify_cart()`: navigate to cart page, assert item is present with correct SKU
  - `clear_cart()`: remove all items from cart (used between retry attempts)
  - Handles "item unavailable" error: raises `CartError.ITEM_UNAVAILABLE`
  - Handles duplicate add prevention: if item already verified in cart, skip add
  - All operations fire `CART_ADDED` webhook on success
  - All errors fire `CHECKOUT_FAILED` with `stage=cart`
- **Dependencies:** E03-T04, E04-T02, E05-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Unit test with mocked adapter. Integration test (tagged `integration`): add item to cart on live retailer, verify cart contents, clear cart.
- **Verification Command:** `pytest tests/test_cart_manager.py -v`

---

#### E09-T02: Implement CheckoutFlow orchestrator
- **Description:** Implement `src/checkout/checkout_flow.py`: the shared checkout orchestrator that coordinates all checkout steps. Manages retry logic, human delays, timeout enforcement, stage-level error reporting, and webhook firing.
- **Files:** `src/checkout/checkout_flow.py`
- **Acceptance Criteria:**
  - `run(adapter: RetailerAdapter, item: MonitoredItem) -> CheckoutResult`: main entry point
  - Executes: shipping → payment → (captcha if needed) → (queue if needed) → review → confirm
  - Retry: up to `config.checkout.retry_max` (default 2) on failure
  - Each step: enforce 30s timeout via `asyncio.wait_for()`
  - Overall checkout: enforce 60s timeout
  - Human delay injected between each step: `human_delay(config.human_delay_ms)`
  - `CheckoutResult`: `{success: bool, order_id: str | None, stage: str, error: str | None, attempts: int}`
  - On success: fire `CHECKOUT_SUCCESS` with `order_id` and `total`
  - On failure: fire `CHECKOUT_FAILED` with `stage`, `error`, `attempt`
  - On payment decline: wait 2s, retry once; second decline → abort
  - On CAPTCHA timeout: abort checkout
  - On unrecoverable error: do not retry; alert immediately
- **Dependencies:** E09-T01, E07-T02
- **Estimate:** L / **Priority:** P0 / **Labels:** `backend`
- **Testing Requirements:** Unit test: mock all adapter methods; verify retry logic, timeout enforcement, stage reporting. Integration: `pokeDrop dry-run` (full flow, no order placed).
- **Verification Command:** `pokeDrop dry-run --retailer target`

---

### Epic E10: Notification Service

#### E10-T01: Implement Discord webhook adapter
- **Description:** Implement `src/notifications/discord.py`: send formatted Discord embeds for all webhook event types. Rich embed with: color (green=success, red=failure, yellow=warning), title (event type), fields (item, retailer, order_id, error), timestamp.
- **Files:** `src/notifications/discord.py`
- **Acceptance Criteria:**
  - `send(event: WebhookEvent)`: builds embed, POSTs to `config.notifications.discord.webhook_url`
  - Embed color: `0x00FF00` (success), `0xFF0000` (failure), `0xFFAA00` (warning/info)
  - Embed fields: always includes `Item`, `Retailer`, `Timestamp`; conditionally includes `Order ID`, `Error`, `Stage`
  - `aiohttp` used for async POST; 5s timeout
  - On send failure: retry up to 3 times with exponential backoff (1s, 2s, 4s)
  - On all retries exhausted: log error, do not raise exception (non-blocking)
  - Rate limit handling (HTTP 429): backoff and retry
  - Validates webhook URL is HTTPS before sending
- **Dependencies:** E02-T03 (WebhookEvent schemas)
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `notifications`
- **Testing Requirements:** Unit test with mocked `aiohttp` responses. Integration test (opt-in): send a test event to a real Discord webhook.
- **Verification Command:** `python -c "from src.notifications.discord import DiscordNotifier; n = DiscordNotifier('https://discord.com/api/webhooks/test'); print('Discord OK')"`

---

#### E10-T02: Implement Telegram webhook adapter
- **Description:** Implement `src/notifications/telegram.py`: send formatted messages via Telegram Bot API. Uses `sendMessage` endpoint with HTML formatting.
- **Files:** `src/notifications/telegram.py`
- **Acceptance Criteria:**
  - `send(event: WebhookEvent)`: builds HTML message, POSTs to `https://api.telegram.org/bot{bot_token}/sendMessage`
  - Message format: `<b>{EVENT_TYPE}</b>\nItem: {item}\nRetailer: {retailer}\nTimestamp: {timestamp}\n[Additional fields]`
  - `chat_id` from config
  - Retry logic: 3 retries with exponential backoff
  - Rate limit handling: backoff and retry
  - Invalid token: log error clearly, do not raise exception
- **Dependencies:** E02-T03
- **Estimate:** S / **Priority:** P1 / **Labels:** `backend`, `notifications`
- **Testing Requirements:** Unit test with mocked Telegram API responses
- **Verification Command:** `python -c "from src.notifications.telegram import TelegramNotifier; n = TelegramNotifier('test_token', '123456'); print('Telegram OK')"`

---

#### E10-T03: Implement NotificationService with retry queue
- **Description:** Implement `src/notifications/webhook.py`: unified `NotificationService` that fans out to all configured channels (Discord, Telegram). Implement an in-memory retry queue for failed deliveries.
- **Files:** `src/notifications/webhook.py`
- **Acceptance Criteria:**
  - `NotificationService`: holds list of configured channels; calls all `channel.send(event)` concurrently
  - Retry queue: failed events stored in queue; retried on next `send()` call or every 30s
  - Queue max size: 100 events; oldest dropped if exceeded (logged)
  - Channel health tracking: if a channel fails 5 consecutive times, mark as degraded and log warning
  - `send_test_event()`: fires a `TEST_EVENT` with all channels to verify connectivity
  - `close()`: flushes queue on shutdown
- **Dependencies:** E10-T01, E10-T02
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `notifications`
- **Testing Requirements:** Test fan-out: mock one channel failing, verify others still succeed. Test retry queue: disable channel, queue events, re-enable, verify events are delivered.
- **Verification Command:** `pytest tests/test_notifications.py -v`

---

### Epic E11: CLI & Operator Interface

#### E11-T01: Implement CLI with all commands
- **Description:** Implement `src/main.py` with full CLI using `argparse`. Commands: `start`, `stop`, `status`, `test-config`, `dry-run`, `prewarm`.
- **Files:** `src/main.py`
- **Acceptance Criteria:**
  - `pokeDrop start [--item <name>] [--retailer <name>]`: starts monitoring loop; blocks until interrupted
  - `pokeDrop stop`: gracefully stops monitoring; closes browser sessions; persists state; exits 0
  - `pokeDrop status`: prints current state: active items, retailer sessions (pre-warmed/expired), uptime
  - `pokeDrop test-config`: validates config; prints "Config valid" or specific field errors; exits 0 or 1
  - `pokeDrop dry-run [--item <name>] [--retailer <name>]`: runs full checkout flow without placing order; exits 0 on success, 1 on failure
  - `pokeDrop prewarm [--retailer <name>]`: triggers immediate session pre-warm for specified retailer or all configured retailers
  - All commands: `--help` shows usage; invalid args show error
  - All errors: non-zero exit code + error message to stderr
- **Technical Notes:** Use `argparse` subparsers for command structure. Global `--config` flag to override config file path. Use `signal.signal(signal.SIGINT, handler)` for graceful stop on Ctrl+C.
- **Dependencies:** E02-T02, E03-T05, E08-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `devex`
- **Testing Requirements:** CLI integration test: invoke each command via `subprocess.run(['python', '-m', 'src.main', '<command>', ...])` and verify exit code and output
- **Verification Command:** `python -m src.main --help && python -m src.main test-config`

---

### Epic E12: Observability & Operations

#### E12-T01: Implement health check endpoint
- **Description:** Implement `src/observability/health.py`: HTTP server exposing `GET /health`. Returns JSON `{status: "ok" | "degraded" | "error", active_items: int, active_retailers: list[str], uptime_seconds: float, session_health: dict}`.
- **Files:** `src/observability/health.py`, `src/observability/__init__.py`
- **Acceptance Criteria:**
  - Health server starts on configurable port (default: `8080`) when monitoring is active
  - `GET /health` returns 200 when healthy; 503 when degraded (e.g., all sessions expired)
  - Does NOT expose sensitive data (no credentials, no order details)
  - Bind to `127.0.0.1` only (not publicly accessible)
  - Integration: when monitoring starts, health server starts; when monitoring stops, health server stops
- **Technical Notes:** Use Python's built-in `http.server` or `aiohttp` for the health endpoint. No need for a full web framework.
- **Dependencies:** E11-T01 (monitoring must be running)
- **Estimate:** S / **Priority:** P0 / **Labels:** `backend`, `ops`
- **Testing Requirements:** Test health endpoint returns correct JSON; test 503 when sessions are expired
- **Verification Command:** `curl http://127.0.0.1:8080/health`

---

#### E12-T02: Implement Prometheus-compatible metrics endpoint
- **Description:** Implement `src/observability/metrics.py`: `/metrics` endpoint exposing Prometheus-formatted counters/gauges for: `pokedrop_checkouts_attempted_total`, `pokedrop_checkouts_succeeded_total`, `pokedrop_checkouts_failed_total{stage}`, `pokedrop_captcha_solve_time_ms`, `pokedrop_stock_detected_total{retailer}`.
- **Files:** `src/observability/metrics.py`
- **Acceptance Criteria:**
  - Prometheus text format
  - All metrics updated in real-time as events fire
  - No sensitive data exposed
  - Endpoint: `GET /metrics`
- **Dependencies:** E09-T02
- **Estimate:** S / **Priority:** P2 / **Labels:** `backend`, `ops`
- **Testing Requirements:** Test metric values are updated after simulated events
- **Verification Command:** `curl http://127.0.0.1:8080/metrics | grep pokedrop`

---

### Epic E13: Testing — Phase 1 (Target MVP)

#### E13-T01: Write unit tests for config validation
- **Description:** Comprehensive unit tests for `src/config.py` covering: valid config loads, all invalid scenarios (missing required fields, wrong types, out-of-range values), env var overrides, error message specificity.
- **Files:** `tests/test_config.py`
- **Acceptance Criteria:** Every validation rule from E02-T02 has at least one test case. All tests pass. Zero tolerance for config validation bypass.
- **Dependencies:** E02-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `testing`, `backend`
- **Testing Requirements:** pytest with `pytest.mark.parametrize` for validation edge cases
- **Verification Command:** `pytest tests/test_config.py -v --tb=short`

---

#### E13-T02: Write unit tests for jitter and UA rotation
- **Description:** Unit tests for `src/evasion/jitter.py` and `src/evasion/user_agents.py`.
- **Files:** `tests/test_evasion.py`
- **Acceptance Criteria:**
  - Jitter: statistical range tests (100 samples, all within range)
  - Jitter: no negative results
  - UA: all strings are valid UA format
  - UA: no immediate duplicates
  - UA: pool size ≥ 50
- **Dependencies:** E06-T01, E06-T03
- **Estimate:** S / **Priority:** P0 / **Labels:** `testing`, `backend`
- **Verification Command:** `pytest tests/test_evasion.py -v`

---

#### E13-T03: Write unit tests for webhook payload generation
- **Description:** Unit tests for all 12 `WebhookPayload` factory methods.
- **Files:** `tests/test_webhook.py`
- **Acceptance Criteria:** Each event type generates correctly-shaped payload. Timestamps are ISO-8601. No extra fields. No missing required fields.
- **Dependencies:** E02-T03
- **Estimate:** S / **Priority:** P0 / **Labels:** `testing`, `backend`
- **Verification Command:** `pytest tests/test_webhook.py -v`

---

#### E13-T04: Write integration tests for Target dry-run
- **Description:** End-to-end dry-run test for Target: start pre-warm, add item to cart, complete checkout, verify no order placed. Use real Target.com in a controlled environment (tagged `integration`).
- **Files:** `tests/integration/test_target_checkout.py`
- **Acceptance Criteria:**
  - Test requires `--run-integration` flag: `pytest --run-integration`
  - All 12 webhook events fire in correct sequence
  - No real order placed (dry-run mode)
  - Checkout completes in <10s
  - Captures and logs any CAPTCHA challenges encountered
- **Dependencies:** E03-T05, E10-T03
- **Estimate:** L / **Priority:** P0 / **Labels:** `testing`, `integration`, `retailer:target`
- **Testing Requirements:** Only runs when explicitly enabled; uses real retailer pages
- **Verification Command:** `pytest --run-integration tests/integration/test_target_checkout.py -v`

---

### Epic E14: Testing — Phase 2 (All Retailers + E2E)

#### E14-T01: Write retailer adapter unit tests (Walmart, Best Buy)
- **Description:** Unit tests for WalmartAdapter and BestBuyAdapter with mocked Playwright and HTTP responses. Cover stock detection, cart add, checkout flow, CAPTCHA detection, queue detection.
- **Files:** `tests/test_walmart_adapter.py`, `tests/test_bestbuy_adapter.py`
- **Acceptance Criteria:** Each method has ≥1 unit test with mocked dependencies. Tests are deterministic and fast (<1s each).
- **Dependencies:** E04-T01–E05-T03
- **Estimate:** M / **Priority:** P0 / **Labels:** `testing`, `backend`
- **Verification Command:** `pytest tests/test_walmart_adapter.py tests/test_bestbuy_adapter.py -v`

---

#### E14-T02: Write E2E Playwright tests for critical flows
- **Description:** Playwright E2E tests covering: full monitoring → cart → checkout flow (dry-run) on all three retailers. Uses `playwright.test` with page objects.
- **Files:** `tests/e2e/`
- **Acceptance Criteria:**
  - One test per retailer: "monitor item → stock detected → cart → checkout"
  - All use dry-run mode (no real orders)
  - All tagged `@pytest.mark.e2e`
  - Run with: `pytest --run-e2e`
  - Assertions: correct webhook event sequence, correct final state
- **Dependencies:** E13-T04 (test infrastructure), E05-T03
- **Estimate:** L / **Priority:** P1 / **Labels:** `testing`, `e2e`
- **Testing Requirements:** E2E tests are the most important validation. Must pass on all three retailers before v2.0 release.
- **Verification Command:** `pytest --run-e2e tests/e2e/ -v`

---

#### E14-T03: Write CAPTCHA integration tests
- **Description:** Test 2Captcha integration: mock 2Captcha API for success, in-progress, timeout, and error scenarios. Verify token injection works correctly.
- **Files:** `tests/test_captcha.py`
- **Acceptance Criteria:**
  - Mock 2Captcha `/res.php` endpoint
  - Test solve success: returns token within timeout
  - Test solve polling: handles "not ready" responses correctly
  - Test timeout: raises `CaptchaTimeoutError` after 120s
  - Test error: raises `CaptchaSolveError` on API error
  - Test token injection: verified token appears in page
- **Dependencies:** E07-T01, E07-T02
- **Estimate:** M / **Priority:** P0 / **Labels:** `testing`, `captcha`
- **Verification Command:** `pytest tests/test_captcha.py -v`

---

#### E14-T04: Accessibility testing pass
- **Description:** Automated accessibility tests: use `axe-core` via `playwright` to audit retailer checkout pages. Run per retailer adapter.
- **Files:** `tests/a11y/`
- **Acceptance Criteria:** Accessibility audit runs on checkout form pages. Critical and serious violations (WCAG 2.1 AA) are documented. Note: retailer pages are third-party; violations should be documented and reported to retailer if actionable.
- **Dependencies:** E14-T02
- **Estimate:** S / **Priority:** P2 / **Labels:** `testing`, `a11y`
- **Testing Requirements:** Manual note: retailer page accessibility cannot be fixed by the bot team. This task is for documentation only.
- **Verification Command:** `pytest tests/a11y/ -v` (manual review of results)

---

### Epic E15: Production Hardening

#### E15-T01: Implement crash recovery and state persistence
- **Description:** Persist full bot state (active items, session health, retry counters) to disk. On restart, load state and resume without re-purchasing already-ordered items. Implement deduplication: if an order was placed in a previous run, do not re-order.
- **Files:** `src/state/recovery.py`
- **Acceptance Criteria:**
  - State persisted to `~/.poke_drop_bot/state.json` on every significant transition
  - On startup: load state; check for any incomplete checkout attempts from previous run
  - Deduplication: if item was successfully ordered in last 24 hours, skip that item (configurable `dedup_window_hours`)
  - On crash mid-checkout: do not retry automatically on restart; require manual confirmation or `--force`
  - Crash recovery tested by killing process mid-checkout, restarting, and verifying no duplicate order
- **Dependencies:** E09-T02, E11-T01
- **Estimate:** M / **Priority:** P0 / **Labels:** `backend`, `ops`
- **Testing Requirements:** Kill process mid-checkout; restart; verify no duplicate. Kill process mid-monitoring; restart; verify monitoring resumes correctly.
- **Verification Command:** `python -c "import os, signal; from src.main import main; # send SIGKILL to main process, restart, verify state"` (manual test procedure documented in runbook)

---

#### E15-T02: Implement multi-account coordination
- **Description:** Support running multiple bot instances with shared checkout queue. Ensure only one instance can attempt to purchase a given item at a given time (distributed lock).
- **Files:** `src/multiaccount/coordinator.py`
- **Acceptance Criteria:**
  - Shared lock via file lock: `~/.poke_drop_bot/locks/{item_id}.lock`
  - On lock acquisition failure: item is being handled by another instance; skip and log
  - Lock TTL: 60s; if instance dies, lock expires and another instance can pick up
  - One-purchase-per-account: if account has purchased item in `purchase_cooldown_hours`, skip
  - Dashboard: `pokeDrop status` shows which instance owns which item lock
- **Dependencies:** E15-T01
- **Estimate:** M / **Priority:** P2 / **Labels:** `backend`, `ops`
- **Testing Requirements:** Run two bot instances simultaneously; verify only one can checkout the same item
- **Verification Command:** `pytest tests/test_multiaccount.py -v`

---

#### E15-T03: Set up monitoring dashboards and alerting
- **Description:** Set up basic Prometheus scraping for the metrics endpoint. Create Grafana dashboard JSON for: checkout success rate, CAPTCHA solve times, stock detection latency, active sessions.
- **Files:** `infra/dashboards/pokedrop-dashboard.json`, `infra/grafana-datasource.yaml`
- **Acceptance Criteria:**
  - Grafana dashboard JSON importable
  - Panels: success rate gauge, CAPTCHA cost/day, checkout latency histogram, active items count
  - Alert rules: success rate <50%, CAPTCHA solve time >60s, session health degraded
  - Alert routing: Slack or PagerDuty webhook (configurable)
- **Dependencies:** E12-T01, E12-T02
- **Estimate:** M / **Priority:** P2 / **Labels:** `ops`, `observability`
- **Testing Requirements:** Dashboard renders correctly in Grafana; alerts fire when thresholds breached
- **Verification Command:** Import JSON into Grafana; verify all panels render data

---

### Epic E16: Documentation

#### E16-T01: Write runbook for top 5 failure scenarios
- **Description:** Write `docs/runbook.md` covering the 5 most likely operational failures and how to handle them.
- **Files:** `docs/runbook.md`
- **Acceptance Criteria:** Runbook covers:
  1. Bot detects stock but checkout fails with "session expired" → re-prewarm and retry
  2. Bot blocked by retailer (HTTP 403) → rotate IP via proxy, reduce check frequency
  3. CAPTCHA not solving within 120s → operator intervention required, increase budget or disable CAPTCHA-required retailers
  4. Payment declined twice → check card balance, verify billing address, retry manually
  5. Process crashed mid-checkout → verify no duplicate order via retailer account page, clear locks, restart
- **Dependencies:** E15-T01
- **Estimate:** S / **Priority:** P1 / **Labels:** `docs`, `ops`
- **Testing Requirements:** None (documentation)
- **Verification Command:** None (human-reviewed)

---

#### E16-T02: Write ADRs for key architectural decisions
- **Description:** Write Architecture Decision Records for non-obvious choices. Files in `docs/adr/`.
- **Files:** `docs/adr/ADR-001-use-playwright-for-browser-automation.md`, `docs/adr/ADR-002-use-2captcha-for-captcha-solving.md`, `docs/adr/ADR-003-session-pre-warming-strategy.md`, `docs/adr/ADR-004-async-vs-sync-architecture.md`
- **Acceptance Criteria:**
  - Each ADR: Context, Decision, Consequences, Alternatives Considered
  - Decisions: Playwright (vs Selenium/Puppeteer), 2Captcha (vs anti-captcha), pre-warm TTL=2h, async throughout
  - Stored in `docs/adr/` with numbered prefixes
- **Dependencies:** None
- **Estimate:** S / **Priority:** P2 / **Labels:** `docs`
- **Testing Requirements:** None
- **Verification Command:** None

---

## 6. Suggested Execution Order

### Milestone M1 — Working Target Bot (End of Phase 1)
**Goal:** Dry-run checkout on Target works end-to-end.

```
E01-T01 → E01-T02 → E01-T03 → E01-T05
  → E02-T01 → E02-T02 → E02-T03
  → E03-T01 → E03-T02 → E03-T03 → E03-T04 → E03-T05 → E03-T06
  → E09-T01 → E09-T02
  → E10-T01 → E10-T03
  → E11-T01
  → E12-T01
  → E13-T01 → E13-T02 → E13-T03 → E13-T04
```

**Definition of M1 Done:**
```bash
pokeDrop test-config  # passes
pokeDrop prewarm --retailer target  # succeeds
pokeDrop dry-run --item "test-item" --retailer target  # completes, all events fire
pytest tests/test_config.py tests/test_evasion.py tests/test_webhook.py -v  # all pass
```

---

### Milestone M2 — Multi-Retailer Support (End of Phase 2)
**Goal:** Bot works on all three retailers with evasion and CAPTCHA.

```
E04-T01 → E04-T02 → E04-T03 → E04-T04
  → E05-T01 → E05-T02 → E05-T03
  → E06-T01 → E06-T02 → E06-T03 → E06-T04 → E06-T05
  → E07-T01 → E07-T02
  → E08-T01 → E08-T02
  → E10-T02
  → E14-T01 → E14-T03
```

**Definition of M2 Done:**
```bash
pokeDrop dry-run --retailer target  # succeeds
pokeDrop dry-run --retailer walmart # succeeds
pokeDrop dry-run --retailer bestbuy # succeeds
pytest tests/test_walmart_adapter.py tests/test_bestbuy_adapter.py tests/test_captcha.py -v  # all pass
```

---

### Milestone M3 — Production Ready (End of Phase 3)
**Goal:** Bot is production-hardened with observability, recovery, and docs.

```
E12-T02 → E15-T01 → E15-T02 → E15-T03
  → E14-T02 → E14-T04
  → E16-T01 → E16-T02
  → E01-T04
```

**Definition of M3 Done:**
```bash
pytest --run-e2e tests/e2e/ -v  # all pass
pokeDrop start  # runs for 1 hour without crash
# crash mid-checkout → restart → no duplicate order
curl http://127.0.0.1:8080/health  # returns 200
curl http://127.0.0.1:8080/metrics  # returns Prometheus metrics
```

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation | Tasks |
|------|------------|--------|-----------|-------|
| Target/Walmart/Best Buy block headless browser | **HIGH** | **HIGH** | Stealth mode + fingerprint randomization + proxy rotation; stealth mode tuning spike (pre-E03) | E06-T01–E06-T05 |
| CAPTCHA always appears on checkout | **HIGH** | **MEDIUM** | 2Captcha integration; budget for solves; fallback to manual if solve fails | E07-T01, E07-T02 |
| Retailer page structure changes (XPath selectors break) | **HIGH** | **HIGH** | Modular adapter isolates changes to one file; regression tests catch failures | E03-T03, E04-T02, E05-T02, E14-T02 |
| Best Buy Turnstile blocks all automation | **HIGH** | **HIGH** | Spike before E05; if unsolvable, Best Buy drops to P2 | E05-T01 (spike) |
| Payment processor flags orders as fraud | **MEDIUM** | **HIGH** | Use saved payment method; randomized delays; dedicated low-limit card | E09-T02 |
| Proxy pool quality insufficient | **HIGH** | **MEDIUM** | Vet proxy providers; test with real retailer before drop window | E06-T04 |
| Crash mid-checkout causes duplicate order | **MEDIUM** | **HIGH** | Dedup tracking; crash recovery with state persistence | E15-T01 |
| 2Captcha solve times exceed budget | **MEDIUM** | **MEDIUM** | Budget tracking; alert if daily solve cost exceeds threshold | E07-T01 |
| Config not validated on startup → silent failure | **LOW** | **HIGH** | Strict schema validation; startup fails on missing required fields | E02-T02 |
| Bot violates retailer ToS and account gets banned | **MEDIUM** | **HIGH** | Use separate account for bot; clear ToS compliance disclaimer; operator bears risk | PRD §22 |

---

## 8. Definition of Done (Project-Wide)

### Code Quality
- [ ] All tests pass (`pytest --tb=short`)
- [ ] `ruff check --fix` produces no changes
- [ ] `mypy src/` produces no errors
- [ ] No hardcoded values — everything in `config.yaml`
- [ ] No secrets in logs, code, or git history
- [ ] Sensitive fields (`card_number`, `cvv`, `api_key`) never logged

### Functional
- [ ] `pokeDrop dry-run` completes successfully on Target, Walmart, and Best Buy
- [ ] All 12 webhook events fire in correct sequence on successful checkout
- [ ] All 12 webhook events fire in correct sequence on failed checkout (with correct error)
- [ ] CAPTCHA challenges are detected and solved via 2Captcha
- [ ] Session pre-warming works and session cookies are reused
- [ ] Config validation rejects missing/invalid fields with clear error messages
- [ ] Crash during checkout does not result in duplicate order on restart
- [ ] Graceful shutdown via `pokeDrop stop` closes all resources cleanly

### Observability
- [ ] Structured logs output to stdout (JSON format in production)
- [ ] `GET /health` returns correct status
- [ ] `GET /metrics` exposes Prometheus metrics
- [ ] All webhook delivery failures are retried up to 3 times

### Security
- [ ] `config.yaml` has `chmod 600` enforced in README
- [ ] `POKEDROP_2CAPTCHA_KEY` loaded from environment variable in production
- [ ] Browser sandboxed; no local filesystem access from browser context
- [ ] No credential committed to git history (verified by `detect-secrets` pre-commit hook)

### Performance
- [ ] Stock detection latency: <1s Target/Walmart, <500ms Best Buy (verified by integration test)
- [ ] Checkout completion: <10s Target, <15s Walmart, <5s Best Buy (verified by dry-run)
- [ ] Memory footprint <512MB with 1 browser instance per retailer

### Documentation
- [ ] README.md: new operator can set up and run dry-run in <15 minutes
- [ ] Runbook: top 5 failure scenarios documented
- [ ] ADRs: 4 key architectural decisions documented
- [ ] All CLI commands documented with `--help` and examples

---

*End of TASKS.md*
