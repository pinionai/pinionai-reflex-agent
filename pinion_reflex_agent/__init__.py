"""Unified entrypoint initialization for the PinionAI Reflex Chat application."""

from .state import AppState
from .pages import index

# Explicitly expose these core layout pieces so the root app file 
# can map page routes cleanly without hidden package naming collisions.
__all__ = [
    "AppState",
    "index",
]
