# decisions-manifest — Email-Agent
Generated: 2026-07-14 via KICKOFF-INTERVIEW.md (resume session)
Method: Genesis G0 Cognitive Design — engineering interview, one question at a time.
Status: accepted (pending user approval to write into DONE.html / PLAN.md).

---

## Project Vision

This repository has two goals:

1. Build a production-quality, reusable Email Agent that any developer can clone,
   configure with their own Gmail and LLM credentials, and use to draft, review,
   approve, and send emails through Gmail.
2. Serve as the reference implementation for applying the Genesis workflow, and as
   the foundation for the future **Abhishek Engineering Flow (AEF)**.

Version 1 focuses on doing one workflow extremely well — natural-language request →
structured draft → human preview → explicit approval → real Gmail send — rather than
implementing many partially completed features.

---

## Architecture Decision (recorded explicitly, not as a discrepancy)

**DECISION — LLM Provider Standardization.**
Version 1 standardizes on **Anthropic** as the sole LLM provider. All LLM interactions
are isolated behind a dedicated module; the rest of the application must never depend
directly on the Anthropic SDK (or any provider SDK). Remaining OpenAI references in the
repository (e.g. README "OpenAI SDK" mention, OpenAISettings examples in code comments)
are **legacy scaffold artifacts** and will be updated during documentation
synchronization (a CI quality gate). This decision does not introduce a generic plugin
abstraction — V1 ships one concrete provider behind a clean module boundary; the shared
provider interface is to be extracted only when a second provider is actually added.

---

## Scope

**IN SCOPE (Version 1.0 — production quality, not a demo):**
- Python 3.11 project using `uv`.
- Clean modular architecture.
- FastAPI backend.
- Gmail OAuth authentication + real Gmail integration (no mocked sending).
- Anthropic-powered natural-language understanding.
- Extract recipient, subject, body, tone, and intent from user requests.
- Generate professional email drafts.
- Human-in-the-loop approval before every send.
- Send the approved email through Gmail.
- Structured configuration management; logging; error handling; validation.
- Unit + integration tests; production-ready code quality.
- Fully documented, reusable, open-source repository.
- Docker support; environment-based configuration.

**OUT OF SCOPE for V1 (deferred to future milestones):**
Multi-agent orchestration, long-term memory, RAG, calendar integration, contact
management, Outlook support, attachment intelligence, autonomous sending without
approval, scheduling, conversation history, MCP integration, voice interface, browser
automation.

---

## Intended Users

- **Primary:** individual developers, AI engineers, technical professionals, and power
  users who run the agent locally with their own Gmail account and LLM API key.
  First-class user is technically capable (clones repo, sets env vars, completes OAuth,
  runs locally).
- **Secondary (future, not V1 design targets):** developers embedding the FastAPI
  service; internal enterprise deployments; desktop/web front-ends; multi-user
  deployments.
- **Approval model:** in V1 the requester and the approver are the same individual.
  No separate approval roles, delegated approval, or multi-user workflows.

---

## Core Cognitive Job

The AI's central cognitive job is to understand human intent and transform an imprecise
natural-language request into a complete, structured, high-quality email draft.

The LLM is responsible for:
- understanding user intent;
- extracting structured information (recipient, subject, body, tone, purpose);
- identifying missing or ambiguous information;
- asking clarifying questions when required;
- producing a professional email draft in a structured format.

The LLM is NOT responsible for: deciding whether to send, triggering Gmail, performing
OAuth/auth, enforcing business rules, making approval decisions, system security, or
application state management. Those are deterministic application logic.

**Ambiguity handling:** the LLM must never invent missing factual information (recipients,
dates, times, commitments, business decisions). If essential information is missing or
ambiguous, it asks concise clarification questions before producing the final draft.
Reasonable language improvements (grammar, tone, formatting, professionalism) may be
inferred automatically. The cognitive boundary of the AI ends once a validated draft has
been produced.

---

## Inputs

1. **User request:** a single free-text natural-language request per interaction.
   No persistent conversation memory or multi-turn session state beyond the
   clarification questions needed to complete the current email. No structured fields
   required from the user.
2. **Configuration & credentials (startup-time, never per-request):** LLM API key,
   model name, Gmail OAuth credentials, access/refresh tokens (OAuth-managed), and
   application config (environment, logging). Loaded from the configuration system and
   secure env vars, never from user prompts.
3. **External context:** minimal. Available = the user's request + optional one-time
   user profile (e.g. name, preferred signature). NOT available = contact DB, calendar,
   previous emails, long-term memory, RAG, knowledge base, cross-session history, CRM.
   Missing info → ask the user, do not retrieve externally.
4. **Validation & sanitization:** every incoming request is untrusted. Before any
   content reaches the LLM the application rejects empty/malformed requests, enforces
   size limits, strips invalid control characters, validates encoding, and protects
   against prompt injection by separating system instructions from user content.
   Secrets/prompts are never exposed to the LLM via user input.

---

## Outputs

1. **AI draft output:** a strongly-typed structured draft object (recipients, subject,
   body, tone, purpose/intent, optional confidence, clarification-required flag, missing
   fields). The LLM never returns only a rendered string. The application renders this
   object into a human-readable preview; the structured object is the AI↔app contract.
2. **Final system output:** after approval + successful Gmail delivery, returns both the
   Gmail result (message ID, thread ID if available, timestamp) and a human-readable
   success response. On failure: a structured error response confirming no email was
   sent.
3. **Human approval:** the human approves a rendered preview. The structured draft is an
   internal object. Approval is an explicit application action (CLI yes / API call / future
   UI button). Only the application converts an approved draft into a send request.
4. **Edit / reject:** the user may Approve, Edit, or Reject. Editing does NOT constitute
   approval; any modification invalidates prior approval and requires a fresh explicit
   approval of the final version. Rejection → nothing sent, workflow terminates, no Gmail
   action, draft discarded (V1 persists no draft history).
5. **Error / observability:** every failure yields a deterministic structured error
   response + appropriate log entry. Secrets (keys, tokens, prompts) never appear in logs
   or user-visible errors. On send failure the system guarantees no intentional partial or
   duplicate email.

---

## Human Approval Requirements

- Approval is a hard, non-bypassable gate enforced entirely by deterministic application
  logic — never by the LLM.
- There is no code path by which a draft reaches Gmail without passing through an explicit
  Approved state. The LLM cannot call Gmail, invoke the send service, change approval
  state, bypass approval, trigger retries, or execute side effects.
- Valid approval = explicit, intentional application action from the interface (single
  local authenticated user; no RBAC/delegated approval in V1).
- Auto-send policy: V1 never auto-sends. Every send — including regenerated drafts, edited
  drafts, retries after transient failures, repeated attempts — requires explicit approval
  for that specific draft. No exceptions.
- The delivered email must be byte-identical to the version explicitly approved.

---

## Failure Tolerance

Priority order: Safety > Correctness > Transparency > Reliability > Automation.
"It is always better to delay sending an email than to send the wrong email."

- **Cost of wrong sends:** Level 1 (grammar/tone) acceptable via human review; Level 2
  (wrong subject, missing recipient name) normally caught in review; Level 3 (wrong
  recipient, confidential/PII leakage, false commitments, wrong dates, financial errors)
  are catastrophic and must never reach Gmail without explicit human approval.
- **Transient failures (OpenAI timeout/rate-limit, Gmail 5xx, network):** conservative
  automatic retries with exponential backoff for infra errors only; surface to user if
  retries fail. Never silently resend.
- **Partial failure (Gmail accepts but app crashes before recording success):** report an
  "Unknown Delivery State"; never auto-resend. User verifies delivery before retrying.
  Exactly-once cannot be guaranteed (Gmail is external); aim for "never resend when
  delivery status is uncertain."
- **Draft quality failures:** every LLM response schema-validated before the approval
  workflow. Valid → continue; missing fields → clarify; schema failure → retry; repeated
  invalid → surface app error. Malformed AI output is never presented as an approved draft.

---

## Trust Boundary

Four trust zones:
- **Zone 1 — External Input (untrusted):** user requests, CLI/API input, unvalidated env
  vars, network/API responses. Nothing auto-trusted.
- **Zone 2 — Application (trusted):** owns validation, state, approval workflow,
  authentication, authorization, config, Gmail integration. Only the app may invoke side
  effects.
- **Zone 3 — LLM (restricted trust):** trusted for reasoning only (understand, clarify,
  draft). Never accesses credentials/tokens, calls Gmail, modifies state, approves, or
  sends.
- **Zone 4 — Gmail (external):** app communicates only after explicit approval; LLM never
  talks to Gmail directly.

Sensitive assets ranked: (1) Gmail send capability (impersonation risk) > (2) Gmail OAuth
credentials > (3) LLM API key > (4) user email content. Prompt injection → secret
exfiltration is a modeled threat; secrets are withheld from the LLM by data minimization,
not by prompt obedience. Recipient trust: never send to an unapproved recipient; AI never
invents/infers recipients; preview must show every final recipient before approval.

---

## AI Autonomy Level

**Autonomy Level 1 (Assistive Intelligence).** The AI may perform cognitive tasks
(understand intent, choose style/tone, structure the email, ask clarifications, improve
grammar). It has zero operational authority — no irreversible actions, no external side
effects. Infrastructure behaviors (retrying an LLM call, validating output, rendering,
loading config) are deterministic app behavior, not AI autonomy. The human controls the
final artifact at every step; the outgoing email always represents an explicit human
decision.

Specification line: *Version 1 is an Autonomy Level 1 (Assistive AI) system. The AI is
authorized only to perform reasoning and draft generation. Every irreversible external
action — including Gmail delivery — requires explicit human approval enforced by
deterministic application logic. Human review occurs after every AI-generated draft and
before every email send.*

---

## Security / Privacy Expectations

Local-first, privacy-by-design; runs on the developer's own machine; never a cloud service
in V1.

- **Credential storage:** static config (LLM key, model, app config) via env vars; OAuth
  tokens stored locally in a dedicated token file behind an isolated auth layer (encrypted
  local storage / OS keyring may follow). Secrets never committed, logged, embedded in
  source, or placed in prompts.
- **Logging privacy:** log startup/shutdown, config status (never values), auth + workflow
  state transitions, validation/API failures, retries, app errors. Never log email bodies,
  API keys, OAuth tokens, auth headers, prompt contents, full recipient addresses, or
  system prompts. Identifiers may be partially masked (e.g. `a***@company.com`).
- **Prompt-injection defense:** strict separation of system instructions / app context /
  user request using provider structured message roles (system vs user); user text never
  concatenated into system instructions; plus validation of every structured LLM output.
  Security relies on deterministic controls, not prompt obedience.
- **Supply chain:** `uv.lock` committed, pinned versions, reproducible env, reviewed
  updates; dependency vulnerability scanning, secret scanning, static analysis, lint, type
  check, automated tests in CI.
- **Data retention:** minimal. No conversation history, analytics, telemetry, usage
  tracking, cloud sync, long-term memory, or training-data collection. Drafts exist only
  for the current workflow unless explicitly saved. User data goes only to the configured
  LLM provider and Gmail APIs required for the task.

---

## Non-Functional Requirements

- **Performance:** startup < 3s; request validation < 100ms; AI draft gen typically < 10s
  (LLM-dependent); draft render near-instant; Gmail send shows immediate progress. Single
  local user; concurrency explicitly out of scope (architecture must not prevent future
  scale).
- **Reliability:** on-demand local app, not 24/7. Goals: predictable behavior, deterministic
  state transitions, graceful failure, no silent data loss, no unintended sends.
  Correctness > uptime.
- **Testing:** unit tests (core logic), integration tests (workflows), mocked LLM + mocked
  Gmail, config/schema/error/approval tests. ≥80% overall coverage; critical paths
  (approval, send pipeline, config, validation) approach 100%. External services mocked;
  live OpenAI/Anthropic + Gmail as optional integration tests.
- **Quality gates (per PR):** ruff lint + format; mypy strict; pytest green; coverage
  threshold met; Docker builds; every LLM response schema-validated; no secrets committed;
  docs synced with implementation; Conventional Commits; Genesis docs updated on
  architecture/workflow change.
- **Observability:** structured logging (human-readable console by default, JSON-easy
  later); FastAPI `GET /health` returning `{"status":"healthy","version":"<ver>"}` — no
  expensive checks, no sensitive config exposed.

---

## Future Extensibility

Build today's requirements so they don't prevent tomorrow's evolution; avoid speculative
abstraction.

**Leave clean extension points for (realistic evolutions):**
- LLM provider — isolate all LLM calls behind a dedicated module; V1 uses Anthropic only;
  rest of app never depends on the SDK. Future providers added without touching business
  logic.
- Email provider — isolate Gmail behind a dedicated email-service module; workflow never
  depends on Gmail-specific concepts outside it. Future Outlook/Exchange = new provider,
  not workflow changes.
- Configuration — centralized Settings layer; future provider settings as independent
  sections.
- Authentication — isolated from email workflow; future auth mechanisms don't alter draft/
  approval logic.

**Do NOT shape V1 for:** multi-agent, memory, RAG, calendar, CRM, browser automation, voice,
autonomous execution, multi-user approval, scheduling.

**Provider architecture:** NOT a generic plugin system in V1 (one LLM, one email provider).
One concrete implementation with clean module boundaries; extract the shared abstraction
only when a second provider is added.

**Non-negotiable architectural invariants:**
- Layering: domain/business logic never imports FastAPI, the Anthropic SDK, or the Gmail
  SDK.
- Dependency direction: inward toward the domain; outer layers depend on inner, inner never
  on infrastructure.
- LLM boundary: LLM produces only structured outputs; app validates every output before
  use.
- Approval boundary: no email reaches Gmail without explicit deterministic approval.
- State ownership: application exclusively owns state; LLM never owns workflow state.
- Timeouts: every outbound network request has explicit timeouts.
- Validation: every external input, every LLM output, every config value validated.
- Error handling: no exception terminates the app without a meaningful error.
- Observability: every significant workflow transition emits a structured log event.
- Security: secrets never enter prompts, logs, or source control.
- Testing: critical workflow components independently testable without live external
  services.

---

## Engineering Principles

- AI performs cognition. Software performs control. Humans retain authority.
- Every irreversible side effect requires deterministic application control and explicit
  human approval.
- When uncertainty exists, stop automation and involve the human.
- The LLM possesses cognitive capability but zero operational authority.
- Design for change, not speculation. Extract abstractions only after multiple concrete
  implementations.
- The safest secret is the one the model never receives.

---

## Assumptions the agent inferred from the interview (not stated verbatim)

- V1 is a single-process local application; the FastAPI service is for local/programmatic
  use, not public exposure.
- "Production-quality" means engineering rigor (tests, CI gates, typed contracts), not
  horizontally-scaled production hosting.
- The repository itself is the product deliverable (open-source reference), so docs and
  Genesis hygiene are first-class, not optional polish.
- Recipient resolution from a name (when added later) must come from an approved contact
  source, never from free text alone.
