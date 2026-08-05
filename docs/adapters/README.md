# Adapters

| Adapter | Install | What it intercepts |
|---|---|---|
| [OpenAI](../../src/killcord/adapters/openai.py) | `pip install "killcord[openai]"` | The OpenAI SDK's httpx transport — works with sync `OpenAI` and async `AsyncOpenAI` clients, and with any framework built on top of that SDK (since interception happens below the SDK's own methods). |
| [Anthropic](../../src/killcord/adapters/anthropic.py) | `pip install "killcord[anthropic]"` | Same approach as OpenAI, for `Anthropic`/`AsyncAnthropic`. |
| [LangChain](../../src/killcord/adapters/langchain.py) | `pip install "killcord[langchain]"` | Tool calls, via `BaseCallbackHandler.on_tool_start`. Spend estimation is a no-op by default — subclass `KillcordCallbackHandler` and override `estimate_spend()` for real accounting. |

## Writing a new adapter

1. Call `tripwire.check(Action(...))` at the point where the framework is
   about to perform a real network/tool call — before it happens, not after.
2. Raising `TripwireTripped` should actually stop the framework's run. Some
   frameworks swallow callback exceptions; verify yours doesn't (LangChain's
   `on_tool_start` propagates; that's why it works).
3. Run [`examples/horror_story.py`](../../examples/horror_story.py)'s
   scenario through your adapter as a test.
4. Add a row to the table above and a short usage snippet.
