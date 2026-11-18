"""One language policy for paper AI and UI-scoped research generation."""
from ..app import i18n
from ..translate import langs


def ui_target() -> str:
    return langs.valid(i18n.lang())


def reply_rule(meta: dict | None = None) -> str:
    return "只用" + langs.reply_lang(meta)  # i18n-ok: prompt


def output_rule(target: str) -> str:
    """Applies to generated prose, not source quotations or machine identifiers."""
    return (f"输出语言：{reply_rule({'target': target})}。所有新生成的标题、章节名、说明、理由和正文都必须使用该语言；"  # i18n-ok: prompt
            "将下方结构示例中的人类可读标题和缺失信息提示也用该语言表达，不要照抄示例语言。"  # i18n-ok: prompt
            "原文引句必须逐字保留，不翻译；保留用户原始笔记作为输入，不擅自转换。"  # i18n-ok: prompt
            "JSON 键、ID、枚举值、来源标记、公式及必要的学术术语保持原样。\n")  # i18n-ok: prompt


def ui_text(text: str, target: str = "", **values) -> str:
    """Resolve generated labels using the same captured locale as their AI body."""
    translated = i18n.ui_dict(target or ui_target()).get(text) or text
    return translated.format(**values) if values else translated
