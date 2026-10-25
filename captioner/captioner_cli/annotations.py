"""Strict transcript annotations kept separate from acoustic alignment text."""
from html import escape
import re


TAGS = {"b", "i", "highlight"}
TAG_START = re.compile(r"<(?=[/!a-zA-Z?])")
COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def parse_annotations(text):
    """Return exact plain text and per-word styled runs, or None for plain input."""
    if not TAG_START.search(text):
        return text, None
    chunks, runs, stack = [], [], []
    cursor = offset = 0
    for match in TAG_START.finditer(text):
        if match.start() < cursor:
            continue
        chunk = text[cursor:match.start()]
        chunks.append(chunk)
        runs.append((offset, offset + len(chunk), tuple(name for name, _ in stack)))
        offset += len(chunk)
        end = text.find(">", match.start())
        if end < 0:
            raise ValueError("Unfinished annotation tag. Use <b>, <i>, or <highlight> with matching closing tags.")
        tag = text[match.start() + 1:end]
        closing = tag.startswith("/")
        name = tag[1:] if closing else tag
        if name not in TAGS:
            raise ValueError(f"Unsupported annotation <{tag}>. Only <b>, <i>, and <highlight> are supported.")
        if closing:
            if not stack or stack[-1][0] != name:
                raise ValueError(f"Mismatched annotation </{name}>. Close nested tags in reverse order.")
            _, start = stack.pop()
            if start == offset:
                raise ValueError(f"Empty annotation <{name}> is not supported.")
        else:
            if any(active == name for active, _ in stack):
                raise ValueError(f"Repeated nested annotation <{name}> is not supported.")
            stack.append((name, offset))
        cursor = end + 1
    if stack:
        raise ValueError(f"Unclosed annotation <{stack[-1][0]}>.")
    chunks.append(text[cursor:])
    runs.append((offset, offset + len(text[cursor:]), ()))
    plain = "".join(chunks)
    if not plain.strip():
        raise ValueError("Generate or enter a transcript first.")
    words, run_index = [], 0
    for word in re.finditer(r"\S+", plain):
        while run_index < len(runs) and runs[run_index][1] <= word.start():
            run_index += 1
        fragments, index = [], run_index
        while index < len(runs) and runs[index][0] < word.end():
            start, end, styles = runs[index]
            fragment = plain[max(start, word.start()):min(end, word.end())]
            if fragment:
                fragments.append((fragment, styles))
            index += 1
        words.append(fragments)
    return plain, words


def apply_annotations(words, annotations):
    if annotations is None:
        return words
    expected = ["".join(text for text, _ in fragments) for fragments in annotations]
    if [word["word"].strip() for word in words] != expected:
        raise ValueError("Aligned words do not match the annotated transcript.")
    return [dict(word, annotations=fragments) for word, fragments in zip(words, annotations)]


def validate_colors(subtitle_color, highlight_color):
    for color in (subtitle_color, highlight_color):
        if not isinstance(color, str) or not COLOR.fullmatch(color):
            raise ValueError("Subtitle and highlight colours must use six-digit hex values, such as #FFD600.")


def render_word(word, subtitle_color, highlight_color):
    if "annotations" not in word:
        return word["word"].strip()
    token = word["word"].strip()
    # Do not apply automatic styling to addresses, paths, or code-like tokens.
    numeric_date = re.fullmatch(r"\d{1,4}/\d{1,2}(?:/\d{1,4})?[.,!?]?", token)
    protected = any(marker in token for marker in ("://", "@", "\\", "`", "<", ">"))
    protected = protected or ("/" in token and not numeric_date)
    numeric = any(char.isdigit() for char in token) and not protected
    parts = []
    for text, styles in word["annotations"]:
        color = highlight_color if numeric or "highlight" in styles else subtitle_color
        rendered = f'<font color="{color}">{escape(text, quote=False)}</font>'
        for style in ("i", "b"):
            if style in styles:
                rendered = f"<{style}>{rendered}</{style}>"
        parts.append(rendered)
    return "".join(parts)
