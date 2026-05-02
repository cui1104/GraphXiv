"""
deepxiv-sdk - A Python package for arXiv paper access with CLI and MCP server support.
"""

__version__ = "0.2.4"

from .reader import (
    Reader,
    APIError,
    BadRequestError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
    ServerError,
)

__all__ = [
    "Reader",
    "APIError",
    "BadRequestError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    "ServerError",
    "Agent",
]


def __getattr__(name):
    """Lazily expose optional agent components.

    Reader-only imports should not initialize LangGraph, OpenAI, or tiktoken.
    Those dependencies are only needed when callers explicitly request Agent.
    """
    if name == "Agent":
        try:
            from .agent.agent import Agent
        except ImportError as exc:
            raise ImportError(
                "Agent functionality requires optional agent dependencies."
            ) from exc
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
