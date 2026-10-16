"""Kept for compatibility: ``python -m flow demo`` runs the full app."""

from __future__ import annotations

from flow.app import run_app as run_demo

__all__ = ["run_demo"]
