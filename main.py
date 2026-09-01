#!/usr/bin/env python3
"""
Entry point for the Gemini Chatbot with Memory.

Run with:
    python main.py

Configuration is read from environment variables / a local .env file.
See .env.example for the full list of supported settings.
"""

from __future__ import annotations

import logging
import sys

from pathlib import Path

from chatbot import (
    GeminiChatbot,
    Config,
    run_cli,
)
from chatbot.memory import PersistentMemory
from chatbot.exceptions import ConfigurationError


def configure_logging() -> None:
    """
    Configure root logging once, at the application entry point.

    Library modules should only ever call `logging.getLogger(__name__)` and
    never configure handlers themselves — that responsibility belongs here.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # Quiet noisy third-party HTTP logging unless something goes wrong.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> int:
    """Wire up configuration, memory, and the API client, then run the CLI."""
    configure_logging()
    logger = logging.getLogger(__name__)

    try:
        config = Config.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    # Use a persistent memory file located relative to this script so
    # memory survives restarts regardless of the current working dir.
    base_dir = Path(__file__).parent
    memory_file = base_dir / "data" / "conversation_memory.json"
    memory = PersistentMemory(
        max_messages=config.max_history_messages,
        memory_file=memory_file,
    )
    bot = GeminiChatbot(config=config, memory=memory)

    logger.info(
        "Starting chatbot session (model=%s, max_history_messages=%d)",
        config.model,
        config.max_history_messages,
    )

    try:
        run_cli(bot)
    except Exception:  # noqa: BLE001 - top-level safety net
        logger.exception("Fatal error in chatbot session")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
