"""Template rendering and file writing shared by the context and memory areas.

A template carries `{{name}}` placeholders (letters, digits, underscore, dot and hyphen; spaces inside the braces
are allowed). `render` fills them from a values map and refuses to ship a leftover placeholder: a name with no
value, or a value that itself carries a placeholder, is an error. Output is LF-only. `write_atomic` and `status`
give the dry-run and idempotent write every Batuta area uses (temp file in the same folder, then `os.replace`).
"""
import os
import re
import tempfile
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
LEFTOVER = re.compile(r"\{\{[^{}\n]*\}\}")


class RenderError(ValueError):
    """The template cannot be rendered; the message names every problem."""


def normalise(text):
    """LF line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def placeholders(template):
    """Placeholder names in order of first appearance, without duplicates."""
    seen = []
    for match in PLACEHOLDER.finditer(template):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def render(template, values):
    """Fill the placeholders of `template` from `values` (name -> str). Raises RenderError on any leftover."""
    template = normalise(template)
    missing = [name for name in placeholders(template) if name not in values]
    if missing:
        raise RenderError("no value for placeholder(s): " + ", ".join(missing))
    # One pass over the template: a value is never re-expanded.
    out = PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)
    left = LEFTOVER.findall(out)
    if left:
        raise RenderError("placeholder left after rendering (a value carries one?): " + ", ".join(sorted(set(left))))
    return out


def render_file(path, values):
    """Render the template file at `path` (UTF-8)."""
    return render(Path(path).read_text(encoding="utf-8-sig"), values)


def write_atomic(path, text):
    """Write `text` as UTF-8 with LF line endings through a temp file in the same folder, then `os.replace`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(normalise(text).encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def status(path, text):
    """NEW when the file does not exist, SAME when it already holds `text` byte for byte, else CHANGED."""
    path = Path(path)
    if not path.is_file():
        return "NEW"
    return "SAME" if path.read_bytes() == normalise(text).encode("utf-8") else "CHANGED"
