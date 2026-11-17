"""Research reader operations; shared journal and revision handling remain in store."""
from __future__ import annotations

import base64
import binascii
import io
import math
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

from PIL import Image

from .store import _newer

def _valid_sticker_link(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and parsed.username is None and parsed.password is None and (parsed.port is None or 0 < parsed.port < 65536)
    except ValueError:
        return False


def _valid_sticker_data(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 540000:
        return False
    match = re.fullmatch(r"data:(image/(?:png|webp|svg\+xml));base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        return False
    try:
        raw = base64.b64decode(match.group(2), validate=True)
        if not raw or len(raw) > 400000:
            return False
        if match.group(1) != "image/svg+xml":
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != {"image/png": "PNG", "image/webp": "WEBP"}[match.group(1)] or image.width * image.height > 16000000:
                    return False
                image.verify()
            return True
        text = raw.decode("utf-8")
        if re.search(r"<!doctype|<!entity|<\?xml-stylesheet|@import|url\s*\(", text, re.I):
            return False
        root = ElementTree.fromstring(text)
        allowed = {"svg", "g", "defs", "style", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "title", "desc"}
        if root.tag.split("}")[-1] != "svg":
            return False
        for element in root.iter():
            tag = element.tag.split("}")[-1]
            if tag not in allowed:
                return False
            if tag == "style" and not re.fullmatch(r"(?:\s*\.[a-zA-Z0-9_-]+\s*\{\s*fill\s*:\s*#[0-9a-fA-F]{3,8}\s*;?\s*\}\s*)*", element.text or ""):
                return False
            if any(k.lower().startswith("on") or k.lower().endswith("href") or re.search(r"url\s*\(|javascript:|data:", v, re.I) for k, v in element.attrib.items()):
                return False
        return True
    except (ValueError, TypeError, UnicodeError, ElementTree.ParseError, binascii.Error, OSError, Image.DecompressionBombError):
        return False


def apply_research_op(reader: dict, op: dict, at: str) -> list[str]:
    ai_annotations = reader.setdefault("ai_annotations", {})
    ink = reader.setdefault("ink", {})
    stickers = reader.setdefault("stickers", {})
    applied = []
    for kind in (op.get("op"),):
        if kind == "ai_annotation":
            annotation = dict(op.get("annotation") or {})
            aid = str(annotation.get("annotation_id") or annotation.get("id") or "")
            if not aid:
                continue
            cur = ai_annotations.get(aid)
            if cur and not _newer(annotation.get("updated_at") or at, cur.get("updated_at")):
                continue
            annotation["annotation_id"] = aid
            annotation.setdefault("created_at", at)
            annotation["updated_at"] = annotation.get("updated_at") or at
            ai_annotations[aid] = annotation
            applied.append(f"ai_annotation:{aid}")
        elif kind in ("ink", "ink_del"):
            stroke = dict(op.get("stroke") or {}) if kind == "ink" else {"id": str(op.get("id") or "")}
            sid = str(stroke.get("id") or "")
            if not sid or len(sid) > 80:
                continue
            cur = ink.get(sid) or {}
            if _newer(at, cur.get("updated")):
                if kind == "ink":
                    points = stroke.get("points")
                    if (not isinstance(points, list) or not 1 <= len(points) <= 2000 or
                            any(not isinstance(p, list) or len(p) != 2 or
                                any(not isinstance(v, (int, float)) or isinstance(v, bool) or abs(v) > 5000 or not math.isfinite(v) for v in p)
                                for p in points)):
                        raise ValueError("Invalid ink stroke points")
                    if (not isinstance(stroke.get("anchor"), str) or len(stroke["anchor"]) > 200 or
                            not isinstance(stroke.get("group"), str) or len(stroke["group"]) > 80 or
                            ("groupId" in stroke and (not isinstance(stroke["groupId"], str) or not re.fullmatch(r"[a-z0-9-]{1,80}", stroke["groupId"]))) or
                            not isinstance(stroke.get("textHash"), str) or len(stroke["textHash"]) != 8 or
                            any(c not in "0123456789abcdef" for c in stroke["textHash"].lower()) or
                            not isinstance(stroke.get("color"), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", stroke["color"]) or
                            not isinstance(stroke.get("width"), (int, float)) or isinstance(stroke.get("width"), bool) or
                            not 1 <= stroke["width"] <= 12 or not math.isfinite(stroke["width"]) or
                            not isinstance(stroke.get("ref"), list) or len(stroke["ref"]) != 2 or
                            any(not isinstance(v, (int, float)) or isinstance(v, bool) or not 1 <= v <= 5000 or not math.isfinite(v) for v in stroke["ref"])):
                        raise ValueError("Invalid ink stroke")
                    ink[sid] = {**stroke, "updated": at}
                else:
                    ink[sid] = {**cur, "id": sid, "deleted": True, "updated": at}
                applied.append(f"ink:{sid}")
        elif kind in ("sticker", "sticker_del"):
            sticker = dict(op.get("sticker") or {}) if kind == "sticker" else {"id": str(op.get("id") or "")}
            sid = str(sticker.get("id") or "")
            if not sid or len(sid) > 80:
                continue
            cur = stickers.get(sid) or {}
            if not _newer(at, cur.get("updated")):
                continue
            if kind == "sticker":
                numeric = ("x", "y", "width", "height", "rotation", "opacity", "z")
                if (not isinstance(sticker.get("assetId"), str) or not re.fullmatch(r"[a-z0-9-]{1,100}", sticker["assetId"]) or
                        not isinstance(sticker.get("anchor"), str) or not 1 <= len(sticker["anchor"]) <= 200 or
                        not isinstance(sticker.get("textHash"), str) or not re.fullmatch(r"[0-9a-f]{8}", sticker["textHash"]) or
                        not isinstance(sticker.get("ref"), list) or len(sticker["ref"]) != 2 or
                        any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not 1 <= v <= 5000 for v in sticker["ref"]) or
                        any(not isinstance(sticker.get(k), (int, float)) or isinstance(sticker.get(k), bool) or not math.isfinite(sticker[k]) for k in numeric) or
                        not all(abs(sticker[k]) <= 5000 for k in ("x", "y")) or
                        not all(1 <= sticker[k] <= 5000 for k in ("width", "height")) or
                        abs(sticker["rotation"]) > 36000 or not 0 <= sticker["opacity"] <= 1 or
                        abs(sticker["z"]) > 1000000 or not isinstance(sticker.get("locked"), bool) or
                        ("strokeColor" in sticker and (not isinstance(sticker["strokeColor"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", sticker["strokeColor"]))) or
                        ("strokeWidth" in sticker and (not isinstance(sticker["strokeWidth"], (int, float)) or isinstance(sticker["strokeWidth"], bool) or not math.isfinite(sticker["strokeWidth"]) or not 1 <= sticker["strokeWidth"] <= 4)) or
                        ("href" in sticker and not _valid_sticker_link(sticker["href"])) or
                        ("textColor" in sticker and (not isinstance(sticker["textColor"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", sticker["textColor"]))) or
                        ("textSize" in sticker and (not isinstance(sticker["textSize"], (int, float)) or isinstance(sticker["textSize"], bool) or not math.isfinite(sticker["textSize"]) or not 10 <= sticker["textSize"] <= 72)) or
                        ("textBold" in sticker and not isinstance(sticker["textBold"], bool)) or
                        ("groupId" in sticker and (not isinstance(sticker["groupId"], str) or not re.fullmatch(r"[a-z0-9-]{1,80}", sticker["groupId"]))) or
                        (sticker["assetId"] == "paperread-text-box" and (not isinstance(sticker.get("text"), str) or len(sticker["text"]) > 2000)) or
                        ("customData" in sticker and not _valid_sticker_data(sticker["customData"])) or
                        (sticker["assetId"].startswith("custom-") and "customData" not in sticker)):
                    raise ValueError("Invalid sticker")
                stickers[sid] = {**sticker, "updated": at}
            else:
                stickers[sid] = {**cur, "id": sid, "deleted": True, "updated": at}
            applied.append(f"sticker:{sid}")
    return applied
