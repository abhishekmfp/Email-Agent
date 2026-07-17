# Architecture — Email-Agent

Verified M1–M7 build. This document is the human-readable companion to
`.genesis/context-graph.json` (the machine-readable source of truth) and
`DONE.html` §1 (the locked spec).

## Style

**Layered Clean / Onion** with Ports & Adapters. Dependency direction is always
**inward** toward the domain. The domain imports no framework and no
infrastructure (no FastAPI, no Anthropic SDK, no Gmail SDK). LLM and email
providers sit behind concrete adapters — no generic plugin framework in V1
(extract the abstraction only when a second provider lands).

## Layers

```
interface/        FastAPI + CLI  (thin shell, delegates to one use case per endpoint)
   │
application/      DraftEmailUseCase · ApproveEmailUseCase · SendEmailUseCase
                  DraftingService · DeliveryService   (orchestration only)
   │
domain/          EmailDraft · Approval · EmailMessage · Recipient
                 DraftPolicy · lifecycle state (DRAFTED→AWAIT_APPROVAL→APPROVED→SENT)
   ▲
infrastructure/  AnthropicAdapter · GmailAdapter · GoogleOAuthClient
                 OAuthTokenStore · DraftResponseValidator · config/settings
```

| Layer | Key types | May import |
|-------|-----------|-----------|
| domain | `EmailDraft`, `Approval`, `EmailMessage`, `Recipient`, `DraftPolicy`, `draft_state` | nothing (pure) |
| application | `DraftEmailUseCase`, `ApproveEmailUseCase`, `SendEmailUseCase`, `DraftingService`, `DeliveryService` | domain, infrastructure (via DI) |
| infrastructure | `AnthropicAdapter`, `GmailAdapter`, `GoogleOAuthClient`, `OAuthTokenStore`, `DraftResponseValidator` | SDKs, domain types |
| interface | `api/`, `cli.py`, `models.py`, `translation.py`, `errors.py`, `logging.py`, `container.py` | application + config only |

## Send path (verified)

```
client → POST /send → SendEmailUseCase.execute(draft, decision)
                         ├─ ApproveEmailUseCase  → EmailMessage (frozen, APPROVED)
                         └─ DeliveryService.send(exact EmailMessage)
                                              └─ GmailAdapter → Gmail (OAuth)
```

`SendEmailUseCase` (M7, Option γ) is the **single** application-layer owner of
the approve-then-deliver composition. The interface composes nothing — it
delegates `/send` to exactly one use case (AC-UI-1). `ApproveEmailUseCase` and
`DeliveryService` are frozen and unchanged since verification.

## Locked invariants (CI-enforced)

1. **domain_inward** — domain imports no infra/framework; deps always inward.
2. **approval_gate** — no email reaches Gmail without an explicit `APPROVED`
   `Approval`. `GmailAdapter` is reached only via `DeliveryService`, only from
   `SendEmailUseCase` after `ApproveEmailUseCase` returns APPROVED.
3. **llm_output_validated** — `AnthropicAdapter` returns a typed `DraftResponse`;
   `DraftResponseValidator` validates it before any `EmailDraft` is created.
4. **outbound_timeout** — every outbound call (Anthropic, Gmail, OAuth refresh)
   has an explicit timeout.
5. **secrets_hygiene** — secrets never enter prompts, logs, or error responses;
   withheld from the LLM by data minimization.
6. **artifact_identity** — the delivered `EmailMessage` is byte-identical to the
   approved one; `SendEmailUseCase` forwards the exact instance (no rebuild).
7. **state_ownership** — the application owns all workflow state; the LLM owns
   none; the interface owns none (stateless — client holds `DraftResponseDTO`).

## Frozen decisions carried into M8

- **M4** — only `ApproveEmailUseCase` constructs `Approval`; `EmailMessage` is
  created once at approve and is immutable; `DeliveryService` delivers that exact
  instance.
- **M5** — PKCE public OAuth client (no secret); tokens outside repo at `0600`;
  `gmail.send` scope; `GoogleOAuthClient` owns OAuth; `refresh_if_needed()`
  before every send; `TokenRefreshError` ⇒ hard stop + re-auth, deliver the SAME
  message.
- **M3** — `AnthropicSettings` in `settings.py`; `anthropic==0.116.0`; typed
  `DraftResponse`; `PromptBuilder` extracted; domain LLM-agnostic.
- **M7** — `SendEmailUseCase` composition; one-endpoint-one-use-case; Translation
  Boundary (DTOs only, domain never crosses the wire); `B3` approver precedence
  (request → `APP_USER_NAME` → fail); interface-owned error envelope
  `{code, message, detail?}`; masked logging; stateless.

## M8 hardening (this milestone)

Cross-cutting only — no inner-module behavior changed:

- Per-layer coverage gate (`scripts/check_coverage.py`): domain ~100%,
  application ≥ 90%, infrastructure ≥ 80%, overall ≥ 80%.
- CI (`.github/workflows/ci.yml`): lint → format → mypy → pytest+coverage →
  coverage-gate → docker → gitleaks → conventional-commits.
- Pinned dev toolchain in `uv.lock` (deterministic gates).
- `gitleaks` secret scan; Conventional Commits (local `pre-commit` + CI action).
- Docker dev image; documented serve command (not a gate).
