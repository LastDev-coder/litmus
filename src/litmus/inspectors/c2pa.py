"""C2PA manifest inspection.

Two distinct capabilities, kept separate on purpose:

* **Presence** — detected structurally with the standard library. A C2PA
  manifest store lives in a PNG ``caBX`` chunk, a JPEG APP11/JUMBF segment, or
  SVG metadata. Presence is cheap and reliable.
* **Verification** — checking the signature chain, issuer, assertions and
  timestamps. This requires the optional ``c2pa`` extra. Without it the finding
  reports ``verification: not_performed`` rather than implying the manifest is
  valid.

Presence of a manifest is *not* proof of provenance; only a verified signature
is, and even then it attests to the signer's claim, not to authorship.
"""

from __future__ import annotations

from typing import Any

from ..artifact import Artifact
from ..model import EvidenceClass, EvidenceLabel, Finding, Severity
from .base import InspectorOutcome
from .file_metadata import (
    JPEG_SIGNATURE,
    PNG_SIGNATURE,
    iter_jpeg_segments,
    iter_png_chunks,
)

# JUMBF box type used by C2PA, and the C2PA namespace UUID prefix.
JUMBF_MAGIC = b"jumb"
C2PA_MARKERS = (b"c2pa", b"jumbf", b"urn:uuid:")


def _load_c2pa_module() -> Any | None:
    try:
        import c2pa  # type: ignore[import-not-found]
    except ImportError:
        return None
    return c2pa


class C2paInspector:
    name = "c2pa"

    def applies_to(self, artifact: Artifact) -> bool:
        data = artifact.data
        return (
            data.startswith(PNG_SIGNATURE)
            or data.startswith(JPEG_SIGNATURE)
            or artifact.ref.media_type == "image/svg+xml"
        )

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        present, container, evidence = self._detect_presence(artifact)
        if not present:
            return InspectorOutcome(findings=[])

        details: dict[str, object] = {
            "container": container,
            "located_in": evidence,
            "verification": "not_performed",
            "verification_reason": (
                "the optional 'c2pa' extra is not installed; manifest presence was "
                "detected structurally but the signature was not verified"
            ),
        }
        severity = Severity.INFO
        label = EvidenceLabel.CONFIRMED

        module = _load_c2pa_module()
        if module is not None:
            details.update(self._verify(module, artifact))

        return InspectorOutcome(
            findings=[
                Finding(
                    detector=self.name,
                    category="c2pa_manifest",
                    # Presence alone is only *claimed* signed provenance. The
                    # class stays SIGNED_PROVENANCE because that is what the
                    # structure is; the verification field carries the caveat.
                    evidence_class=EvidenceClass.SIGNED_PROVENANCE,
                    severity=severity,
                    summary=f"C2PA manifest store present in {container} container",
                    label=label,
                    details=details,
                    removable_by=[],
                )
            ]
        )

    def _detect_presence(self, artifact: Artifact) -> tuple[bool, str, str]:
        data = artifact.data
        if data.startswith(PNG_SIGNATURE):
            for ctype, _payload in iter_png_chunks(data):
                if ctype == "caBX":
                    return True, "png", "caBX chunk"
            return False, "png", ""
        if data.startswith(JPEG_SIGNATURE):
            for marker, payload in iter_jpeg_segments(data):
                if marker == 0xEB and JUMBF_MAGIC in payload[:64]:
                    return True, "jpeg", "APP11 JUMBF segment"
            return False, "jpeg", ""
        if artifact.text is not None and artifact.ref.media_type == "image/svg+xml":
            lowered = artifact.text.lower()
            if "c2pa" in lowered:
                return True, "svg", "c2pa reference in SVG markup"
            return False, "svg", ""
        return False, "unknown", ""

    def _verify(self, module: Any, artifact: Artifact) -> dict[str, object]:
        """Verify with the optional c2pa library.

        Any failure is reported as a verification outcome, never raised: a
        broken or untrusted manifest is a result, not a crash.
        """
        path = artifact.ref.path
        if path is None:
            return {
                "verification": "not_performed",
                "verification_reason": "verification requires a file path",
            }
        try:
            reader = module.Reader.from_file(path)
            manifest_json = reader.json()
        except Exception as exc:  # noqa: BLE001 - any library error is a result
            return {
                "verification": "failed",
                "verification_reason": f"{type(exc).__name__}: {exc}",
            }
        return {
            "verification": "performed",
            "verification_reason": None,
            "manifest": manifest_json,
        }
