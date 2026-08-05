# Kill-Cord — plan.md

**Verdict:** ✅ Build — differentiate on resume. Risk: Low-Med. Effort-to-payoff: Great.

**One-liner:** A one-line wrapper that gives any agent loop spending caps, rate limits, a big red pause button — and safe resume.

## Pressure test

- **Prior art:** Warmer than it looked. OpenRouter shipped platform-level Guardrails (spend/policy controls); at least one indie open-source "auto-stop runaway agents" project already made the rounds on DEV; enterprise SOC-guardrail products exist. A Forbes piece ("1.3 billion agents are coming, most have no kill switch") shows the narrative is mainstream.
- **The gap that remains:** Everything existing is either platform-locked (OpenRouter), enterprise, or stop-only. Nothing found does **snapshot-state → human review → resume where it left off** as a framework-agnostic drop-in library. Stopping is easy; resuming safely is the unsolved part.
- **Risks:**
  1. Framework-agnostic is hard — being honest, "wrap any agent loop" really means shipping first-class adapters for 2-3 frameworks and a generic decorator.
  2. OpenRouter-style platforms could absorb the feature — but self-hosted/local-model users are outside their reach.
- **Positioning:** Lead with resume-after-review as the headline feature, not the kill switch. The kill switch gets the HN title; resume gets the stars.

## Product scope

### MVP (v0.1.0)

- `Tripwire` — declarative limits: spend cap, action-count cap, rate cap (actions/minute), tool/domain allowlist.
- Usable three ways: decorator (`@guarded(tripwire)`), context manager, and explicit `tripwire.check(action)` for custom loops.
- **Trip → snapshot → review → resume**: on trip, serialize pending action + counters + reason; human approves/denies/adjusts from a phone-friendly local page; loop resumes from the snapshot idempotently.
- Pause server (`killcord serve`) with the big red button + live status; push notifications via ntfy.sh.
- Adapters: LangChain/LangGraph callback; OpenAI + Anthropic SDK interception at the HTTP-transport layer (works with any framework built on those SDKs); plain decorator for everything else.
- Trip and resume events POST to agent-activity-ledger when configured (`KILLCORD_LEDGER_URL` + key).

### Non-goals (v0.1)

TypeScript port (fast-follow, tracked issue from day one), dashboard analytics, multi-agent orchestration, policy DSLs, cloud/hosted anything. One agent, one tripwire config, one button.

## Architecture

```
 agent loop ──▶ @guarded / adapter ──▶ Tripwire.check(action)
                                          │ under limit → proceed, count/accrue
                                          │ over limit  → Snapshot.write() → raise TripwireTripped
                                          ▼
                                 SnapshotStore (JSON file, pluggable)
                                          ▲
     killcord serve  ◀── reads/updates ───┘
     (FastAPI, localhost, phone-friendly page)
     ├─ shows THE exact pending action that tripped
     ├─ approve / deny / adjust-cap  → writes Decision
     └─ notify: ntfy.sh topic (free push to phone)

 resume:  guarded loop restarts → finds snapshot + Decision
          → approved: replays/permits the pending action once (idempotency token)
          → denied: skips action, surfaces DeniedByHuman to the loop
```

### Design invariants (the hard 20% — write tests first)

1. **At-most-once execution of the tripped action.** The snapshot carries an idempotency token; resume consumes it atomically (file rename / transaction). If the process dies mid-resume, a second resume must not re-execute.
2. **Crash-safe trip.** Snapshot write is atomic (write-temp + fsync + rename) *before* the exception propagates. A killed process mid-trip leaves either no snapshot or a complete one — never a torn one.
3. **Spend accounting is explicit and honest.** Token-cost estimation tables drift; the API is `record_spend(amount)` called by adapters (which estimate from usage fields) *or* by the user directly. Docs state estimation error honestly.
4. **Tripwire state survives restarts.** Counters persist in the snapshot store, not process memory, so caps can't be reset by crashing.

## Public API sketch (freeze early — this is a library; API churn is the product killer)

```python
from killcord import Tripwire, guarded, TripwireTripped

tw = Tripwire(
    max_spend=Decimal("5.00"),  # currency-tagged, USD default
    max_actions=50,
    rate=Rate(20, per="minute"),
    allow_domains=["*.mycompany.com"],
    allow_tools=["search", "read_file"],
    store="~/.killcord/agent1",  # snapshot dir
    notify="ntfy://killcord-yourtopic",  # optional
    ledger=None,  # optional LedgerSink(url, key)
)


@guarded(tw)
def agent_loop(): ...


# or, inside a custom loop:
tw.check(Action(tool="browser.purchase", target="amazon.com", spend=Decimal("129.99")))
```

`TripwireTripped` carries `.snapshot_id` and `.reason`. `killcord resume <snapshot_id>` (or re-entering the guarded function) continues per the recorded decision.

## Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.10+ library (broad floor — libraries meet users where they are) | Widest install base |
| Core deps | stdlib + pydantic v2 only; FastAPI/uvicorn behind `killcord[server]` extra; adapters behind `killcord[langchain]`, `killcord[openai]`, `killcord[anthropic]` extras | A guard library must be nearly dependency-free |
| SDK interception | Custom `httpx` transport wrapped around OpenAI/Anthropic clients | Framework-agnostic at the one layer everything shares |
| Snapshots | JSON files, atomic rename; `SnapshotStore` protocol for future backends | Inspectable with `cat` — a trust tool must be auditable |
| Money | `decimal.Decimal` everywhere | Never float for spend caps |
| Packaging | hatchling, uv for dev; **no lockfile committed** (library, not app); `py.typed` marker | Standard library packaging |

## Repository layout

```
killcord/
├── src/killcord/
│   ├── core/          # Tripwire, Action, limits, Rate
│   ├── snapshot/      # store protocol, file store, idempotency tokens
│   ├── server/        # pause page (FastAPI + one Jinja2 template)
│   ├── notify/        # ntfy backend (protocol for others later)
│   ├── adapters/      # langchain.py, openai.py, anthropic.py
│   ├── ledger.py      # agent-event.v0 emitter (schema pinned, CI-validated vs ledger repo)
│   └── cli.py         # killcord serve|status|resume|approve|deny
├── tests/             # unit, property (hypothesis), crash tests, adapter tests
├── examples/          # the horror-story demo: "buy the cheapest flight" agent buying 5
├── docs/              # concepts.md, adapters/, resume-semantics.md, threat-model.md
└── community files (see standards below)
```

## Engineering & open-source standards

### License & legal

**Apache-2.0**, `LICENSE` at root, declared in `pyproject.toml`. Copyright `(c) 2026 Ketrium Labs`. No CLA; DCO optional, never gating.

### Community files (all present before the first feature commit)

| File | Standard |
|---|---|
| `README.md` | Structure below |
| `CONTRIBUTING.md` | Dev setup ≤5 commands, tests, PR expectations, commit convention |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| `SECURITY.md` | GitHub Security Advisories private reporting; ack ≤72h, fix-or-plan ≤14 days HIGH+ |
| `CHANGELOG.md` | Keep a Changelog, release-automation-driven |
| `.github/ISSUE_TEMPLATE/` | `bug_report.yml`, `feature_request.yml` |
| `.github/PULL_REQUEST_TEMPLATE.md` | Tests / docs / changelog checklist |
| `.github/dependabot.yml` | Weekly grouped, pip + github-actions |
| `.editorconfig`, `.gitignore` | 4-space Python, LF; `.killcord/` local state ignored |

Repo settings: Discussions on, squash-merge only, branch protection with required CI, `good first issue` labels seeded pre-launch.

### README structure

One-liner + horror-story demo GIF → badges (CI, PyPI, license) → **Quickstart** (`pip install killcord`, 6-line guarded loop) → why → adapters table → configuration reference → **security model: what killcord does NOT protect against** (a malicious agent bypassing the wrapper, spend estimation drift) → roadmap/contributing/license.

### Versioning & releases

- **SemVer** from `0.1.0`; pre-1.0 breaking changes bump minor with a **BREAKING** changelog entry. Because this is a *library*, API stability is the currency: deprecation warnings one minor version before removal, even pre-1.0.
- **Conventional Commits**, normalized on squash-merge.
- **release-please** → GitHub Release → **PyPI Trusted Publishing** (OIDC). Artifact attestations + signed tags.
- **Claim the `killcord` name on PyPI on day 0** — the name is part of the plan.

### CI/CD (GitHub Actions)

`ci.yml`: ruff (lint+format) → mypy --strict → pytest + coverage (≥85% on `core/` and `snapshot/`) on a matrix of **Python 3.10–3.13 × ubuntu/macos/windows** (file-atomicity semantics differ on Windows — test it, don't assume). Adapter tests run with pinned extras. `codeql.yml` weekly. `pip-audit` warn-only pre-1.0. Actions pinned to SHA; minimal permissions; separate release workflow with scoped `id-token: write`.

### Toolchain

`src/` layout, **ruff**, **mypy --strict**, **pytest** + `pytest-cov`, **hypothesis**, **pre-commit** hooks.

## Testing strategy

- **Property tests:** counters never exceed caps under any interleaving; rate limiter monotonicity.
- **Crash-injection tests:** `os._exit()` at every fault point in trip/resume paths (subprocess-based); assert at-most-once and no-torn-snapshot invariants.
- **Adapter contract tests:** recorded (vcr-style) OpenAI/Anthropic responses → spend estimation within documented tolerance; LangChain callback against a minimal fake agent.
- **End-to-end:** the examples/ horror-story script runs headless in CI — trips, auto-approves via API, resumes, asserts exactly one purchase.
- **Schema contract test:** emitted ledger events validate against the pinned `agent-event.v0.json` from agent-activity-ledger.

## Build plan — milestones

**M0 — Scaffold (day 0.5).** Community-file baseline, CI green, **PyPI name `killcord` claimed immediately.**

**M1 — Core (day 1).** Tripwire, limits, Action, decorator + context manager; crash-safe snapshot store. *DoD: property + crash tests green on all 3 OSes.*

**M2 — Pause server + notify (day 2).** `killcord serve`, big red button, ntfy push. *DoD: trip → phone notification → approve from phone → loop resumes, demoed on real hardware.*

**M3 — Review-and-resume (day 3).** Decision model, idempotent resume, `killcord resume` CLI. *DoD: at-most-once invariant proven by crash tests; `docs/resume-semantics.md` written — this doc is the moat; explain it better than anyone.*

**M4 — Adapters (day 4).** httpx-transport interception for OpenAI/Anthropic SDKs; LangChain callback. *DoD: each adapter runs the horror-story example unmodified except the wrapper line.*

**M5 — Hardening + ledger sink (day 5).** Failure-mode pass, ledger integration behind env config, schema contract test. *DoD: coverage ≥85% core; pip-audit clean.*

**M6 — Ship kit (day 6).** README with the horror-story demo GIF (agent told to "buy the cheapest flight" tries to buy 5 — tripped, reviewed from a phone, resumed correctly, exactly one ticket). *DoD: launch checklist ticked.*

**M7 — Launch (day 7).** `v0.1.0` on PyPI. Show HN titled on the kill switch, first paragraph pivots to resume. r/LangChain, r/LocalLLaMA. Cross-post to the ledger's audience ("from the maker of…").

### Launch checklist

- [ ] Quickstart verified in a clean venv on all 3 OSes
- [ ] Horror-story GIF embedded; examples/ runs green
- [ ] Community files present; 3–5 `good first issue` items filed (TS port is one)
- [ ] `v0.1.0` tagged + published with attestation
- [ ] Show HN draft + honest first comment pre-written
- [ ] 24h response SLO for week one

## Post-launch

TS port (`npm: killcord`) as the first fast-follow if traction; LiteLLM/proxy adapter; multiple tripwires per process; pluggable notify (Telegram, webhook). Analytics stays out — that's the ledger's job.

**Maintenance policy:** issues triaged weekly; security per SECURITY.md; scoped small, big asks → Discussions.

## Synergy with other ketriumlabs projects

Trip events log to [agent-activity-ledger](../agent-activity-ledger/plan.md) via its ingest API using `agent-event.v0` (`source.integration: "killcord"`) — first cross-project integration, second launch story ("from the maker of…").

## Sequence position

**Week 2-3**, a few weeks after the ledger ships.
