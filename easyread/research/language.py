"""Research prompt language follows EasyRead targets, including old PaperRead data."""
from ..translate import langs


def reply_rule(meta: dict | None) -> str:
    meta = dict(meta or {})
    if meta.get("target") == "zh-TW":
        meta["target"] = "zh-Hant"
    if meta.get("target") == "zh-Hant":
        return "用繁體中文（臺灣用語），不可使用簡體字"  # i18n-ok: model instruction
    return "用" + langs.reply_lang(meta)  # i18n-ok: model instruction
