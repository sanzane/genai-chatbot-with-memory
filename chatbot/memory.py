"""
Conversation memory management.

This module is deliberately decoupled from the Gemini SDK: it just stores
plain, JSON-serializable message dicts in the shape the Messages API expects
(`{"role": "user" | "assistant", "content": str}`). That keeps it easy to
unit test, swap out for a persistent backend (Redis, a database, a file)
later, or reuse across different LLM providers.

Provides both in-memory (ConversationMemory) and persistent (PersistentMemory)
implementations.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Dict, List, Literal

logger = logging.getLogger(__name__)

Role = Literal["user", "assistant"]


class ConversationMemory:
    """
    Maintains an ordered, in-memory record of a single conversation session.

    Responsible for:
      - Storing user and assistant turns in the order they occurred.
      - Exposing the full history in the exact format the Claude Messages
        API expects, so it can be passed straight through on every request.
      - Bounding memory growth via a sliding window, so very long sessions
        don't grow the request payload (and cost/latency) without limit.
    """

    def __init__(self, max_messages: int = 50) -> None:
        """
        Args:
            max_messages: Maximum number of messages (user + assistant turns
                combined) to retain. Oldest messages are dropped first once
                the limit is exceeded. Must be a positive, even-ish number
                to keep user/assistant turns paired; trimming always removes
                from the front in pairs where possible to avoid leaving a
                dangling assistant reply with no preceding user turn.
        """
        if max_messages <= 0:
            raise ValueError("max_messages must be a positive integer")
        self.max_messages = max_messages
        self._messages: List[Dict[str, str]] = []

    def add_user_message(self, content: str) -> None:
        """Append a user turn to the history."""
        self._append("user", content)

    def add_assistant_message(self, content: str) -> None:
        """Append an assistant turn to the history."""
        self._append("assistant", content)

    def get_history(self) -> List[Dict[str, str]]:
        """
        Return the full conversation history, oldest first, ready to be
        passed directly as the `messages` argument to the Claude API.

        A deep copy is returned so callers cannot mutate internal state.
        """
        return copy.deepcopy(self._messages)

    def clear(self) -> None:
        """Erase all stored history (e.g. on a user-issued /clear command)."""
        self._messages.clear()

    def _append(self, role: Role, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        self._trim()

    def _trim(self) -> None:
        """
        Keep the stored history within `max_messages`, trimming from the
        oldest end in pairs so the conversation never starts with a lone
        assistant message (which the API would treat as malformed context).
        """
        while len(self._messages) > self.max_messages:
            # Drop the oldest message. If that leaves the list starting with
            # an assistant message, drop one more so history always begins
            # with a user turn.
            self._messages.pop(0)
            if self._messages and self._messages[0]["role"] == "assistant":
                self._messages.pop(0)

    def __len__(self) -> int:
        return len(self._messages)

    def __bool__(self) -> bool:
        return bool(self._messages)


class PersistentMemory(ConversationMemory):
    """
    Extends ConversationMemory to automatically persist conversation history
    to a JSON file.

    Responsible for:
      - All ConversationMemory features (in-memory message management)
      - Automatically saving messages to disk after every addition
      - Loading previously saved messages from disk on initialization
      - Providing metadata about the stored memory
    """

    def __init__(
        self,
        max_messages: int = 50,
        memory_file: str | Path = "data/conversation_memory.json",
    ) -> None:
        """
        Args:
            max_messages: Maximum number of messages to retain in memory.
            memory_file: Path to the JSON file for persistent storage.
                        Directory is created if it doesn't exist.
        """
        super().__init__(max_messages=max_messages)
        self.memory_file = Path(memory_file)
        self._ensure_directory_exists()
        self._load_from_disk()

    def add_user_message(self, content: str) -> None:
        """Append a user turn and persist to disk."""
        super().add_user_message(content)
        self._save_to_disk()

    def add_assistant_message(self, content: str) -> None:
        """Append an assistant turn and persist to disk."""
        super().add_assistant_message(content)
        self._save_to_disk()

    def clear(self) -> None:
        """Erase all stored history and delete the persistent file."""
        super().clear()
        self._delete_disk_file()

    def get_memory_stats(self) -> Dict[str, str]:
        """
        Get information about stored memory.

        Returns:
            A dict with file path, message count, and file size.
        """
        file_exists = self.memory_file.exists()
        file_size = self.memory_file.stat().st_size if file_exists else 0
        return {
            "file": str(self.memory_file),
            "messages": str(len(self._messages)),
            "file_size_bytes": str(file_size),
        }

    def _ensure_directory_exists(self) -> None:
        """Create the parent directory if it doesn't exist."""
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def _save_to_disk(self) -> None:
        """Persist the current message history to the JSON file."""
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self._messages, f, indent=2, ensure_ascii=False)
            logger.debug("Memory saved to %s", self.memory_file)
        except Exception as exc:
            logger.error("Failed to save memory to %s: %s", self.memory_file, exc)

    def _load_from_disk(self) -> None:
        """Load message history from the JSON file if it exists."""
        if not self.memory_file.exists():
            logger.debug(
                "Memory file %s does not exist. Starting with empty history.",
                self.memory_file,
            )
            return

        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                messages = json.load(f)
            if isinstance(messages, list):
                self._messages = messages
                # Apply max_messages limit to loaded messages
                self._trim()
                logger.info(
                    "Loaded %d messages from %s",
                    len(self._messages),
                    self.memory_file,
                )
            else:
                logger.warning(
                    "Memory file %s contains invalid format. Starting fresh.",
                    self.memory_file,
                )
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse memory file %s: %s. Starting fresh.",
                self.memory_file,
                exc,
            )
        except Exception as exc:
            logger.error(
                "Failed to load memory from %s: %s. Starting fresh.",
                self.memory_file,
                exc,
            )

    def _delete_disk_file(self) -> None:
        """Delete the persistent memory file."""
        try:
            if self.memory_file.exists():
                self.memory_file.unlink()
                logger.info("Deleted memory file %s", self.memory_file)
        except Exception as exc:
            logger.error("Failed to delete memory file %s: %s", self.memory_file, exc)
