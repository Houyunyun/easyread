"""Extract model JSON without mistaking citation brackets for a result.

Adapted from bisuwuss-netizen's EasyRead PR #64. Keep block-array responses
supported, and skip malformed outer containers instead of rescuing their children.
"""
from __future__ import annotations

import json
import re

_DECODER = json.JSONDecoder(strict=False)

# Models sometimes emit TeX with a single slash. JSON accepts \b, \f, \n,
# \r and \t and silently destroys those commands, so repair known TeX names
# before decoding. Paired (already escaped) slashes remain untouched.
_TEX_CTRL = re.compile(
    r'(?<!\\)(\\\\)*\\(?=(?:'
    r'frac|beta|begin|big|bigg|bigl|bigr|mathbf|boldsymbol|'
    r'text|textbf|textit|textrm|theta|tau|times|tilde|to|top|triangle|tanh|tan|tfrac|therefore|'
    r'rho|right|rangle|rceil|rfloor|rm|real|'
    r'nabla|neq|ne|nu|not|ni|norm|natural|neg|nmid|nparallel)\b)'
)
_BAD_ESCAPE = re.compile(r'(?<!\\)(\\\\)*\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')


def _end(text: str, start: int) -> int:
    depth, quoted, escaped = 0, False, False
    for i in range(start, len(text)):
        char = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _payload(text: str):
    error, pos = None, 0
    while pos < len(text):
        match = re.search(r"[\[{]", text[pos:])
        if not match:
            break
        start = pos + match.start()
        pos = _end(text, start)
        try:
            obj, end = _DECODER.raw_decode(text, start)
            if end == pos and (isinstance(obj, dict) or isinstance(obj, list)
                               and (all(isinstance(block, dict) for block in obj)
                                    or all(isinstance(item, str) for item in obj))):
                return obj, None
        except json.JSONDecodeError as exc:
            error = error or exc
    return None, error


def extract(text: str):
    """Return a JSON object, block array or query list; ignore numeric citations."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = _TEX_CTRL.sub(r"\g<0>\\", text)
    obj, error = _payload(text)
    if obj is None:
        obj, _ = _payload(_BAD_ESCAPE.sub(r"\g<0>\\", text))
    return obj, error
