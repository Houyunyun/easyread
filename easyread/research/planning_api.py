"""Additive goal, follow and reminder endpoints over the existing planning store."""
from __future__ import annotations

import json

from ..app.i18n import tr
from ..library import planning_store


def get(root, endpoint: str):
    if endpoint == "milestones":
        return {"milestones": planning_store.init(root)["milestones"]}
    if endpoint == "follows":
        return {"follows": planning_store.get_follows(root)}
    return None


def post(root, endpoint: str, body: dict):
    if endpoint in ("/milestones", "/follows", "/reminders/claim") and len(json.dumps(body, ensure_ascii=False)) > 64000:
        raise ValueError(tr("规划请求过大"))
    if endpoint == "/milestones":
        return {"milestone": planning_store.add_milestone(root, body)}
    if endpoint == "/milestones/delete":
        return {"deleted": planning_store.delete_milestone(root, str(body.get("id") or ""), bool(body.get("whole_series")))}
    if endpoint == "/follows":
        return {"follow": planning_store.add_follow(root, str(body.get("kind") or ""), str(body.get("value") or ""), str(body.get("label") or ""))}
    if endpoint == "/follows/delete":
        planning_store.remove_follow(root, str(body.get("id") or ""))
        return {"deleted": True}
    if endpoint == "/reminders/claim":
        events = body.get("candidates")
        if not isinstance(events, list) or len(events) > 200 or any(
            not isinstance(event, dict) or not isinstance(event.get("key"), str) or not 1 <= len(event["key"]) <= 300
            for event in events
        ):
            raise ValueError(tr("提醒事件无效"))
        return {"claimed": planning_store.claim_reminders(root, events)}
    return None
