"""Convenience factory: build a fully-wired NLOpsStrandsAgent.

In Strands-mode (default after v3) we don't need to register agents
individually — Strands picks tools automatically from the registry.
"""
from __future__ import annotations

from .engine import NLOpsStrandsAgent, build_default

__all__ = ["NLOpsStrandsAgent", "build_default"]
