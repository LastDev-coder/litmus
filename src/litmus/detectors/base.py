"""Detector abstraction for provider provenance detectors.

**There are deliberately no implementations in this package.**

No public detector exists for Anthropic's text watermark, and SynthID detection
requires partner access. Shipping a stub that returned a plausible-looking
result would be fabrication, so the interface is defined and left empty until a
real detector is available.

When one ships, an implementation is added here and the corresponding row in
``providers/registry.py`` flips to ``Detectability.PUBLIC_DETECTOR``. Nothing
else in the pipeline changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from ..artifact import Artifact
from ..model import Confidence, EvidenceClass


class DetectionResult(BaseModel):
    detector: str
    provider: str
    signal: str
    evidence_class: EvidenceClass
    input_sha256: str
    detected: bool | None
    confidence: Confidence
    #: Provider-reported score, if and only if the provider returns one.
    provider_score: float | None = None
    minimum_length_met: bool | None = None
    detail: str = ""
    #: True when running this detector transmitted the artifact off the machine.
    network_used: bool = False


@runtime_checkable
class Detector(Protocol):
    name: str
    provider: str
    #: Detectors that transmit content must declare it so the CLI can require
    #: an explicit opt-in (brief §14).
    requires_network: bool

    def applies_to(self, artifact: Artifact) -> bool: ...

    def detect(self, artifact: Artifact, *, timeout_s: float) -> DetectionResult: ...


def available_detectors() -> list[Detector]:
    """No detectors are available. See the module docstring."""
    return []
