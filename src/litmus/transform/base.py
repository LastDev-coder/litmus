"""Transform protocol.

A transform is a pure, deterministic ``str -> str`` function with an id, a
description, and an honest declaration of whether it preserves meaning. No
model calls, no randomness, no clock reads: the same input always produces
byte-identical output.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Transform:
    id: str
    description: str
    #: True when the operation cannot change what the text means to a reader.
    semantics_preserving: bool
    apply: Callable[[str], str]
    #: Caveats that a user needs in order to judge the operation, e.g. that
    #: replacing NO-BREAK SPACE changes line-breaking behaviour.
    note: str = ""


@dataclass(frozen=True)
class AppliedOperation:
    transform: Transform
    changes: int
