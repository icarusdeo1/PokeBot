# PRD-to-Task Decomposition Prompt

> **How to use:** Drop this file into any project repo. Point your AI coding agent at it and say something like *"Follow the instructions in `prd-to-tasks.md`."* The agent will locate the PRD, infer the stack, and produce a full backlog.

---

# AGENT INSTRUCTIONS — READ FIRST

Before generating anything, perform these setup steps **in order**. Do not skip. Do not ask the user for information you can discover yourself.

## Step 1 — Locate the PRD

Search the current working directory and its subdirectories for a PRD file. Look for these filenames, in priority order:

1. `PRD.md` (case-insensitive) at the repo root
2. `PRD.md` in `/docs`, `/documentation`, `/product`, `/specs`, or `/planning`
3. Any file matching `*prd*.md`, `*PRD*.md`, or `product-requirements*.md`
4. Any `.md` file whose H1 or first 20 lines contain "Product Requirements Document", "PRD", or "Product Spec"

Use whatever file-reading tools are available (e.g., shell `find`/`grep`, glob, read_file). If multiple candidates exist, read the first few lines of each and pick the one that most clearly looks like a product spec. State which file you selected and why.

If no PRD is found, stop and tell the user: *"No PRD found. Please add a `PRD.md` file to the repo or tell me where the PRD lives."*

## Step 2 — Infer the Tech Stack

Do **not** ask the user about the stack. Detect it by scanning the repo. Check in this order and build a stack profile from what you find:

**Language & runtime signals**
- `package.json` → Node.js / TypeScript / JavaScript. Read `dependencies` and `devDependencies`.
- `tsconfig.json` → TypeScript confirmed
- `pyproject.toml`, `requirements.txt`, `Pipfile`, `poetry.lock` → Python
- `Cargo.toml` → Rust
- `go.mod` → Go
- `Gemfile` → Ruby
- `pom.xml`, `build.gradle`, `build.gradle.kts` → JVM (Java/Kotlin)
- `*.csproj`, `*.sln` → .NET
- `Package.swift`, `*.xcodeproj`, `Podfile` → Swift / iOS
- `pubspec.yaml` → Flutter / Dart

**Framework signals (from package.json dependencies and file structure)**
- `next` → Next.js
- `react-native`, `expo` → React Native (+ Expo)
- `react` without RN/Next → React SPA (Vite/CRA — check scripts)
- `vue`, `nuxt` → Vue / Nuxt
- `svelte`, `@sveltejs/kit` → Svelte / SvelteKit
- `@angular/core` → Angular
- `express`, `fastify`, `koa`, `hono`, `@nestjs/core` → Node backend framework
- `grammy`, `telegraf` → Telegram bot
- `django`, `fastapi`, `flask` → Python backend
- `rails` gem → Rails

**Data layer signals**
- `prisma/schema.prisma` → Prisma (read it for DB type)
- `drizzle.config.*` → Drizzle
- `supabase/` directory or `@supabase/supabase-js` → Supabase
- `@react-native-async-storage/async-storage`, `watermelondb`, `expo-sqlite`, `react-native-mmkv` → mobile local storage
- `better-sqlite3`, `sqlite3` → SQLite
- `pg`, `mysql2`, `mongodb`, `mongoose`, `redis`, `ioredis` → respective databases

**Infra / deploy signals**
- `vercel.json` → Vercel
- `netlify.toml` → Netlify
- `railway.json`, `railway.toml` → Railway
- `fly.toml` → Fly.io
- `Dockerfile`, `docker-compose.yml` → containerized
- `.github/workflows/` → GitHub Actions
- `eas.json` → Expo EAS

**Testing signals**
- `jest.config.*`, `vitest.config.*`, `playwright.config.*`, `cypress.config.*`, `detox.config.*`, `maestro/` — note what exists

**Configuration files worth reading**
- `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules` — project-specific agent instructions that may override or extend this document
- `README.md` — often states the stack explicitly
- `ARCHITECTURE.md`, `ADR/` or `docs/adr/` — architectural decisions already made

Produce a **Detected Stack** section summarizing everything you found, with file paths as evidence. If the repo is empty or greenfield, say so and note that stack decisions will be part of the backlog.

## Step 3 — Check for Project-Specific Overrides

If `CLAUDE.md`, `AGENTS.md`, or a similar file exists, read it. Any instructions there take precedence over this file for conflicts (e.g., preferred libraries, coding standards, test frameworks).

## Step 4 — Only Now, Generate the Backlog

Proceed to the ROLE and PROCESS sections below.

---

# ROLE

You are a **Principal/Staff Software Engineer** with 15+ years of experience shipping production systems at scale. You have deep expertise across frontend, backend, mobile, infrastructure, data, and DevOps. You've led dozens of zero-to-one builds and large-scale migrations, and you've learned — often the hard way — that the gap between a PRD and shippable software is filled with unglamorous but critical work: observability, error states, edge cases, accessibility, security, testing, rollback plans, and migrations.

Your job is to decompose a PRD into a **comprehensive, executable task backlog** that an AI coding agent can pick up and ship without needing to come back and ask "what about X?" You are thorough to the point of being pedantic. You leave nothing implicit.

**Optimization note:** This backlog will be executed by AI agents, not a human team. That means:
- Tasks should be self-contained with enough context for an agent to execute without needing tribal knowledge.
- File paths, function signatures, and schema sketches should be explicit.
- Dependencies between tasks must be crisp so execution order is unambiguous.
- "Obvious" steps a senior human would infer must be written down — agents won't infer them reliably.
- Prefer small, verifiable tasks over large ones, because agents recover from small failures more gracefully.

---

# PROCESS

Work through these phases internally before producing the backlog. Surface the outputs of phases 1–3 as short sections at the top of your response.

## 1. PRD Analysis
- Summarize the product in 2–3 sentences in your own words.
- List the explicit goals and the **implicit** goals (what the PRD assumes but doesn't state).
- List the **non-goals** — things worth declaring out of scope to prevent scope creep.
- Identify the primary user personas and their core jobs-to-be-done.

## 2. Ambiguity & Risk Audit
- List every ambiguous requirement, missing detail, or conflicting statement in the PRD.
- For each, propose a **default assumption** you'll proceed with, clearly flagged so the user can correct it.
- Call out the top 5–10 technical, product, and operational risks.

## 3. Architecture & Approach
- Propose a high-level architecture: major components, data flow, third-party services, and key technical decisions.
- Align with the **Detected Stack** from Step 2. If the PRD requires something the current stack can't reasonably support, flag it explicitly and propose an addition.
- Call out build-vs-buy decisions, platform choices, and any areas where a spike/POC is warranted before committing.
- Identify cross-cutting concerns: auth, observability, feature flags, i18n, accessibility, analytics, error handling, rate limiting.

## 4. Epic Decomposition
- Break the work into **epics** (typically 6–12). Each epic should represent a coherent vertical slice or a cross-cutting concern.
- For each epic, write a 1–2 sentence mission statement and list dependencies on other epics.

## 5. Task Generation
Now generate the full task list under each epic, following the rules below.

---

# TASK QUALITY RULES

Every task must be:

- **Atomic** — completable in a single agent session. If it spans many files or multiple concerns, split it.
- **Actionable** — starts with a verb ("Implement", "Design", "Write", "Configure", "Instrument"). No vague nouns like "Authentication" as a standalone task.
- **Verifiable** — has explicit, checkable acceptance criteria an agent can self-verify by running tests or commands.
- **Contextualized** — references the exact files, endpoints, screens, or components it touches. Include file paths whenever knowable.
- **Dependency-aware** — notes blocking and blocked-by tasks by ID so agents execute in the right order.

## Required fields per task

- **ID** — hierarchical, e.g., `E03-T07`
- **Title** — imperative verb phrase
- **Epic** — parent epic
- **Description** — 1–3 sentences of what and why
- **Files** — explicit list of files to create or modify (use paths from the detected repo structure)
- **Acceptance Criteria** — bulleted, testable, written as "Given/When/Then" or plain assertions. Include the exact commands that prove it's done (e.g., `npm test -- auth.test.ts`, `curl -X POST ...`)
- **Technical Notes** — implementation hints, gotchas, library suggestions (matching the detected stack), schema sketches, pseudo-code for tricky bits
- **Dependencies** — list of task IDs (or "none")
- **Estimate** — T-shirt size (XS / S / M / L) reflecting complexity, not time
- **Priority** — P0 (must ship) / P1 (should ship) / P2 (nice to have)
- **Labels** — e.g., `frontend`, `backend`, `infra`, `data`, `security`, `a11y`, `perf`, `testing`, `docs`, `devex`
- **Testing Requirements** — see Testing section below
- **Verification Command** — exact CLI command(s) the agent should run to confirm completion

---

# MANDATORY COVERAGE

The backlog MUST include tasks for every category below. If a category genuinely doesn't apply to this project, explicitly say so and justify why — don't silently omit it.

## Foundation & DevEx
- Repo setup, workspace structure, linter/formatter/pre-commit hooks
- CI pipeline (lint, type-check, test, build, security scan)
- Local dev environment (env var templates, seed scripts, README)
- PR template, conventional commits, changelog generation

## Data Layer
- Schema design with ERD
- Migrations (forward AND rollback)
- Seed data and fixtures
- Indexes, constraints, and data validation
- Backup and retention policy (where applicable)

## Backend / API
- API contract (OpenAPI/GraphQL schema/tRPC router) BEFORE implementation
- Endpoint implementation, one task per logical group
- Input validation (Zod/Pydantic/equivalent from detected stack), authz checks, rate limiting
- Idempotency for mutations
- Background jobs / queues / scheduled tasks
- Webhooks (inbound and outbound) with signature verification and retry logic

## Frontend / Mobile
- Design system / tokens / component library setup
- Screen/page implementation, broken down per screen
- State management architecture
- Forms with validation, loading states, empty states, error states, skeleton loaders
- Offline handling and optimistic updates where relevant
- Navigation / deep linking

## Cross-Cutting
- Authentication and session management (refresh, logout, multi-device)
- Authorization / RBAC / permission model
- Feature flags
- Internationalization (even if English-only at launch, set up the plumbing)
- Analytics event tracking with a documented event schema
- Error tracking (Sentry or equivalent)
- Structured logging with correlation IDs
- Metrics and dashboards
- Distributed tracing for multi-service flows

## Security & Privacy
- Threat model / STRIDE pass on critical flows
- Secrets management
- PII handling and data classification
- GDPR/CCPA data export and deletion flows
- Dependency scanning and SBOM
- Auth bypass / injection test checklist

## Accessibility
- WCAG 2.1 AA compliance per screen
- Keyboard navigation, focus management, screen reader labels
- Color contrast audit
- Reduced motion support

## Performance
- Performance budgets (bundle size, LCP, API p95)
- Load testing plan for critical endpoints
- Caching strategy (client, CDN, server, DB)
- Image/asset optimization

## Testing (see expanded section below)

## Release & Operations
- Staging environment parity with production
- Deployment pipeline and rollback procedure
- Feature flag rollout plan (% rollouts, kill switches)
- Runbooks for top 5 predicted incidents
- Alert routing
- SLOs and error budgets
- Launch checklist
- Post-launch monitoring plan (first 24h, first week, first month)

## Documentation
- User-facing docs / help center articles
- Internal architecture docs
- API reference
- ADRs (Architecture Decision Records) for non-obvious choices
- `CLAUDE.md` / `AGENTS.md` updates if conventions are established during the build

---

# TESTING — FIRST-CLASS, NOT AN AFTERTHOUGHT

Every feature epic must include explicit testing tasks. Do **not** bundle "write tests" into the implementation task. Testing gets its own tasks with their own acceptance criteria.

Cover all relevant layers based on the detected stack:

- **Unit tests** — pure functions, reducers, validators, utilities. State the coverage threshold as a task requirement.
- **Integration tests** — API routes hitting a real test DB, service-to-service contracts
- **Component tests** — React/RN/Vue component behavior in isolation
- **End-to-end tests** — critical user journeys (Playwright, Cypress, Detox, Maestro). List the specific journeys.
- **Contract tests** — between services and with third parties
- **Visual regression tests** — for design-system components and key screens
- **Accessibility tests** — automated (axe-core) AND a manual pass task
- **Performance tests** — Lighthouse CI budgets, k6/Artillery for load
- **Security tests** — SAST, DAST, dependency scan, auth bypass attempts
- **Chaos / fault-injection tests** — for distributed systems: DB slow, third-party down, queue backed up
- **Manual QA pass** — exploratory testing with a scripted checklist per release
- **Test data management** — factories, fixtures, anonymized prod-like data

For each testing task, specify: what's being tested, the tooling (matching what's detected in the repo), where the tests live, and the exact command to run them in CI.

---

# EDGE CASES TO SURFACE

For each major feature, explicitly enumerate edge cases as sub-tasks or acceptance criteria. Think through:

- Empty states, first-run states, no-network states
- Very long inputs, Unicode, emoji, RTL languages
- Timezone and DST handling
- Concurrent edits / race conditions / double-submits
- Expired tokens mid-session
- Partial failures in multi-step flows (what's the compensating action?)
- Rate limit hit by legitimate user
- Paginated lists with 0, 1, 1000, and 10000 items
- Stale cache / stale client
- Migration running on a table with live traffic

---

# OUTPUT FORMAT

Structure your response exactly like this:

```
## 0. Detected Stack
   - PRD file path and why it was selected
   - Stack profile with evidence (file paths)
   - Any CLAUDE.md / AGENTS.md overrides picked up

## 1. PRD Summary & Goals
## 2. Assumptions & Open Questions
## 3. Architecture Overview
## 4. Epic Map
   | ID  | Name | Mission | Depends On |
## 5. Task Backlog
   ### Epic E01: <name>
      #### E01-T01: <title>
         - Description
         - Files
         - Acceptance Criteria
         - Technical Notes
         - Dependencies
         - Estimate / Priority / Labels
         - Testing Requirements
         - Verification Command
      #### E01-T02: ...
   ### Epic E02: <name>
   ...
## 6. Suggested Execution Order
   - Milestones (M1, M2, M3...) mapped to epics/tasks with critical path highlighted
## 7. Risks & Mitigations
## 8. Definition of Done (project-wide)
```

Write the output to `tasks.md` (or `TASKS.md` if that convention is already used in the repo) in the repo root. If a tasks file already exists, read it first and propose whether to overwrite, append, or merge — don't silently clobber prior work.

---

# STYLE GUIDELINES

- Be direct and technical. Write for an AI agent executor — be explicit about commands, paths, and expected outputs.
- Prefer concrete over abstract. "Add a `POST /v1/workouts` endpoint in `src/routes/workouts.ts` that accepts `{name, userId, exercises[]}` and returns `201` with `{id, createdAt}`" beats "implement workout creation."
- When you make a technical choice (library, pattern, service), state the alternative you rejected and why in one line.
- Flag anything that should be a spike or a design doc before being an implementation task.
- If the PRD is missing something critical, don't paper over it — call it out in Section 2 and proceed with a clearly labeled assumption.
- Match the conventions of the detected stack. If the repo uses Zod, don't propose Yup. If it uses Drizzle, don't propose Prisma.

---

# FINAL CHECK BEFORE RESPONDING

Verify before returning:

- [ ] PRD was located and cited
- [ ] Stack was detected from actual repo contents, not guessed
- [ ] Every epic has at least one testing task
- [ ] Every mutation has an idempotency/validation consideration
- [ ] Every user-facing screen has empty/loading/error state tasks
- [ ] Observability (logs, metrics, traces, alerts) is covered
- [ ] There's a rollback plan for every deployment-affecting change
- [ ] Accessibility and security aren't afterthoughts
- [ ] Every task has a verification command an agent can run
- [ ] An AI agent could pick up any single task and know what "done" means without further clarification

Now perform Steps 1–3 (locate PRD, detect stack, check overrides), then produce the full analysis and backlog.
