"""Identifier-aware tokenizer for code search.

``getUserById``, ``get_user_by_id`` and ``HTTPAuthMiddleware`` must be findable by their parts
("user", "auth") *and* by their exact whole name. So each identifier emits its lower-cased
whole form plus its split parts::

    getUserById       -> getuserbyid, get, user, by, id
    HTTPAuthMiddleware -> httpauthmiddleware, http, auth, middleware
    __init__          -> __init__, init
    route             -> route

Digits stay attached to the preceding letters (``sha256Hash`` -> sha256, hash).
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+\d*|[A-Z]+\d*|\d+")

# Applied to *queries* only. Code bodies keep every token; BM25's IDF already down-weights them.
STOPWORDS = frozenset(
    """a an and are as at be by can do does for from how i if in is it its of on or that the
    this to was were what when where which who why with would should could
    """.split()  # noqa: SIM905 - a word list reads better than a list literal
)


def split_identifier(word: str) -> list[str]:
    """Lower-cased parts of one identifier, split on underscores and camelCase humps."""
    parts: list[str] = []
    for segment in word.split("_"):
        parts.extend(m.group().lower() for m in _PART.finditer(segment))
    return parts


def tokenize(text: str, *, drop_stopwords: bool = False, min_len: int = 2) -> list[str]:
    tokens: list[str] = []
    for match in _WORD.finditer(text):
        word = match.group()
        parts = split_identifier(word)
        whole = word.lower()
        candidates = parts if parts == [whole] else [whole, *parts]
        for tok in candidates:
            if len(tok) < min_len or (drop_stopwords and tok in STOPWORDS):
                continue
            tokens.append(tok)
    return tokens
