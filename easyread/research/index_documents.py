"""Document-level research index updates and explicitly personal reader passages."""
from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def document_write(db):
    """A failed encoder must leave all previous chunks and FTS rows intact."""
    db.execute("SAVEPOINT research_document")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO research_document")
        raise
    finally:
        db.execute("RELEASE research_document")


def reader_passages(paper_id: str, paper: dict, reader: dict):
    """Yield personal notes separately from paper evidence, with source anchors."""
    blocks = {str(block.get("id") or ""): block for block in paper.get("blocks") or []}
    note = reader.get("paper_note") or {}
    documents = [("paper-note", "Paper note", "", 0, str(note.get("body") or ""))]
    for identity, note in (reader.get("notes") or {}).items():
        if not isinstance(note, dict) or note.get("deleted"):
            continue
        anchor = str(note.get("anchor") or note.get("key") or "").partition("#")[0]
        page = int((blocks.get(anchor) or {}).get("page") or note.get("page") or 0)
        text = "\n".join(str(note.get(key) or "").strip() for key in ("quote", "body")).strip()
        documents.append(("note:" + str(identity), "Reader note " + str(identity), anchor, page, text))
    for identity, heading, anchor, page, text in documents:
        cap = 320 if sum("\u3400" <= c <= "\u9fff" for c in text) > len(text) * 0.08 else 1050
        for part, start in enumerate(range(0, len(text), cap - min(100, cap // 4))):
            content = text[start:start + cap].strip()
            if content:
                yield (f"reader-note:{paper_id}:{identity}:{part}", heading, page, anchor, content, "reader-note")
