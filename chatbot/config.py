"""
Configuration management.

All runtime configuration is sourced from environment variables (optionally
loaded from a local .env file via python-dotenv). Centralizing this in a
single, validated, immutable dataclass avoids scattering `os.environ` calls
throughout the codebase and fails fast with a clear error if something is
missing or malformed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .exceptions import ConfigurationError

# Sensible, explicit defaults. Every one of these can be overridden via
# environment variables, so no redeploy is needed to tune behavior.
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_HISTORY_MESSAGES = 50
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, friendly AI assistant. Maintain awareness of the "
    "full conversation and naturally reference information the user has "
    "already shared when it is relevant."
)


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""

    api_key: str
    model: str
    max_tokens: int
    temperature: float
    max_history_messages: int
    system_prompt: str
    request_timeout: float
    max_retries: int

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Config":
        """
        Build a Config instance from environment variables.

        Args:
            dotenv_path: Optional explicit path to a .env file. If omitted,
                python-dotenv searches the current and parent directories.

        Raises:
            ConfigurationError: If required variables are missing or any
                variable fails validation (e.g. non-numeric max tokens).
        """
        load_dotenv(dotenv_path=dotenv_path)

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is not set. Create a .env file (see "
                ".env.example) or export the variable in your shell before "
                "starting the chatbot."
            )

        model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip()

        try:
            max_tokens = int(os.getenv("GEMINI_MAX_TOKENS", DEFAULT_MAX_TOKENS))
            if max_tokens <= 0:
                raise ValueError
        except ValueError as exc:
            raise ConfigurationError(
                "GEMINI_MAX_TOKENS must be a positive integer."
            ) from exc

        try:
            temperature = float(os.getenv("GEMINI_TEMPERATURE", DEFAULT_TEMPERATURE))
            if not 0.0 <= temperature <= 2.0:
                raise ValueError
        except ValueError as exc:
            raise ConfigurationError(
                "GEMINI_TEMPERATURE must be a float between 0.0 and 2.0."
            ) from exc

        try:
            max_history_messages = int(
                os.getenv("MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES)
            )
            if max_history_messages <= 0:
                raise ValueError
        except ValueError as exc:
            raise ConfigurationError(
                "MAX_HISTORY_MESSAGES must be a positive integer."
            ) from exc

        try:
            request_timeout = float(os.getenv("GEMINI_REQUEST_TIMEOUT", "60.0"))
        except ValueError as exc:
            raise ConfigurationError(
                "GEMINI_REQUEST_TIMEOUT must be a number (seconds)."
            ) from exc

        try:
            max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
            if max_retries < 0:
                raise ValueError
        except ValueError as exc:
            raise ConfigurationError(
                "GEMINI_MAX_RETRIES must be a non-negative integer."
            ) from exc

        system_prompt = os.getenv("GEMINI_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

        return cls(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_history_messages=max_history_messages,
            system_prompt=system_prompt,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
