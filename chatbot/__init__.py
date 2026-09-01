"""
chatbot
=======

A production-ready, memory-aware conversational chatbot built on top of the
official Google Gemini SDK (`google-genai`).

Public entry points:
    - Config                : environment-driven configuration loader
    - ConversationMemory    : in-session message history manager
    - PersistentMemory      : persistent JSON-backed message history manager
    - GeminiChatbot         : Gemini API wrapper with retry/backoff
    - run_cli               : interactive command-line loop
"""

from .config import Config
from .memory import ConversationMemory, PersistentMemory
from .client import GeminiChatbot, ClaudeChatbot
from .exceptions import (
    ChatbotError,
    ConfigurationError,
    APICommunicationError,
    InvalidInputError,
)
from .cli import run_cli

__all__ = [
    "Config",
    "ConversationMemory",
    "PersistentMemory",
    "GeminiChatbot",
    "ClaudeChatbot",  # deprecated alias, kept for backwards compatibility
    "ChatbotError",
    "ConfigurationError",
    "APICommunicationError",
    "InvalidInputError",
    "run_cli",
]

__version__ = "2.1.0"
