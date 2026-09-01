# Gemini Chatbot with Memory

A production-ready, memory-aware conversational chatbot built on the official
[Google Gen AI Python SDK](https://github.com/googleapis/python-genai)
(`google-genai`). It maintains full conversational context for the duration
of a session, so Gemini can naturally refer back to anything said earlier.

## Project layout

```
gemini_chatbot/
├── main.py                 # Entry point: wires config, memory, client, CLI together
├── chatbot/
│   ├── __init__.py         # Public package API
│   ├── config.py           # Env-driven configuration + validation
│   ├── memory.py           # Conversation history storage (sliding window)
│   ├── client.py           # Gemini API wrapper: calls, retries, error mapping
│   ├── cli.py               # Interactive terminal loop (commands, I/O)
│   └── exceptions.py       # Package-specific exception hierarchy
├── requirements.txt
├── .env.example
└── README.md
```

## Architecture

The design separates four concerns that are easy to tangle together in a
"quick script" chatbot, but which cause pain at production scale if they
aren't:

| Layer | Module | Responsibility |
|---|---|---|
| **Configuration** | `chatbot/config.py` | Loads and *validates* every setting from environment variables once, at startup, into an immutable `Config` object. No `os.environ` calls anywhere else in the codebase. Fails fast with a clear message if the API key is missing. |
| **Memory** | `chatbot/memory.py` | `ConversationMemory` is a small, **provider-agnostic** store of `{"role", "content"}` dicts, unchanged from the original design. It knows nothing about HTTP or any specific SDK — it just tracks turns and enforces a bounded sliding window so a very long session doesn't grow the request payload (and cost/latency) unbounded. Trimming always removes from the *front in pairs*, so history never starts with a dangling assistant message. |
| **API client** | `chatbot/client.py` | `GeminiChatbot` is the only module that talks to Google. On every `send_message()` call it pulls the *entire* current history from `ConversationMemory` and translates it into Gemini's `types.Content` format — this is what gives Gemini full context on every turn. It validates input, retries transient failures (rate limits, connection errors, 5xx) with exponential backoff + jitter, and translates every `google-genai` SDK exception into the package's own `APICommunicationError`/`InvalidInputError` so callers never need to import `google.genai` themselves. If a call fails after retries, the just-added user turn is rolled back so memory never contains an unanswered, dangling message. |
| **Interface** | `chatbot/cli.py` + `main.py` | A thin terminal REPL: reads input, dispatches `/help`, `/history`, `/clear`, `/exit`, and otherwise calls `bot.send_message()`. This layer is intentionally dumb — swapping it for a web API or Slack bot later means writing a new thin layer, not touching memory or client logic. |

**Why full history is sent on every call:** the Gemini `generate_content`
API is stateless — it has no memory of previous requests. Context is
established purely by what's included in the `contents` array of the
*current* request. `ConversationMemory.get_history()` returns the
provider-agnostic turn list, and `client.py` translates it into Gemini's
`types.Content` objects on every call, so every request is automatically
context-aware with no extra bookkeeping at the call site.

**Role mapping:** internally, memory still stores turns as `"user"` /
`"assistant"` (unchanged from the original design, and reusable if this
project is ever pointed at a different provider again). Only `client.py`
translates `"assistant"` → Gemini's `"model"` role when building a request.
The system prompt is no longer a message in the history at all — it's sent
once per request via `GenerateContentConfig(system_instruction=...)`, which
is the Gemini equivalent of Claude's separate top-level `system` parameter.

**Error handling strategy:** exceptions are categorized into *retryable*
(HTTP 408/429/500/502/503/504 — transient, worth an exponential-backoff
retry) and *non-retryable* (401/403 authentication/permission errors, 400
bad requests — retrying would just fail again, so these surface
immediately). All of them are ultimately normalized to
`APICommunicationError` so the CLI (or any other caller) only needs one
`except` clause.

## Setup

**1. Install dependencies** (Python 3.9+):

```bash
pip install -r requirements.txt
```

**2. Configure your API key:**

```bash
cp .env.example .env
# then edit .env and set GEMINI_API_KEY=... (get one at https://aistudio.google.com/apikey)
```

**3. Run:**

```bash
python main.py
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | **Yes** | — | Your Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Model identifier to use |
| `GEMINI_MAX_TOKENS` | No | `1024` | Max output tokens generated per reply |
| `GEMINI_TEMPERATURE` | No | `0.7` | Sampling temperature (0.0–2.0) |
| `MAX_HISTORY_MESSAGES` | No | `50` | Max messages kept in the sliding-window memory |
| `GEMINI_REQUEST_TIMEOUT` | No | `60.0` | Per-request timeout, in seconds |
| `GEMINI_MAX_RETRIES` | No | `3` | Retries for transient API failures |
| `GEMINI_SYSTEM_PROMPT` | No | *(a friendly assistant prompt)* | System instruction sent with every request |

## CLI commands

| Command | Effect |
|---|---|
| `/help` | Show available commands |
| `/history` | Print the current conversation history |
| `/clear` | Wipe conversation memory and start fresh |
| `/exit`, `/quit` | End the session |

## Example conversation demonstrating contextual memory

```
============================================================
 Gemini Chatbot with Memory  —  type /help for commands
============================================================
Type your message and press Enter. Conversation context is kept for the whole session.

You: Hi, I'm Priya and I'm planning a trip to Kyoto next spring.
Gemini: Hi Priya! Kyoto in spring is a wonderful choice — you'll likely catch
the cherry blossoms if you go in late March to early April. Are you
thinking of a specific week, and is this a solo trip or with others?

You: It'll be with my sister. We're both really into traditional tea ceremonies.
Gemini: That's a great pairing with Kyoto — it's one of the best places in
the world for an authentic tea ceremony experience. A couple of options for
you and your sister: Camellia Garden near Kiyomizu-dera offers ceremonies in
English, and En Tea House does a more intimate, traditional setting. Want me
to sketch out an itinerary built around that?

You: Yes please, and remember we don't eat meat.
Gemini: Got it — I'll keep both the tea-ceremony focus and vegetarian dining
in mind. Here's a rough 3-day outline for you and your sister:

Day 1: Arrive, settle in near Gion, evening walk through the historic
streets, vegetarian kaiseki dinner.
Day 2: Morning tea ceremony at Camellia Garden, afternoon at Kiyomizu-dera
and the nearby craft shops, vegetarian-friendly udon for dinner.
Day 3: Fushimi Inari shrine at sunrise (before the crowds), tea ceremony at
En Tea House in the afternoon, farewell dinner at a vegetarian shojin-ryori
restaurant.

Want me to add day trips outside the city, like Nara or Arashiyama?

You: What was the name of that first tea house you mentioned again?
Gemini: The first one I mentioned was Camellia Garden, near Kiyomizu-dera —
that's the one offering ceremonies in English, which I suggested for Day 2
of your itinerary with your sister.

You: /history
--- conversation history ---
You: Hi, I'm Priya and I'm planning a trip to Kyoto next spring.
Gemini: Hi Priya! Kyoto in spring is a wonderful choice...
You: It'll be with my sister. We're both really into traditional tea ceremonies.
Gemini: That's a great pairing with Kyoto...
You: Yes please, and remember we don't eat meat.
Gemini: Got it — I'll keep both the tea-ceremony focus...
You: What was the name of that first tea house you mentioned again?
Gemini: The first one I mentioned was Camellia Garden...
-----------------------------

You: /exit
Goodbye!
```

Notice that in the final answer, Gemini correctly recalls **Priya's name**,
**who she's traveling with**, her **dietary restriction**, and the
**specific tea house named several turns earlier** — all without those
details being repeated in the latest message. This works because every
turn (`user` and `assistant`) is stored by `ConversationMemory` and the
*entire* history is resent (translated into Gemini's `Content` format) on
every API call.

## Migration notes (Claude → Gemini)

This project was originally built against the Anthropic Claude API and has
been ported to Google's Gemini API. What changed and what didn't:

- **Unchanged:** `chatbot/memory.py` (the sliding-window `ConversationMemory`
  store), the overall four-layer architecture, the CLI commands, and the
  retry/backoff strategy shape.
- **Changed:** the SDK (`anthropic` → `google-genai`), the client class
  (`ClaudeChatbot` → `GeminiChatbot`, with `ClaudeChatbot` kept as a
  backwards-compatible alias), the env var names (`ANTHROPIC_API_KEY` →
  `GEMINI_API_KEY`, `CLAUDE_*` → `GEMINI_*`), how the system prompt is sent
  (Claude's top-level `system` string → Gemini's
  `GenerateContentConfig(system_instruction=...)`), how assistant turns are
  labeled on the wire (Claude's `"assistant"` → Gemini's `"model"`, mapped
  in `client.py` only — memory itself still uses `"assistant"`), and how
  errors are classified for retry (Claude's typed exceptions → Gemini's
  `ClientError`/`ServerError` with HTTP status codes).

## Extending this project

- **Persistent memory across sessions:** swap `ConversationMemory`'s
  in-memory list for a Redis- or SQLite-backed store — the `client.py`
  and `cli.py` layers don't need to change since they only depend on
  `get_history()` / `add_user_message()` / `add_assistant_message()`.
- **Streaming responses:** replace `models.generate_content(...)` with
  `models.generate_content_stream(...)` in `client.py` and yield chunks
  instead of returning a single string.
- **Web/API interface:** write a new thin layer (e.g. FastAPI routes) that
  calls the same `GeminiChatbot.send_message()`, one `ConversationMemory`
  instance per session/user.
