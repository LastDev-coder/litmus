"""AI provenance inspector and quality-preserving transformation system.

Inspects files for locally detectable provenance signals (hidden characters,
embedded metadata, content credentials) and strips them behind proofs that the
visible content is unchanged. It never claims to detect statistical text
watermarks; no public detector exists for them.
"""

from __future__ import annotations

from .artifact import Artifact, load_bytes, load_path
from .model import TOOL_VERSION, Report
from .pipeline import TransformOptions, analyze, inspect, transform

__version__ = TOOL_VERSION

__all__ = [
    "Artifact",
    "Report",
    "TransformOptions",
    "__version__",
    "analyze",
    "inspect",
    "load_bytes",
    "load_path",
    "transform",
]
