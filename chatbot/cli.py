"""
Interactive command-line interface for the chatbot.

Kept separate from GeminiChatbot so the core chatbot logic remains reusable
in non-CLI contexts (a web backend, a Slack bot, tests, etc.) without dragging
along any terminal I/O concerns.
"""

from __future__ import annotations

import logging

from .client import GeminiChatbot
from .exceptions import APICommunicationError, InvalidInputError

logger = logging.getLogger(__name__)

EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit"}
CLEAR_COMMANDS = {"/clear"}
HISTORY_COMMANDS = {"/history"}
MEMORY_COMMANDS = {"/memory"}
HELP_COMMANDS = {"/help"}

BANNER = """
============================================================
 Gemini Chatbot with Persistent Memory  —  type /help for commands
============================================================
""".strip()

HELP_TEXT = """
Available commands:
  /help      Show this help message
  /history   Show the current conversation history
  /memory    Show information about stored persistent memory
  /clear     Clear conversation memory and persistent storage (starts fresh)
  /exit      Exit the chatbot (also: /quit, exit, quit)
""".strip()


def run_cli(bot: GeminiChatbot) -> None:
    """
    Run an interactive read-eval-print loop until the user exits.

    Args:
        bot: A fully configured GeminiChatbot instance.
    """
    print(BANNER)
    print("Type your message and press Enter. Conversation context is kept "
          "across sessions thanks to persistent memory.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            # Silently re-prompt rather than sending empty input to the API.
            continue

        lowered = user_input.lower()

        if lowered in EXIT_COMMANDS:
            print("Goodbye!")
            break

        if lowered in CLEAR_COMMANDS:
            bot.memory.clear()
            print("(conversation memory cleared)\n")
            continue

        if lowered in MEMORY_COMMANDS:
            _print_memory_info(bot)
            continue

        if lowered in HELP_COMMANDS:
            print(HELP_TEXT + "\n")
            continue

        if lowered in HISTORY_COMMANDS:
            _print_history(bot)
            continue

        try:
            reply = bot.send_message(user_input)
            print(f"Gemini: {reply}\n")
        except InvalidInputError as exc:
            print(f"(input error: {exc})\n")
        except APICommunicationError as exc:
            logger.error("API communication error: %s", exc)
            print(f"(sorry, something went wrong talking to Gemini: {exc})\n")
        except Exception as exc:  # noqa: BLE001 - final safety net for a CLI loop
            logger.exception("Unexpected error in chat loop")
            print(f"(an unexpected error occurred: {exc})\n")


def _print_history(bot: GeminiChatbot) -> None:
    history = bot.memory.get_history()
    if not history:
        print("(no messages yet)\n")
        return
    print("--- conversation history ---")
    for msg in history:
        speaker = "You" if msg["role"] == "user" else "Gemini"
        print(f"{speaker}: {msg['content']}")
    print()


def _print_memory_info(bot: GeminiChatbot) -> None:
    """Display information about stored persistent memory."""
    if hasattr(bot.memory, "get_memory_stats"):
        stats = bot.memory.get_memory_stats()
        print("--- persistent memory info ---")
        print(f"Storage file:   {stats['file']}")
        print(f"Messages:       {stats['messages']}")
        print(f"File size:      {stats['file_size_bytes']} bytes")
        print()
    else:
        print("(this session is using in-memory storage only)\n")
    print("-----------------------------\n")
