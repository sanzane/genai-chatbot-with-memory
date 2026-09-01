"""
Custom exception hierarchy for the chatbot package.

Using a dedicated hierarchy (instead of letting raw SDK/library exceptions
leak upward) keeps the calling code decoupled from the Google Gen AI SDK's
internal exception types and gives callers a single, predictable set of
errors to catch.
"""


class ChatbotError(Exception):
    """Base class for all chatbot-related errors."""


class ConfigurationError(ChatbotError):
    """Raised when required configuration (e.g. API key) is missing or invalid."""


class InvalidInputError(ChatbotError):
    """Raised when user-supplied input fails validation."""


class APICommunicationError(ChatbotError):
    """Raised when communication with the Gemini API fails unrecoverably."""
