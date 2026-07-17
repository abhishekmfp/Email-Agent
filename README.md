# Email Agent

An AI-powered email assistant with **mandatory human-in-the-loop approval**
before every send. Natural-language requests are turned into structured,
high-quality drafts by Anthropic; a human reviews and approves; only then is the
exact approved message sent through Gmail via OAuth.

> Autonomy Level 1 (Assistive AI): the LLM performs cognition only. It never
> decides to send, authenticates, or owns workflow state. Every irreversible
> action requires explicit human approval enforced by deterministic application
> logic.

---

## Vision

Build a production-quality, reusable email agent: draft, review, approve, and
send email through Gmail — with the human always in control. V1 does one
workflow extremely well rather than many partially.

## How it works

```
natural-language request
        │
        ▼
  DraftEmailUseCase ──► DraftingService ──► AnthropicAdapter (LLM)
        │                                     ▲
        │                                     │ DraftResponse (validated)
        ▼                                     │
   DraftResult (AWAIT_APPROVAL) ◄─────────────┘
        │
   human reviews preview (client holds DraftResponseDTO)
        │  Send  ──►  SendEmailUseCase
        │                ├─ ApproveEmailUseCase  → immutable EmailMessage (APPROVED)
        │                └─ DeliveryService ──► GmailAdapter ──► Gmail (OAuth)
        ▼
   SendResult (SENT) — delivered message is byte-identical to the approved one
```

Key invariants (enforced in CI, see `docs/ARCHITECTURE.md`):

- **Approval gate** — no email reaches Gmail without an explicit `APPROVED`
  state. The interface never calls `DeliveryService` directly.
- **Artifact identity** — the exact `EmailMessage` instance produced at approval
  is the one delivered; it is never rebuilt from the draft.
- **Secrets hygiene** — API keys / OAuth tokens never enter prompts, logs, or
  error responses.

## Architecture (layers)

| Layer | Responsibility |
|-------|----------------|
| `domain/` | Pure business rules: `EmailDraft`, `Approval`, `EmailMessage`, `Recipient`, `DraftPolicy`, lifecycle state. No I/O, no framework. |
| `application/` | Use cases: `DraftEmailUseCase`, `ApproveEmailUseCase`, `SendEmailUseCase`, `DraftingService`, `DeliveryService`. Orchestration only. |
| `infrastructure/` | Concrete adapters: `AnthropicAdapter`, `GmailAdapter`, `GoogleOAuthClient`, `OAuthTokenStore`, `DraftResponseValidator`. |
| `interface/` | Thin shell: FastAPI + CLI. Delegates to exactly one use case per endpoint. No business logic. |

Dependency direction is always inward (Clean/Onion). The domain imports nothing
from infrastructure or any framework.

## Human-in-the-loop

The four user actions are **Draft, Edit, Send, Reject**:

- **Draft** → generate a structured draft (may return a clarification question).
- **Edit** → modify the draft; invalidates any prior approval (fresh approval required).
- **Send** → approves the current draft, then delivers it. Send *is* the
  approve+send action.
- **Reject** → discards; nothing is sent.

The approver identity falls back to `APP_USER_NAME` (config) when not supplied
per request.

## Setup

### 1. Install

```bash
uv sync --dev
```

### 2. Configure environment

```bash
cp .env.example .env   # then fill in real values
```

Required variables:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key (LLM). Never logged/prompted. |
| `ANTHROPIC_MODEL` | Model id (default `claude-3-5-haiku-latest`). |
| `GMAIL_CLIENT_ID` | Google OAuth **Desktop** client id (PKCE public client — no secret). |
| `GMAIL_FROM_ADDRESS` | Authenticated send address (MIME `From`). |
| `APP_USER_NAME` | Local human identity used as the approver fallback. |

> OAuth tokens are stored **outside the repo** at `0600` perms and are
> gitignored. No client secret is stored (PKCE public-client flow).

### 3. Authenticate with Gmail

Run the interactive OAuth flow once to obtain and store tokens:

```bash
uv run python -m email_agent.infrastructure.google_oauth_client
```

(One-time browser consent; tokens are persisted for later sends.)

## Run

### CLI

```bash
uv run email-agent draft  --request "Email Alice about the Q3 report, friendly tone"
uv run email-agent edit   --field body --value "Updated body text"
uv run email-agent send   --approver "Your Name"
uv run email-agent reject
```

### HTTP API (FastAPI)

```bash
uv run uvicorn email_agent.main:app --port 8000
```

| Method | Route | Delegates to |
|--------|-------|--------------|
| POST | `/draft`  | `DraftEmailUseCase` |
| POST | `/edit`   | `ApproveEmailUseCase` (decision=edit) |
| POST | `/send`   | `SendEmailUseCase` (approve + deliver) |
| POST | `/reject` | `ApproveEmailUseCase` (decision=reject) |
| GET  | `/health` | returns `{"status":"healthy","version":"<ver>"}` |

### Docker

```bash
# Run the full test suite inside the image (CI gate):
docker build -t email-agent .
docker run --rm email-agent uv run pytest -q

# Serve the API (not part of the CI gate):
docker run --rm -p 8000:8000 --env-file .env email-agent \
  uv run uvicorn email_agent.main:app --host 0.0.0.0 --port 8000
```

## Development

Quality gates (run locally or via `pre-commit`):

```bash
uv run ruff check src/ tests/      # lint
uv run ruff format --check src/ tests/   # format
uv run mypy src/email_agent        # strict type check
uv run pytest --cov=email_agent --cov-report=json=coverage.json -q
uv run python scripts/check_coverage.py coverage.json   # per-layer floors
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
(enforced locally via pre-commit and in CI).

## Future (out of scope for V1)

Contact management, calendar integration, attachments, scheduling, conversation
history, multi-agent workflows, Outlook support, memory/personalization,
multi-user/RBAC, metrics/tracing.

## License

MIT
