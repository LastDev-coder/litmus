"""Unicode and invisible-character inspection.

Scope note (brief §5, and FINDINGS.md §3): invisible characters are *not* a
provider watermark. They are reported as invisible-character anomalies with
evidence class ``EMBEDDED_METADATA``, because that is the strongest honest
claim: someone or something put codepoints in the file that carry no visible
content. They are frequently mundane (word processors, PDF copy/paste, web
editors, CJK typography, RTL text).

All special codepoints below are written as escapes on purpose, so that this
source file itself contains no invisible characters.
"""

from __future__ import annotations

import re
import unicodedata

from ..artifact import Artifact
from ..model import ArtifactKind, EvidenceClass, EvidenceLabel, Finding, Location, Severity
from .base import InspectorOutcome, line_col

MAX_LOCATIONS = 50

BOM = "\ufeff"

# Codepoints with no visible rendering that can carry an out-of-band payload.
ZERO_WIDTH: dict[str, str] = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\u2060": "WORD JOINER",
    "\u180e": "MONGOLIAN VOWEL SEPARATOR",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE (BOM)",
}

# Bidirectional formatting controls. Legitimate in RTL text; also the basis of
# the "Trojan Source" source-code attack, so they are a warning in code.
BIDI_CONTROLS: dict[str, str] = {
    "\u202a": "LEFT-TO-RIGHT EMBEDDING",
    "\u202b": "RIGHT-TO-LEFT EMBEDDING",
    "\u202c": "POP DIRECTIONAL FORMATTING",
    "\u202d": "LEFT-TO-RIGHT OVERRIDE",
    "\u202e": "RIGHT-TO-LEFT OVERRIDE",
    "\u2066": "LEFT-TO-RIGHT ISOLATE",
    "\u2067": "RIGHT-TO-LEFT ISOLATE",
    "\u2068": "FIRST STRONG ISOLATE",
    "\u2069": "POP DIRECTIONAL ISOLATE",
    "\u061c": "ARABIC LETTER MARK",
    "\u200e": "LEFT-TO-RIGHT MARK",
    "\u200f": "RIGHT-TO-LEFT MARK",
}

# Space characters that are neither U+0020 nor a tab.
EXOTIC_SPACES: dict[str, str] = {
    "\u00a0": "NO-BREAK SPACE",
    "\u1680": "OGHAM SPACE MARK",
    "\u2000": "EN QUAD",
    "\u2001": "EM QUAD",
    "\u2002": "EN SPACE",
    "\u2003": "EM SPACE",
    "\u2004": "THREE-PER-EM SPACE",
    "\u2005": "FOUR-PER-EM SPACE",
    "\u2006": "SIX-PER-EM SPACE",
    "\u2007": "FIGURE SPACE",
    "\u2008": "PUNCTUATION SPACE",
    "\u2009": "THIN SPACE",
    "\u200a": "HAIR SPACE",
    "\u202f": "NARROW NO-BREAK SPACE",
    "\u205f": "MEDIUM MATHEMATICAL SPACE",
    "\u3000": "IDEOGRAPHIC SPACE",
}

OTHER_INVISIBLE: dict[str, str] = {
    "\u00ad": "SOFT HYPHEN",
    "\u034f": "COMBINING GRAPHEME JOINER",
    "\u2800": "BRAILLE PATTERN BLANK",
}

# Scripts that legitimately interleave inside a single whitespace-delimited run
# of Japanese or Chinese text; collapsing them avoids a flood of false hits.
_CJK_SCRIPTS = frozenset({"HIRAGANA", "KATAKANA", "CJK", "KANGXI", "IDEOGRAPHIC"})


def is_variation_selector(ch: str) -> bool:
    cp = ord(ch)
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def is_tag_char(ch: str) -> bool:
    # U+E0000..U+E007F: deprecated, invisible, and the most common vehicle for
    # hiding an arbitrary ASCII payload inside otherwise-clean text.
    return 0xE0000 <= ord(ch) <= 0xE007F


def decode_tag_payload(chars: list[str]) -> str:
    """Tag characters mirror ASCII at an offset of U+E0000."""
    return "".join(chr(ord(c) - 0xE0000) for c in chars if 0xE0020 <= ord(c) <= 0xE007E)


def _script_of(ch: str) -> str | None:
    """Coarse script bucket, sufficient for homoglyph detection."""
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    script = name.split(" ")[0]
    return "CJK" if script in _CJK_SCRIPTS else script


class UnicodeInspector:
    name = "unicode"

    def applies_to(self, artifact: Artifact) -> bool:
        return artifact.is_textual

    def inspect(self, artifact: Artifact) -> InspectorOutcome:
        text = artifact.text
        if text is None:
            return InspectorOutcome.skipped("artifact is not decodable text")

        buckets: dict[str, list[tuple[int, str, str]]] = {
            "zero_width": [],
            "bidi_control": [],
            "exotic_space": [],
            "variation_selector": [],
            "unicode_tag_char": [],
            "other_invisible": [],
            "control_char": [],
        }

        for offset, ch in enumerate(text):
            if ch in ZERO_WIDTH:
                # A leading BOM is reported by _structural_findings instead.
                if not (offset == 0 and ch == BOM):
                    buckets["zero_width"].append((offset, ch, ZERO_WIDTH[ch]))
            elif ch in BIDI_CONTROLS:
                buckets["bidi_control"].append((offset, ch, BIDI_CONTROLS[ch]))
            elif ch in EXOTIC_SPACES:
                buckets["exotic_space"].append((offset, ch, EXOTIC_SPACES[ch]))
            elif ch in OTHER_INVISIBLE:
                buckets["other_invisible"].append((offset, ch, OTHER_INVISIBLE[ch]))
            elif is_variation_selector(ch):
                buckets["variation_selector"].append((offset, ch, "VARIATION SELECTOR"))
            elif is_tag_char(ch):
                buckets["unicode_tag_char"].append((offset, ch, "UNICODE TAG CHARACTER"))
            elif unicodedata.category(ch) == "Cc" and ch not in "\n\r\t":
                buckets["control_char"].append((offset, ch, "CONTROL CHARACTER"))

        is_code = artifact.ref.kind is ArtifactKind.SOURCE_CODE
        severity_by_bucket = {
            "zero_width": Severity.WARNING,
            "unicode_tag_char": Severity.WARNING,
            "bidi_control": Severity.WARNING if is_code else Severity.NOTICE,
            "variation_selector": Severity.NOTICE,
            "control_char": Severity.WARNING,
            "exotic_space": Severity.NOTICE,
            "other_invisible": Severity.NOTICE,
        }
        removable_by = {
            "zero_width": ["strip_zero_width"],
            "unicode_tag_char": ["strip_tag_characters"],
            "bidi_control": ["strip_bidi_controls"],
            "variation_selector": ["strip_variation_selectors"],
            "control_char": ["strip_control_characters"],
            "exotic_space": ["normalize_spaces"],
            "other_invisible": ["strip_other_invisible"],
        }

        findings: list[Finding] = []
        for bucket, hits in buckets.items():
            if not hits:
                continue
            details: dict[str, object] = {
                "codepoints": sorted({f"U+{ord(c):04X}" for _, c, _ in hits}),
                "names": sorted({name for _, _, name in hits}),
            }
            if bucket == "unicode_tag_char":
                payload = decode_tag_payload([c for _, c, _ in hits])
                if payload:
                    details["decoded_ascii_payload"] = payload
            findings.append(
                Finding(
                    detector=self.name,
                    category=bucket,
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=severity_by_bucket[bucket],
                    summary=f"{len(hits)} {bucket.replace('_', ' ')} character(s) present",
                    label=EvidenceLabel.CONFIRMED,
                    count=len(hits),
                    locations=self._locations(text, hits),
                    details=details,
                    removable_by=removable_by[bucket],
                )
            )

        findings.extend(self._structural_findings(artifact, text))
        return InspectorOutcome(findings=findings)

    def _locations(self, text: str, hits: list[tuple[int, str, str]]) -> list[Location]:
        locations = []
        for offset, ch, name in hits[:MAX_LOCATIONS]:
            line, col = line_col(text, offset)
            locations.append(
                Location(
                    offset=offset,
                    line=line,
                    column=col,
                    length=1,
                    excerpt=f"U+{ord(ch):04X} {name}",
                )
            )
        return locations

    def _structural_findings(self, artifact: Artifact, text: str) -> list[Finding]:
        findings: list[Finding] = []

        if artifact.ref.encoding == "utf-8-sig" or text.startswith(BOM):
            findings.append(
                Finding(
                    detector=self.name,
                    category="byte_order_mark",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.NOTICE,
                    summary="File begins with a UTF-8 byte order mark",
                    locations=[Location(offset=0, line=1, column=1, length=1)],
                    removable_by=["strip_bom"],
                )
            )

        if not unicodedata.is_normalized("NFC", text):
            form = next(
                (f for f in ("NFD", "NFKC", "NFKD") if unicodedata.is_normalized(f, text)),
                "none",
            )
            findings.append(
                Finding(
                    detector=self.name,
                    category="unicode_normalization",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.INFO,
                    summary="Text is not in Unicode NFC normalization form",
                    details={"current_form": form},
                    removable_by=["normalize_nfc"],
                )
            )

        crlf = text.count("\r\n")
        lf = text.count("\n") - crlf
        cr = text.count("\r") - crlf
        if sum(1 for n in (crlf, lf, cr) if n) > 1:
            findings.append(
                Finding(
                    detector=self.name,
                    category="mixed_line_endings",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.NOTICE,
                    summary="File mixes line ending styles",
                    details={"crlf": crlf, "lf": lf, "cr": cr},
                    removable_by=["normalize_line_endings"],
                )
            )

        mixed = _mixed_script_words(text)
        if mixed:
            findings.append(
                Finding(
                    detector=self.name,
                    category="mixed_script_word",
                    evidence_class=EvidenceClass.EMBEDDED_METADATA,
                    severity=Severity.WARNING,
                    summary=(
                        f"{len(mixed)} word(s) mix Latin with another script (possible homoglyphs)"
                    ),
                    count=len(mixed),
                    details={"examples": mixed[:10]},
                    # Homoglyph substitution is not safely auto-reversible: the
                    # intended target character is genuinely ambiguous.
                    removable_by=[],
                )
            )
        return findings


_ALPHA_RUN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _mixed_script_words(text: str) -> list[str]:
    """Maximal runs of letters that mix Latin with another script.

    Two deliberate restrictions keep the false-positive rate usable:

    * Only *letter runs* are examined, not whitespace-delimited words. In source
      code a single "word" routinely spans an identifier and a string literal
      (``_categories("...")``), which is not a homoglyph.
    * Only Latin-plus-other counts. That is the homoglyph-attack shape; a run
      mixing two non-Latin scripts is far more likely to be ordinary
      multilingual text.
    """
    mixed: list[str] = []
    for match in _ALPHA_RUN.finditer(text):
        run = match.group()
        scripts = {s for s in (_script_of(ch) for ch in run) if s}
        if len(scripts) > 1 and "LATIN" in scripts:
            mixed.append(run)
    return mixed
