"""Text normalization shared by the guards: the command a guard reads is folded before any pattern is matched.

`normalize` (NFKC, zero-width characters removed, common Cyrillic and Greek lookalikes folded to Latin), `deobfuscate`
(PowerShell backticks, cmd carets and quotes cut into a word), `decoded_commands` (PowerShell `-EncodedCommand`
payloads decoded) and `nested_texts` (quoted strings, `$(...)` and backtick bodies) so a pattern is also matched inside
a nested command.
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­‪‫‬‭‮"))
_LOOKALIKES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "ο": "o", "α": "a", "ι": "i", "ρ": "p", "ν": "v", "υ": "u",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X",
})
_ENCODED = re.compile(r"(?<![\w-])-(?:e|ec|en|enc|enco|encod|encode|encoded|encodedc\w*)\s+(\S+)", re.IGNORECASE)
_SHELL_WORD = re.compile(r"\b(?:powershell|pwsh)(?:\.exe)?\b", re.IGNORECASE)
_EMPTY_QUOTES = re.compile(r"\"\"|''")
_QUOTE_IN_WORD = re.compile(r"(?<=\w)[\"'](?=\w)")
_NESTED = (
    re.compile(r"\$\(([^()]*)\)"),
    re.compile(r"`([^`]*)`"),
)


def normalize(text: str) -> str:
    """NFKC, zero-width characters removed, Cyrillic and Greek lookalikes folded to Latin letters."""
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    return text.translate(_LOOKALIKES)


def deobfuscate(text: str) -> str:
    """The text with PowerShell backticks, cmd carets and quotes inside a word removed (`Reg`ister`, `sch^tasks`)."""
    text = text.replace("`", "").replace("^", "")
    text = _EMPTY_QUOTES.sub("", text)
    return _QUOTE_IN_WORD.sub("", text)


def decoded_commands(command: str) -> list:
    """The decoded text of every PowerShell `-EncodedCommand` payload in `command`; None for one that cannot be decoded."""
    if not _SHELL_WORD.search(command):
        return []
    found = []
    for match in _ENCODED.finditer(command):
        raw = match.group(1).strip("\"'")
        try:
            found.append(base64.b64decode(raw, validate=True).decode("utf-16-le"))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            found.append(None)
    return found


def quoted_bodies(text: str) -> list[str]:
    """The bodies of the '...' and "..." strings of `text` (a backslash escapes the next character inside double quotes);
    one linear pass, with no pattern that can backtrack."""
    out: list[str] = []
    i, n = 0, len(text)
    dead: set[str] = set()          # a quote character with no closing one: later ones are not scanned again
    while i < n:
        ch = text[i]
        if ch in "'\"" and ch not in dead:
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if (ch == '"' and text[j] == "\\") else 1
            if j < n:
                out.append(text[i + 1:j])
                i = j
            else:
                dead.add(ch)
        i += 1
    return out


def nested_texts(command: str, depth: int = 3) -> list[str]:
    """Quoted strings, `$(...)` and backtick bodies found in `command`, recursively (a nested command is matched too)."""
    out: list[str] = []
    seen: set[str] = set()
    pending = [(command, depth)]
    while pending:
        text, left = pending.pop()
        bodies = quoted_bodies(text) + [m.group(1) for pattern in _NESTED for m in pattern.finditer(text)]
        for body in bodies:
            if body and body not in seen:
                seen.add(body)
                out.append(body)
                if left > 1:
                    pending.append((body, left - 1))
    return out
