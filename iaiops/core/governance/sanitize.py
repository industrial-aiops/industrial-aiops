"""Prompt-injection defense: strip control characters and truncate untrusted text.

Consolidated from 22 duplicate ``_sanitize()`` implementations across the AIops tool line.
All skills should import from here instead of defining their own copy.
"""

from __future__ import annotations

import re
import unicodedata

# C0 control chars (except tab \x09, LF \x0a, CR \x0d) + C1 control chars
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize(text: str | None, max_len: int = 500) -> str:
    """Strip control characters, Unicode format chars, and truncate.

    Removes:
    - C0/C1 control characters (except newline/tab)
    - Unicode Format characters (Cf): zero-width spaces, bidi overrides,
      zero-width joiners — used in prompt injection attacks

    Stripping happens BEFORE truncation so an attacker cannot push the real
    payload past the cut-off by padding with junk control characters.
    ``None`` sanitizes to ``""``.

    Args:
        text: Untrusted text from network API responses.
        max_len: Maximum length after truncation. Default 500.

    Returns:
        Cleaned, truncated string safe for LLM consumption.
    """
    if text is None:
        return ""
    stripped = _CONTROL_CHAR_RE.sub("", str(text))
    cleaned = "".join(c for c in stripped if unicodedata.category(c) != "Cf")
    return cleaned[:max_len]
