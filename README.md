# killcord

**Spending caps, rate limits, a big red pause button — and safe resume — for any agent loop.**

Stopping a runaway agent is easy. The hard part is resuming it safely afterward,
without either re-running the action that tripped the wire or losing the rest
of the loop's progress. killcord's whole reason to exist is that second part.

```bash
pip install killcord
```

```python
from decimal import Decimal
from killcord import Tripwire, guarded, TripwireTripped

tw = Tripwire(max_spend=Decimal("5.00"), max_actions=50, notify="ntfy://your-topic")


@guarded(tw)
def agent_loop():
    for step in plan:
        tw.check(step.as_action())  # raises TripwireTripped if this step is over-cap
        perform(step)
```

When it trips, you get a push notification, open `killcord serve`, see *the
exact action that tripped it*, and click approve / deny. The loop resumes
from exactly where it stopped — see [docs/resume-semantics.md](docs/resume-semantics.md)
for how that's made safe.

## Quickstart

```bash
pip install killcord
killcord serve &          # the pause server, http://127.0.0.1:8710
python examples/horror_story.py   # an agent told to buy the cheapest flight tries to buy 5
```

## Why

- Platform guardrails (OpenRouter) are platform-locked. Enterprise SOC tools aren't for individuals. Everything else that exists is stop-only.
- **Resuming safely is the unsolved part.** killcord snapshots the pending action, counters, and reason to disk *before* raising — so review-and-resume works even across a process restart.
- Framework-agnostic by design: a plain decorator/context-manager core, plus first-class adapters for the OpenAI SDK, Anthropic SDK (both via httpx-transport interception, so they work with any framework built on those SDKs), and LangChain.

## Integrations

| Framework | Setup |
|---|---|
| Plain Python | `tw.check(Action(...))` anywhere in your loop |
| OpenAI SDK | `from killcord.adapters.openai import guard_openai_client` |
| Anthropic SDK | `from killcord.adapters.anthropic import guard_anthropic_client` |
| LangChain | `from killcord.adapters.langchain import KillcordCallbackHandler` |

## Configuration

| `Tripwire(...)` kwarg | Default | Purpose |
|---|---|---|
| `max_spend` | `None` (no cap) | `Decimal` total spend cap |
| `max_actions` | `None` | Total action count cap |
| `rate` | `None` | `Rate(count, per="minute")` sliding-window cap |
| `allow_domains` | `None` (allow all) | e.g. `["*.mycompany.com"]` |
| `allow_tools` | `None` (allow all) | e.g. `["search", "read_file"]` |
| `store` | `~/.killcord/default` | Where snapshot/counter state lives |
| `notify` | `None` | `"ntfy://topic-name"` for phone push on trip |
| `ledger` | `None` | A `LedgerSink` — see [Synergy](#synergy) below |

## Security model

killcord decides whether an action is *permitted*; it doesn't sandbox or
intercept execution for you (except inside the OpenAI/Anthropic adapters,
which do intercept at the HTTP transport layer). **What this does NOT protect
against:** an agent (or a bug in your loop) that calls the real API directly
instead of going through `tw.check()`. Spend estimation from adapters is
best-effort — token-cost tables drift; treat `max_spend` as a strong signal,
not an exact accounting ledger.

The pause server is supported for local use only in v0.1. It defaults to
`127.0.0.1`; non-loopback binding has no built-in authentication or remote
request protections and prints a warning. See the [threat model](docs/threat-model.md).

## Roadmap

See [plan.md](plan.md). TypeScript port, LiteLLM/proxy adapter, and
pluggable notify backends are the tracked next steps.

## Synergy

Trip and resume events can be forwarded to
[agent-activity-ledger](https://github.com/ketriumlabs/agent-activity-ledger)
by passing `ledger=LedgerSink(url=..., api_key=...)` — see
[`src/killcord/ledger.py`](src/killcord/ledger.py).
The integration sends only a stable, non-secret trip ID and generic trip/decision
verbs; it omits action targets and caller-provided action metadata. Delivery is
best-effort, with a configurable 2-second default timeout, and is not crash-proof
or backed by an outbox. The Ledger provides tamper-evident records, not
tamper-proof storage. Ledger availability does not affect killcord's trip,
counter, or resume decisions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
