import os
import re
import unicodedata
from typing import Final

try:
    import regex
except ImportError:  # pragma: no cover
    regex = None

MAX_NAME_GRAPHEMES: Final[int] = int(os.environ.get("MAX_NAME_GRAPHEMES", "80"))
MAX_SECOND_LINE_GRAPHEMES: Final[int] = int(os.environ.get("MAX_SECOND_LINE_GRAPHEMES", "120"))

_ALLOWED_FORMAT_CHARS: Final[set[str]] = {
    "\u200c",  # ZWNJ
    "\u200d",  # ZWJ
    "\ufe0e",  # VS15 text style
    "\ufe0f",  # VS16 emoji style
}

_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _clean_controls(value: str) -> str:
    cleaned_chars: list[str] = []
    for ch in value:
        category = unicodedata.category(ch)
        if category in {"Cc", "Cs", "Co", "Cn"}:
            continue
        if category == "Cf" and ch not in _ALLOWED_FORMAT_CHARS:
            continue
        cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def _truncate_graphemes(value: str, max_graphemes: int) -> str:
    clusters = split_graphemes(value)
    if len(clusters) <= max_graphemes:
        return value
    return "".join(clusters[:max_graphemes])


def split_graphemes(value: str) -> list[str]:
    if regex is not None:
        return regex.findall(r"\X", value)

    clusters: list[str] = []
    for char in value:
        if not clusters:
            clusters.append(char)
            continue

        category = unicodedata.category(char)
        prev = clusters[-1]
        if (
            category.startswith("M")
            or char in _ALLOWED_FORMAT_CHARS
            or prev.endswith("\u200d")
        ):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def sanitize_text_line(value: str | None, max_graphemes: int) -> str | None:
    if value is None:
        return None

    normalized = unicodedata.normalize("NFC", value)
    normalized = _clean_controls(normalized)
    normalized = normalized.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        return None

    return _truncate_graphemes(normalized, max_graphemes)


def sanitize_label_text(name: str, second_line: str | None) -> tuple[str, str | None]:
    clean_name = sanitize_text_line(name, MAX_NAME_GRAPHEMES)
    clean_second_line = sanitize_text_line(second_line, MAX_SECOND_LINE_GRAPHEMES)

    if clean_name is None:
        raise ValueError("Name must contain at least one printable character")

    return clean_name, clean_second_line


def safe_log_text(value: str | None, limit: int = 120) -> str:
    if value is None:
        return ""

    cleaned = _clean_controls(value)
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = f"{cleaned[:limit]}..."
    return cleaned
