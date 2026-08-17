"""Artifact loading and classification.

Loading is deliberately conservative: files are read as bytes, decoding is
attempted rather than assumed, and a failure to decode downgrades the artifact
to ``BINARY`` instead of raising or silently mangling content.
"""

from __future__ import annotations

import codecs
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .model import ArtifactKind, ArtifactRef

MAX_DEFAULT_BYTES = 32 * 1024 * 1024

# Extension -> language name. Only languages the project targets are named;
# anything else stays ``None`` and is treated as generic text.
_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".java": "java",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
    ".pyi": "python",
}

_MEDIA_TYPE_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".html": "text/html",
    ".xml": "text/xml",
}

# Directories that are never worth walking.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".gradle",
        "build",
        "out",
        "dist",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        "DerivedData",
        ".build",
    }
)


class ArtifactError(Exception):
    """Raised when an artifact cannot be loaded at all."""


@dataclass(frozen=True)
class Artifact:
    """An artifact plus its decoded text, when decoding succeeded."""

    ref: ArtifactRef
    data: bytes
    text: str | None

    @property
    def is_textual(self) -> bool:
        return self.text is not None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> tuple[str | None, str | None]:
    """Return (text, encoding). UTF-8 only; anything else is treated as binary.

    Guessing legacy encodings would make offsets and normalization unreliable,
    which is worse than declining to decode.

    A byte order mark is detected explicitly and **kept** in the decoded text as
    U+FEFF. Decoding with ``utf-8-sig`` would silently swallow it, which both
    hides a real finding and shifts every character offset by one relative to
    the byte stream.
    """
    if b"\x00" in data[:8192]:
        return None, None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, None
    return text, "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"


def classify(path: Path | None, data: bytes, text: str | None) -> tuple[ArtifactKind, str | None]:
    language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower()) if path else None
    if text is None:
        return ArtifactKind.BINARY, None
    if language is not None:
        return ArtifactKind.SOURCE_CODE, language
    return ArtifactKind.TEXT, None


def load_bytes(data: bytes, *, path: Path | None = None) -> Artifact:
    text, encoding = _decode(data)
    kind, language = classify(path, data, text)
    media_type = _MEDIA_TYPE_BY_SUFFIX.get(path.suffix.lower()) if path else None
    ref = ArtifactRef(
        path=str(path) if path else None,
        kind=kind,
        language=language,
        media_type=media_type,
        sha256=sha256_hex(data),
        size_bytes=len(data),
        encoding=encoding,
        decoded=text is not None,
    )
    return Artifact(ref=ref, data=data, text=text)


def load_path(path: Path, *, max_bytes: int = MAX_DEFAULT_BYTES) -> Artifact:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ArtifactError(f"cannot stat {path}: {exc}") from exc
    if size > max_bytes:
        raise ArtifactError(f"{path} is {size} bytes, above the {max_bytes} byte limit")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ArtifactError(f"cannot read {path}: {exc}") from exc
    return load_bytes(data, path=path)


def walk(root: Path, *, follow_symlinks: bool = False) -> list[Path]:
    """Collect regular files under ``root``, skipping build and VCS directories.

    Symlinks are not followed by default: a tree scan should not be steerable
    out of the tree it was pointed at.
    """
    if root.is_file():
        return [root]
    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink() and not follow_symlinks:
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                found.append(entry)
    return sorted(found)
