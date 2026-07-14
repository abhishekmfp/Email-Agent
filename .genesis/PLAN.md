# PLAN — Email-Agent

The machine-parseable implementation plan. Mirrors the milestone table in `DONE.html` (DONE.html is the
human/visual view; this is the one loops read). Sliced so each milestone ships in one L1 BUILD pass.

> Slicing rule: a milestone must have (a) a single clear outcome, (b) an exact **demo command** that
> proves it, and (c) a freeze boundary of files it may touch. If you can't write the demo command,
> the milestone is too vague — split it.

---

## Brainstorm (G0.5 — fill before slicing milestones)

> Three fundamentally different approaches to the cognitive job. Pick one. Record the rationale.
> This is the cheapest design decision — you haven't written a line of code yet.

### Approach A — Layered Clean / Onion with Ports & Adapters
Four layers (Interface → Application → Domain → Infrastructure adapters), dependency
direction inward (DIP). Domain imports nothing (no FastAPI, no Anthropic SDK, no Gmail
SDK). LLM and Email providers sit behind concrete adapters. HITL is two application use
cases (DraftEmail, ApproveAndSend) plus a domain Approval value object; the LLM never
touches send.
- Strengths: maps 1:1 onto the locked invariants; provider isolation is natural; canonical
  "production reference" shape; HITL is a deterministic boundary.
- Weaknesses: more boilerplate than a script-style app; risk of dogmatic over-layering.

### Approach B — Linear Pipeline / Functional Stages
Ordered typed stage functions (ValidateInput → LLMGenerate → ValidateDraft →
RenderPreview → Approve? → SendEmail). Approval is a blocking stage that yields to the
human; the pipeline resumes on approve.
- Strengths: very readable dataflow; each stage independently testable; minimal abstraction.
- Weaknesses: a human pause fractures the linear "pipeline" metaphor — you end up splitting
  into two runs anyway; approval-as-a-stage blurs the deterministic-control boundary.

### Approach C — Explicit State Machine / Workflow Lifecycle
A Draft aggregate with a lifecycle state (DRAFTED → AWAIT_APPROVAL → APPROVED → SENDING →
SENT). Transitions are guarded; send() is only legal from APPROVED; uncertain Gmail outcome
stays non-terminal so the human verifies before retry.
- Strengths: HITL gate is a structural guarantee; best fit for "no email reaches Gmail
  without explicit deterministic approval" and the unknown-delivery rule.
- Weaknesses: more machinery (state enum, guards) for a short flow; easy to over-engineer
  with persistence/event-sourcing V1 does not need.

### Chosen: Architecture A (baseline) + a lightweight domain state model from C — see rationale below

**Chosen architecture for Version 1 (recorded 2026-07-14, approved):**

- **Baseline:** Architecture A — Layered Clean / Onion with Ports & Adapters.
- **Adopt from C:** a *lightweight* domain lifecycle state model (plain state enum +
  guard logic). **No workflow engine, no persistence, no event bus.** In-memory only
  (sufficient for a single local user with minimal retention). This captures C's safety
  property — send only from `APPROVED`; an uncertain delivery outcome stays non-terminal —
  without C's machinery.
- **Application layer stays thin:** it orchestrates use cases (DraftEmail, ApproveAndSend)
  and delegates to services/domain; it does NOT contain business rules.
- **Introduce two services in the Application layer:**
  - `DraftGenerationService` — coordinates request → LLM adapter → structured draft →
    domain validation → lifecycle transition. Returns a preview + `PENDING` state.
  - `EmailDeliveryService` — coordinates the approved draft → Gmail adapter → send, with
    explicit timeouts and the unknown-delivery handling; only invoked after a deterministic
    `APPROVED` state.
- **Provider isolation via concrete adapters, not generic plugin interfaces:** one concrete
  `AnthropicLLMAdapter` and one concrete `GmailEmailAdapter`, each behind a narrow port used
  only by the Application/Domain. No plugin registry, no provider-abstraction framework —
  per the "extract abstractions only after multiple concrete implementations" principle.
- **Responsibility split (locked):**
  - **Domain** owns business rules, lifecycle state, and policies (approval validity,
    recipient resolution rules, draft schema/policy, validation).
  - **Application** owns orchestration (use-case flow, service calls, state transitions
    driven by human actions).
  - **Infrastructure** owns external integrations (Anthropic SDK, Gmail API/OAuth, config
    source, token store) and must never be imported by the Domain.

**Why this choice:** A is the only option that makes every non-negotiable invariant a
structural property (domain inward; Anthropic + Gmail isolated; provider isolation is the
single explicit extensibility need, satisfied by concrete adapters with no speculation).
C's safety idea is kept cheaply via the in-memory domain state enum. B was rejected because
the human pause fractures the linear metaphor and weakens the approval boundary. C as a full
state-machine was rejected as speculative machinery for a flow V1 handles in-memory.
Result: production-reference clarity, deterministic HITL, zero operational authority for the
LLM, and clean extension points for future LLM/Email providers — without over-engineering.

---

## Milestones

> Standard verification command (all milestones): `uv run ruff check src/ tests/ && uv run mypy src/email_agent && uv run pytest -q`
> Coverage targets (enforced from M2 onward): Domain ~100% · Application 90% · Infrastructure 80% · Overall 80%.

### M1 — Project Foundation   [STATUS: built, needs L4 close]
- **Outcome:** Reproducible, lint/type/test-clean Python 3.11 package with a working entry point and centralized typed configuration (AppSettings).
- **Phase (swe-master):** bootstrap
- **Files / freeze boundary:** `pyproject.toml`, `src/email_agent/main.py`, `src/email_agent/config/settings.py` (→ AppSettings), `uv.lock`
- **Demo command:** `uv run python -m email_agent.main`
- **Success criteria:** package builds; ruff/mypy/pytest pass; AppSettings loads from env with validation; milestone formally closed via L4 VERIFY + quiz-me Q&A.
- **Risk & Mitigation:** *uv.lock dirty / M1 never loop-closed.* Mitigation: commit uv.lock, run L4 VERIFY on existing bootstrap+config work, record quiz-me Q&A in a CURRENT-adjacent checkpoint before slicing further.
- **Loops:** L1, L4
- **Skills:** canon + tdd + data-systems-engineering
- **Token budget:** 50000

### M2 — Domain Model (Domain first)
- **Outcome:** A pure, framework-free domain modeling the email lifecycle and enforcing all business rules — no I/O, fully unit-tested.
- **Phase:** domain
- **Files:** `src/email_agent/domain/*.py` only (email_draft, recipient, approval, draft_policy, email_message, lifecycle)
- **Demo command:** `uv run pytest tests/domain -q`
- **Success criteria:** every domain invariant from context-graph holds; state transitions DRAFTED→AWAIT_APPROVAL→APPROVED→SENT; send() illegal except from APPROVED; recipient never inferred; DraftPolicy required-field/clarification rules; EmailDraft→EmailMessage conversion immutable; Domain ~100% coverage; domain imports nothing from infrastructure/framework.
- **Risk & Mitigation:** *Over-modeling (adding persistence/events not needed in V1).* Mitigation: keep domain in-memory value objects + plain state enum; no DB/event bus per G0.5 decision.
- **Loops:** L1, L4
- **Skills:** canon + tdd + modular-architecture
- **Token budget:** 50000

### M3 — Anthropic Drafting (Anthropic before Gmail)
- **Outcome:** End-to-end DRAFT flow — natural-language request → Anthropic → validated structured draft → EmailDraft in AWAIT_APPROVAL → preview. No send.
- **Phase:** integration (LLM)
- **Files:** `src/email_agent/infrastructure/anthropic_adapter.py`, `infrastructure/draft_validator.py`, `application/drafting_service.py`, `application/draft_email_use_case.py`, + tests
- **Demo command:** `uv run pytest tests/application tests/infrastructure -q` (acceptance test drives a sample request → validated draft → preview assertion; Anthropic mocked)
- **Success criteria:** AnthropicAdapter returns structured data only (no validation, no secrets, explicit timeout); DraftValidator validates LLM output before any EmailDraft is created; missing-info request triggers clarification; ruff/mypy/pytest green; Application 90% / Infrastructure 80% / Overall 80% coverage on drafting path.
- **Risk & Mitigation:** *Malformed/partial LLM output reaching the workflow.* Mitigation: DraftValidator rejects non-conforming output before EmailDraft creation; repeated invalid → surface app error (per Failure Tolerance).
- **Loops:** L1, L4
- **Skills:** canon + tdd + llmops-ai-agents
- **Token budget:** 50000

### M4 — Approval & EmailMessage (Approval before Delivery)
- **Outcome:** Explicit human approval converts the approved EmailDraft into an immutable EmailMessage; reject/edit invalidates prior approval and requires fresh approval.
- **Phase:** domain + application
- **Files:** `src/email_agent/application/approve_email_use_case.py`, `domain/email_message.py` (conversion already in M2), + tests
- **Demo command:** `uv run pytest tests/application -q` (acceptance: approve → EmailMessage in APPROVED; edit → back to AWAIT_APPROVAL; reject → no message)
- **Success criteria:** Approval is a deterministic domain value object; EmailMessage byte-identical to approved draft; GmailAdapter never invoked; editing invalidates approval; Application 90% coverage on approval/convert/reject paths.
- **Risk & Mitigation:** *Edit-after-approve silently sending the old version.* Mitigation: any modification returns lifecycle to AWAIT_APPROVAL; only the explicitly re-approved EmailMessage is deliverable (artifact_identity invariant).
- **Loops:** L1, L4
- **Skills:** canon + tdd + security-engineering
- **Token budget:** 50000

### M5 — Gmail OAuth Authentication (before delivery)
- **Outcome:** Independently demoable Gmail OAuth authentication — token acquisition, secure local storage, refresh — with no email delivery yet.
- **Phase:** integration (auth)
- **Files:** `src/email_agent/infrastructure/oauth_token_store.py`, `infrastructure/gmail_adapter.py` (auth surface only), + tests
- **Demo command:** `uv run pytest tests/infrastructure -q` (acceptance: OAuth flow yields tokens; OAuthTokenStore persists/refreshes isolated from logs; Gmail send path NOT exercised)
- **Success criteria:** OAuth tokens isolated behind a dedicated auth layer; tokens never logged/committed/prompted; refresh works; ruff/mypy/pytest green; Infrastructure 80% coverage on auth path.
- **Risk & Mitigation:** *Token leakage via logs or prompt.* Mitigation: OAuthTokenStore never logs token material; secrets withheld from LLM by data minimization (secrets_hygiene invariant).
- **Loops:** L1, L4
- **Skills:** canon + tdd + security-engineering
- **Token budget:** 50000

### M6 — Gmail Delivery (after OAuth + Approval)
- **Outcome:** DeliveryService sends the immutable EmailMessage via GmailAdapter (OAuth), with explicit timeout and unknown-delivery handling. Real Gmail send.
- **Phase:** integration (delivery)
- **Files:** `src/email_agent/infrastructure/gmail_adapter.py` (send surface), `application/delivery_service.py`, + tests
- **Demo command:** `uv run pytest tests/infrastructure tests/application -q` (acceptance: approved EmailMessage → real/sandboxed Gmail send; absence of approval → assert no send)
- **Success criteria:** GmailAdapter only called from DeliveryService, only from APPROVED; explicit timeout; uncertain delivery → reported, never auto-resend; delivered EmailMessage byte-identical to approved; ruff/mypy/pytest green; Infrastructure 80% / Overall 80% coverage.
- **Risk & Mitigation:** *Duplicate send on uncertain delivery.* Mitigation: unknown delivery state reported to user; no automatic resend (state_ownership + artifact_identity invariants).
- **Loops:** L1, L4
- **Skills:** canon + tdd + production-readiness
- **Token budget:** 50000

### M7 — Interface & Observability (stable app, thin outer layer)
- **Outcome:** FastAPI + CLI surfaces over the stable use cases, plus GET /health and structured logging with consistent secret-safe error responses.
- **Phase:** interface
- **Files:** `src/email_agent/interface/api/*.py`, `interface/cli/*.py`, `infrastructure/app_settings.py` (observability config), `main.py` wiring, + tests
- **Demo command:** `uv run uvicorn email_agent.interface.api:app --port 8000` then `curl -s localhost:8000/health` → `{"status":"healthy","version":"0.1.0"}` (plus POST /draft, /approve, /send exercising full flow)
- **Success criteria:** /health returns version, no sensitive config; structured logs mask recipients, never bodies/keys/prompts; every external failure → structured error; full HTTP flow draft→approve→send works; ruff/mypy/pytest green; Application 90% / Overall 80% coverage.
- **Risk & Mitigation:** *Interface layer leaking business rules.* Mitigation: interface delegates to use cases only; no domain logic in API/CLI (domain_inward invariant).
- **Loops:** L1, L4
- **Skills:** canon + tdd + production-readiness
- **Token budget:** 50000

### M8 — Production Hardening (gates, Docker, docs, quality)
- **Outcome:** Enforce all CI quality gates, ship Docker, reach coverage targets, sync docs and Genesis, ensure no secrets committed.
- **Phase:** hardening
- **Files:** `Dockerfile`, `.github/` (CI), `tests/` (raise coverage), `README`, `.env.example`, `docs/`, `.genesis/*` (notes/CURRENT/§3 sync), `pyproject.toml` (gates)
- **Demo command:** `docker build -t email-agent . && docker run --rm email-agent uv run pytest -q`
- **Success criteria:** every PR gate from DONE.html §2 passes (lint, format, mypy strict, pytest, coverage Domain~100%/App90%/Infra80%/Overall80%, Docker, schema-validation, no-secrets, docs-synced, conventional commits, Genesis-synced); uv.lock committed; legacy OpenAI references reconciled per the Architecture Decision.
- **Risk & Mitigation:** *Genesis drift during a long build.* Mitigation: M8 explicitly includes Genesis-sync as a stated task; update implementation-notes.html + CURRENT.md on each milestone close.
- **Loops:** L1, L4
- **Skills:** canon + tdd + production-readiness
- **Token budget:** 50000

Dependency chain (exact): M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8.
Each milestone leaves the tree green and demoable; later milestones only add outer layers / cross-cutting concerns, never rewrite inner ones.

---

## Progress (loops append here on milestone completion — newest last)

- 2026-07-13 — M1 Task 2 (Application Bootstrap): `src/email_agent/main.py` created. Logs
  ` Email-Agent started successfully` at INFO, `main()` returns 0. Verified via `py_compile` + run. Status: DONE.
- 2026-07-13 — M1 Task 1 (Project Foundation): `pyproject.toml` created (uv / PEP 621,
  Python 3.11, pydantic runtime dep, dev group ruff/mypy/pytest/pytest-cov). Status: DONE.
