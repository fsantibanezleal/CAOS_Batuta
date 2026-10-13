"""Output helpers shared by every area: tag lines and the C20 machine object, with the exit-code rule.

An area builds a list of items (`item(tag, message, path)`), then ends with `emit(area, verb, items, summary, as_json)`
which prints and returns the exit code: 1 when any item is FAIL or REFUSED, else 2 when any is WARN, else 0.
"""
import json
import sys

TAGS = ("OK", "NEW", "CHANGED", "SAME", "SKIP", "MERGED", "REMOVED", "MISSING", "DIFFERENT", "REFUSED", "WARN", "FAIL")
CONTRACT_VERSION = "1.0"
TOOL = "batuta"


def item(tag, message, path=None):
    """One output line as a dict (the C20 item). An unknown tag is a programming error."""
    if tag not in TAGS:
        raise ValueError(f"unknown tag {tag!r}; expected one of {', '.join(TAGS)}")
    d = {"tag": tag, "message": message}
    if path:
        d["path"] = path
    return d


def exit_code(items):
    """0 ok, 1 failure or refusal, 2 warnings or an honest partial."""
    tags = {i["tag"] for i in items}
    if "FAIL" in tags or "REFUSED" in tags:
        return 1
    if "WARN" in tags:
        return 2
    return 0


def render_line(it):
    return f"{it['tag']} {it['message']}" + (f" ({it['path']})" if it.get("path") else "")


def c20_object(area, verb, items, summary):
    """The object printed with --json (contract C20)."""
    return {"contract_version": CONTRACT_VERSION, "tool": TOOL, "area": area, "verb": verb,
            "exit_code": exit_code(items), "items": items, "summary": summary}


def emit(area, verb, items, summary, as_json=False, stream=None):
    """Print the items (tag lines and the summary, or the C20 JSON object) and return the exit code."""
    out = stream or sys.stdout
    if as_json:
        print(json.dumps(c20_object(area, verb, items, summary), indent=2), file=out)
    else:
        for it in items:
            print(render_line(it), file=out)
        print(summary, file=out)
    return exit_code(items)
