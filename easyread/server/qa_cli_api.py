"""Authenticated settings endpoints for Q&A-only CLI capabilities and skills."""
import json
import re

from ..app import config, native_cli_settings, qa_skills
from ..engines import qa_capabilities
from ..library.store import write_json_atomic
from .access_routes import same_origin

_PATTERN = re.compile(r"^/api/chat/cli/(claude|codex)(/skills/import)?$")


def listing(engine):
    selected = qa_capabilities.policy(config.load(), engine)
    items = qa_skills.inventory(engine)
    for item in items:
        item["enabled"] = qa_capabilities.skill_enabled(engine, item, selected)
        item["inherited_enabled"] = qa_capabilities.skill_enabled(engine, item, {**selected, "skill_overrides": {}})
    return {"engine": engine, "settings": selected, "skills": items,
            "native": native_cli_settings.summary(engine),
            "tools": qa_capabilities.CLAUDE_TOOLS + ["Skill", "Bash", "Write", "Edit", "Agent"] if engine == "claude" else qa_capabilities.CODEX_TOOLS}


def handle(handler):
    from urllib.parse import urlsplit
    match = _PATTERN.fullmatch(urlsplit(handler.path).path)
    if not match:
        return False
    engine, action = match.groups()
    if handler.command in ("GET", "HEAD") and not action:
        handler._json(200, listing(engine))
        return True
    if handler.command != "POST":
        handler._json(405, {"error": "Method not allowed"})
        return True
    if not same_origin(handler):
        handler.close_connection = True
        handler._json(403, {"error": "bad origin"})
        return True
    if int(handler.headers.get("Content-Length", "0")) > (8 * 1024 * 1024 if action else 65536):
        raise ValueError("CLI settings upload is too large")
    body = json.loads(handler._body() or b"{}")
    if not isinstance(body, dict):
        raise ValueError("Expected object")
    if action:
        qa_skills.import_skill(engine, body.get("filename", ""), body.get("content_b64", ""))
    else:
        selected = qa_capabilities.validate(engine, body)
        with config.SAVE_LOCK:
            # Replace this engine policy, rather than deep-merging stale skill overrides.
            saved = config._merge(config.DEFAULTS, config._saved())
            saved.setdefault("qa_cli", {})[engine] = selected
            write_json_atomic(config.CONFIG_PATH, saved)
    handler._json(200, listing(engine))
    return True
