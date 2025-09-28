"""Telegram post automation пакет."""

from .config import Settings
from .main import run_poll_once, run_poll_loop

__all__ = ["Settings", "run_poll_once", "run_poll_loop"]
