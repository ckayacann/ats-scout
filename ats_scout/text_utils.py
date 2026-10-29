from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
})


def fold(s: str) -> str:
    """Lowercase + strip accents (Turkish aware) so 'Mühendisi' matches 'muhendisi'."""
    s = s.translate(_TR_MAP).lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")


def words(s: str) -> list[str]:
    return [w.strip(".-") for w in WORD_RE.findall(fold(s)) if w.strip(".-")]


def count_words(s: str) -> int:
    return len(re.findall(r"\S+", s))


def phrase_regex(term: str) -> re.Pattern:
    """Whole-word regex for a folded term; tolerates a plural 's'."""
    esc = re.escape(term)
    return re.compile(rf"(?<![a-z0-9]){esc}(?:s|es)?(?![a-z0-9+#])")


_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "s", "ly")


def stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            word = word[: -len(suf)]
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word
