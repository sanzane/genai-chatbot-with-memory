"""
Gemini API client wrapper.

Wraps the official `google-genai` SDK with:
  - Input validation
  - Automatic inclusion of full conversation history on every call
  - Exponential-backoff retries for transient failures (rate limits,
    connection errors, 5xx responses)
  - Translation of SDK-specific exceptions into the package's own
    `APICommunicationError`, so callers only need to handle one error type

Memory is stored provider-agnostically by `ConversationMemory` as
`{"role": "user" | "assistant", "content": str}` dicts (unchanged from the
original Claude-based implementation). This module is the only place that
translates that shape into what the Gemini API expects — namely
`types.Content` objects using role `"user"` / `"model"`, with the system
prompt sent separately via `system_instruction` rather than as a message.
"""

from __future__ import annotations

import logging
import random
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from .config import Config
from .exceptions import APICommunicationError, InvalidInputError
from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# HTTP status codes worth retrying: request timeout, rate limiting, and
# server-side (5xx) failures. Anything else (e.g. auth errors, bad request)
# fails fast since a retry would not help.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

MAX_INPUT_LENGTH = 32_000  # characters; guards against runaway payloads

# Maps our internal, provider-agnostic role names to Gemini's role names.
_ROLE_TO_GEMINI = {"user": "user", "assistant": "model"}


class GeminiChatbot:
    """
    High-level, memory-aware wrapper around the Gemini generate_content API.

    Usage:
        config = Config.from_env()
        memory = ConversationMemory(max_messages=config.max_history_messages)
        bot = GeminiChatbot(config, memory)
        reply = bot.send_message("Hello!")
    """

    def __init__(self, config: Config, memory: ConversationMemory) -> None:
        self.config = config
        self.memory = memory
        self._client = genai.Client(
            api_key=config.api_key,
            http_options=genai_types.HttpOptions(timeout=config.request_timeout * 1000),
        )

    def send_message(self, user_input: str) -> str:
        """
        Send a user message to Gemini, using the full conversation history
        as context, and return the assistant's reply text.

        The user message and the assistant's reply are both persisted to
        memory so subsequent calls automatically include them as context.

        Args:
            user_input: The raw text typed by the user.

        Returns:
            The assistant's reply as plain text.

        Raises:
            InvalidInputError: If `user_input` is empty, whitespace-only,
                or exceeds the maximum allowed length.
            APICommunicationError: If the request to Gemini fails after all
                retries are exhausted, or fails for a non-retryable reason.
        """
        self._validate_input(user_input)

        # Record the user's turn BEFORE calling the API so it is included
        # in the very request that answers it.
        self.memory.add_user_message(user_input.strip())

        try:
            reply_text = self._call_api_with_retry()
        except Exception:
            # Roll back the just-added user message so a failed call does
            # not leave an unanswered, dangling turn in memory that would
            # desync the conversation on the next attempt.
            self._remove_last_message_if_matches("user", user_input.strip())
            raise

        self.memory.add_assistant_message(reply_text)
        return reply_text

    def _validate_input(self, user_input: str) -> None:
        if user_input is None:
            raise InvalidInputError("Input cannot be None.")
        if not isinstance(user_input, str):
            raise InvalidInputError("Input must be a string.")
        if not user_input.strip():
            raise InvalidInputError("Input cannot be empty or whitespace-only.")
        if len(user_input) > MAX_INPUT_LENGTH:
            raise InvalidInputError(
                f"Input exceeds maximum allowed length of "
                f"{MAX_INPUT_LENGTH} characters."
            )

    def _call_api_with_retry(self) -> str:
        """
        Call the Gemini generate_content API, retrying transient failures
        with exponential backoff and jitter.
        """
        last_exception: Exception | None = None
        contents = self._history_to_gemini_contents()
        gen_config = genai_types.GenerateContentConfig(
            system_instruction=self.config.system_prompt,
            max_output_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=gen_config,
                )
                return self._extract_text(response)

            except genai_errors.ClientError as exc:
                code = getattr(exc, "code", None)

                if code in (401, 403):
                    # Never retryable: bad/expired/unauthorized API key.
                    raise APICommunicationError(
                        "Authentication with the Gemini API failed. Check "
                        "that GEMINI_API_KEY is valid and has access to "
                        "this model."
                    ) from exc

                if code in _RETRYABLE_STATUS_CODES:
                    last_exception = exc
                    if attempt < self.config.max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            "Transient error calling Gemini API (attempt "
                            "%d/%d): %s. Retrying in %.1fs...",
                            attempt + 1,
                            self.config.max_retries + 1,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    logger.error(
                        "Gemini API call failed after %d attempts.",
                        self.config.max_retries + 1,
                    )
                    continue

                # Any other 4xx (e.g. 400 bad request) is not retryable.
                raise APICommunicationError(
                    f"The request was rejected as invalid by the Gemini "
                    f"API: {exc}"
                ) from exc

            except genai_errors.ServerError as exc:
                code = getattr(exc, "code", None)
                last_exception = exc
                if code in _RETRYABLE_STATUS_CODES or code is None:
                    if attempt < self.config.max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            "Transient error calling Gemini API (attempt "
                            "%d/%d): %s. Retrying in %.1fs...",
                            attempt + 1,
                            self.config.max_retries + 1,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    logger.error(
                        "Gemini API call failed after %d attempts.",
                        self.config.max_retries + 1,
                    )
                    continue
                raise APICommunicationError(
                    f"An unexpected server error occurred communicating "
                    f"with the Gemini API: {exc}"
                ) from exc

            except genai_errors.APIError as exc:
                # Catch-all for any other SDK-raised API error.
                raise APICommunicationError(
                    f"An unexpected error occurred communicating with the "
                    f"Gemini API: {exc}"
                ) from exc

        raise APICommunicationError(
            f"Failed to get a response from Gemini after "
            f"{self.config.max_retries + 1} attempts."
        ) from last_exception

    def _history_to_gemini_contents(self) -> list["genai_types.Content"]:
        """
        Translate `ConversationMemory`'s provider-agnostic history
        (`{"role": "user" | "assistant", "content": str}`) into the list of
        `types.Content` objects the Gemini API expects, mapping our
        `"assistant"` role to Gemini's `"model"` role. The system prompt is
        deliberately NOT included here — it's sent via `system_instruction`
        in the request config instead, mirroring how it was previously sent
        via Claude's separate top-level `system` parameter.
        """
        return [
            genai_types.Content(
                role=_ROLE_TO_GEMINI[msg["role"]],
                parts=[genai_types.Part.from_text(text=msg["content"])],
            )
            for msg in self.memory.get_history()
        ]

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 20.0) -> float:
        """Exponential backoff with jitter: base * 2^attempt, capped."""
        raw_delay = min(cap, base * (2 ** attempt))
        return raw_delay * (0.5 + random.random() / 2)  # jitter in [0.5x, 1.0x]

    @staticmethod
    def _extract_text(response: "genai_types.GenerateContentResponse") -> str:
        """
        Extract plain text from a Gemini generate_content response.

        `response.text` is the SDK's own convenience accessor, which
        concatenates all text parts of the first candidate — the Gemini
        equivalent of concatenating Claude's text content blocks.
        """
        text = response.text
        if not text or not text.strip():
            raise APICommunicationError(
                "Gemini API returned a response with no text content."
            )
        return text.strip()

    def _remove_last_message_if_matches(self, role: str, content: str) -> None:
        """Best-effort rollback helper used after a failed API call."""
        history = self.memory.get_history()
        if history and history[-1]["role"] == role and history[-1]["content"] == content:
            # ConversationMemory has no public pop; rebuild via clear+replay
            # to keep the memory module's internals private and simple.
            remaining = history[:-1]
            self.memory.clear()
            for msg in remaining:
                if msg["role"] == "user":
                    self.memory.add_user_message(msg["content"])
                else:
                    self.memory.add_assistant_message(msg["content"])


# Backwards-compatible alias: earlier versions of this project (when it
# targeted the Claude API) exposed this class as `ClaudeChatbot`.
ClaudeChatbot = GeminiChatbot
