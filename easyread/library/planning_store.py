"""SQLite state for PaperRead's paper-discovery and reading-planning workspace.

Imported-paper status and dates remain canonical in each paper's item.json. This
database owns research discovery metadata, candidate membership, and legacy
planning records (kept for compatibility with earlier releases).
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..app.i18n import tr

DEFAULT_STATUSES = [
    {"id": "unread", "label": "待阅读", "color": "#8b8b8b", "position": 0, "builtin": True},
    {"id": "reading", "label": "阅读中", "color": "#6b9eb1", "position": 1, "builtin": True},
    {"id": "organizing", "label": "待整理", "color": "#b68a54", "position": 2, "builtin": True},
    {"id": "done", "label": "已完成", "color": "#719879", "position": 3, "builtin": True},
    {"id": "paused", "label": "暂停", "color": "#9a819e", "position": 4, "builtin": True},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(root: Path):
    path = Path(root) / ".paperread-planning.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS statuses (
        id TEXT PRIMARY KEY, label TEXT NOT NULL, color TEXT NOT NULL,
        position INTEGER NOT NULL, builtin INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS saved_papers (
        paper_key TEXT PRIMARY KEY, openalex_id TEXT, doi TEXT, arxiv TEXT,
        metadata_json TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unread', plan_json TEXT NOT NULL DEFAULT '{}',
        interested INTEGER NOT NULL DEFAULT 0, pdf_url TEXT NOT NULL DEFAULT '',
        pdf_state TEXT NOT NULL DEFAULT 'pending', pdf_error TEXT NOT NULL DEFAULT '', manual_order INTEGER NOT NULL DEFAULT 0,
        library_id TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS candidates (
        paper_key TEXT PRIMARY KEY, metadata_json TEXT NOT NULL,
        summary_markdown TEXT NOT NULL DEFAULT '', summary_model TEXT NOT NULL DEFAULT '', summary_updated TEXT NOT NULL DEFAULT '',
        summary_status TEXT NOT NULL DEFAULT '', summary_error TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS paper_summaries (
        paper_key TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, summary_markdown TEXT NOT NULL,
        summary_model TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS paper_summary_trash (
        trash_id TEXT PRIMARY KEY, paper_key TEXT NOT NULL, metadata_json TEXT NOT NULL,
        summary_markdown TEXT NOT NULL, summary_model TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL, updated TEXT NOT NULL, deleted_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS milestones (
        id TEXT PRIMARY KEY, series_id TEXT NOT NULL, title TEXT NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL DEFAULT '',
        recurrence TEXT NOT NULL DEFAULT 'once', color TEXT NOT NULL DEFAULT '#6b9eb1',
        linked_json TEXT NOT NULL DEFAULT '[]', exceptions_json TEXT NOT NULL DEFAULT '{}',
        created TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS follows (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL,
        label TEXT NOT NULL, last_checked TEXT NOT NULL DEFAULT '',
        results_json TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL,
        UNIQUE(kind, value)
      );
      CREATE TABLE IF NOT EXISTS cache (
        cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS skipped (paper_key TEXT PRIMARY KEY, created TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS reminder_claims (
        event_key TEXT PRIMARY KEY, claimed_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS keyword_maps (
        id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS keywords (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, match_text TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL,
        UNIQUE(name)
      );
      CREATE TABLE IF NOT EXISTS keyword_links (
        id TEXT PRIMARY KEY, keyword_id TEXT NOT NULL, paper_id TEXT NOT NULL,
        source TEXT NOT NULL, anchor TEXT NOT NULL DEFAULT '', page INTEGER,
        quote TEXT NOT NULL DEFAULT '', occurrences INTEGER NOT NULL DEFAULT 0,
        excluded INTEGER NOT NULL DEFAULT 0, source_hash TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL,
        UNIQUE(keyword_id, paper_id, source, anchor, quote)
      );
      CREATE TABLE IF NOT EXISTS keyword_scans (
        keyword_id TEXT NOT NULL, paper_id TEXT NOT NULL, source_hash TEXT NOT NULL, updated TEXT NOT NULL,
        PRIMARY KEY(keyword_id, paper_id)
      );
      CREATE TABLE IF NOT EXISTS keyword_exclusions (
        keyword_id TEXT NOT NULL, paper_id TEXT NOT NULL, created TEXT NOT NULL,
        PRIMARY KEY(keyword_id, paper_id)
      );
    """)
    if "locator" not in {r[1] for r in db.execute("PRAGMA table_info(keyword_links)")}:
        db.execute("ALTER TABLE keyword_links ADD COLUMN locator TEXT NOT NULL DEFAULT ''")
    columns = {r[1] for r in db.execute("PRAGMA table_info(saved_papers)")}
    if "manual_order" not in columns:
        db.execute("ALTER TABLE saved_papers ADD COLUMN manual_order INTEGER NOT NULL DEFAULT 0")
    if "archived" not in columns:
        db.execute("ALTER TABLE saved_papers ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    candidate_columns = {r[1] for r in db.execute("PRAGMA table_info(candidates)")}
    for name, declaration in (("summary_markdown", "TEXT NOT NULL DEFAULT ''"), ("summary_model", "TEXT NOT NULL DEFAULT ''"), ("summary_updated", "TEXT NOT NULL DEFAULT ''"), ("summary_status", "TEXT NOT NULL DEFAULT ''"), ("summary_error", "TEXT NOT NULL DEFAULT ''"), ("summary_claim", "TEXT NOT NULL DEFAULT ''")):
        if name not in candidate_columns:
            db.execute(f"ALTER TABLE candidates ADD COLUMN {name} {declaration}")
    for table in ("paper_summaries", "paper_summary_trash"):
        if "summary_target" not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN summary_target TEXT NOT NULL DEFAULT ''")
    existing = db.execute("SELECT count(*) FROM statuses").fetchone()[0]
    if not existing:
        db.executemany("INSERT INTO statuses(id,label,color,position,builtin) VALUES(?,?,?,?,?)",
                        [(s["id"], s["label"], s["color"], s["position"], 1) for s in DEFAULT_STATUSES])
    db.commit()
    return db


@contextmanager
def _db(root: Path):
    db = _connect(root)
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def _read_db(root: Path):
    """Read-only library/trash listings must not initialize or migrate research data."""
    path = Path(root).resolve() / ".paperread-planning.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15) if path.is_file() else None
    if db is not None:
        db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        if db is not None:
            db.close()


def recover_interrupted(root: Path):
    with _db(root) as db:
        db.execute("UPDATE saved_papers SET pdf_state='failed', pdf_error=?, updated=? WHERE pdf_state='running'",
                   (tr("上次下载中断，可重新尝试"), _now()))
        db.commit()


def init(root: Path) -> dict:
    with _db(root) as db:
        return {"statuses": [dict(r) for r in db.execute("SELECT * FROM statuses ORDER BY position,id")],
                "saved": [_saved(r) for r in db.execute("SELECT * FROM saved_papers ORDER BY updated DESC")],
                "milestones": [_milestone(r) for r in db.execute("SELECT * FROM milestones ORDER BY start_date")],
                "follows": [_follow(r) for r in db.execute("SELECT * FROM follows ORDER BY created DESC")]}


def _keyword_key(value: str) -> str:
    import unicodedata
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


# Auto matches hidden by an explicit per-paper exclusion survive any rescan.
_VISIBLE_LINK = ("l.excluded=0 AND NOT (l.source='auto' AND EXISTS("
                 "SELECT 1 FROM keyword_exclusions e WHERE e.keyword_id=l.keyword_id AND e.paper_id=l.paper_id))")


def keyword_upsert(root: Path, name: str, match_text: str, *, replace_match: bool = False) -> dict:
    """Create a keyword or return the existing one with the same normalized name.

    A different match text for an existing name is a conflict unless replace_match is set.
    """
    name, match_text = str(name).strip()[:120], str(match_text).strip()[:180]
    if not name or not match_text:
        raise ValueError(tr("请填写关键字名称与原文比对词"))
    now = _now()
    with _db(root) as db:
        row = next((r for r in db.execute("SELECT * FROM keywords") if _keyword_key(r["name"]) == _keyword_key(name)), None)
        if row:
            if _keyword_key(row["match_text"]) != _keyword_key(match_text):
                if not replace_match:
                    raise ValueError(tr("已有同名关键字，但原文比对词不同"))
                db.execute("UPDATE keywords SET match_text=?, updated=? WHERE id=?", (match_text, now, row["id"]))
            if row["archived"]:
                db.execute("UPDATE keywords SET archived=0, updated=? WHERE id=?", (now, row["id"]))
            kid = row["id"]
        else:
            kid = uuid4().hex
            db.execute("INSERT INTO keywords(id,name,match_text,created,updated) VALUES(?,?,?,?,?)", (kid, name, match_text, now, now))
        db.commit()
        return dict(db.execute("SELECT * FROM keywords WHERE id=?", (kid,)).fetchone())


def keyword_update(root: Path, keyword_id: str, name: str, match_text: str) -> tuple[dict, bool]:
    """Rename a keyword and/or change its match text. Returns (keyword, match_text_changed)."""
    name, match_text = str(name).strip()[:120], str(match_text).strip()[:180]
    if not name or not match_text:
        raise ValueError(tr("请填写关键字名称与原文比对词"))
    with _db(root) as db:
        row = db.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,)).fetchone()
        if not row:
            raise ValueError(tr("找不到关键字"))
        if any(r["id"] != keyword_id and _keyword_key(r["name"]) == _keyword_key(name) for r in db.execute("SELECT id,name FROM keywords")):
            raise ValueError(tr("已有同名关键字"))
        changed = _keyword_key(row["match_text"]) != _keyword_key(match_text)
        db.execute("UPDATE keywords SET name=?, match_text=?, updated=? WHERE id=?", (name, match_text, _now(), keyword_id))
        db.commit()
        return dict(db.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,)).fetchone()), changed


def keyword_list(root: Path, include_archived: bool = False) -> list[dict]:
    with _db(root) as db:
        rows = db.execute(f"SELECT k.*, COUNT(DISTINCT CASE WHEN {_VISIBLE_LINK} THEN l.paper_id END) papers FROM keywords k LEFT JOIN keyword_links l ON l.keyword_id=k.id WHERE (? OR k.archived=0) GROUP BY k.id ORDER BY k.updated DESC", (int(include_archived),)).fetchall()
        return [dict(r) for r in rows]


def keyword_link(root: Path, keyword_id: str, paper_id: str, *, source: str, anchor: str = "", page=None, quote: str = "", occurrences: int = 0, source_hash: str = "", locator: dict | None = None) -> None:
    now = _now()
    locator = locator if isinstance(locator, dict) else {}
    # Reader locating hints only (side + surrounding context); never a second copy of the paper text.
    clean = {"side": locator.get("side") if locator.get("side") in ("en", "zh") else "",
             "prefix": str(locator.get("prefix") or "")[:120], "suffix": str(locator.get("suffix") or "")[:120]}
    locator_json = json.dumps(clean, ensure_ascii=False) if any(clean.values()) else ""
    with _db(root) as db:
        db.execute("INSERT INTO keyword_links(id,keyword_id,paper_id,source,anchor,page,quote,occurrences,source_hash,locator,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(keyword_id,paper_id,source,anchor,quote) DO UPDATE SET occurrences=excluded.occurrences, source_hash=excluded.source_hash, updated=excluded.updated", (uuid4().hex, keyword_id, paper_id, source, anchor[:200], page, quote[:600], max(0, int(occurrences)), source_hash[:80], locator_json, now, now))
        db.commit()


def keyword_scan_state(root: Path, keyword_id: str, paper_id: str) -> tuple[str, int]:
    """(source hash of the last scan, number of stored auto matches) for one keyword/paper pair."""
    with _db(root) as db:
        row = db.execute("SELECT source_hash FROM keyword_scans WHERE keyword_id=? AND paper_id=?", (keyword_id, paper_id)).fetchone()
        count = db.execute("SELECT COUNT(*) FROM keyword_links WHERE keyword_id=? AND paper_id=? AND source='auto'", (keyword_id, paper_id)).fetchone()[0]
        return (row["source_hash"] if row else ""), int(count)


def keyword_replace_auto(root: Path, keyword_id: str, paper_id: str, hits: list[dict], source_hash: str = "") -> None:
    """Atomically replace one paper's auto matches for a keyword; other papers and manual links are untouched."""
    now = _now()
    with _db(root) as db:
        db.execute("DELETE FROM keyword_links WHERE keyword_id=? AND paper_id=? AND source='auto'", (keyword_id, paper_id))
        for hit in hits:
            db.execute("INSERT OR REPLACE INTO keyword_links(id,keyword_id,paper_id,source,anchor,page,quote,occurrences,source_hash,created,updated) VALUES(?,?,?,'auto',?,?,?,?,?,?,?)",
                       (uuid4().hex, keyword_id, paper_id, str(hit.get("anchor") or "")[:200], hit.get("page"), str(hit.get("quote") or "")[:600], max(0, int(hit.get("occurrences") or 0)), source_hash[:80], now, now))
        db.execute("INSERT OR REPLACE INTO keyword_scans(keyword_id,paper_id,source_hash,updated) VALUES(?,?,?,?)", (keyword_id, paper_id, source_hash[:80], now))
        db.commit()


def keyword_unlink(root: Path, keyword_id: str, paper_id: str) -> dict:
    """Remove only the user-collected links between one keyword and one paper.

    The keyword, other papers' links and any automatic match stay; auto_remaining tells the UI
    whether the paper still appears through an automatic match (use the exclusion for that).
    """
    with _db(root) as db:
        removed = db.execute("DELETE FROM keyword_links WHERE keyword_id=? AND paper_id=? AND source='manual'", (keyword_id, paper_id)).rowcount
        remaining = db.execute(f"SELECT COUNT(*) FROM keyword_links l WHERE l.keyword_id=? AND l.paper_id=? AND l.source='auto' AND {_VISIBLE_LINK}", (keyword_id, paper_id)).fetchone()[0]
        db.commit()
        return {"removed": int(removed), "auto_remaining": int(remaining)}


def keyword_matches(root: Path, keyword_ids: list[str], mode: str = "all", manual_only: bool = False) -> list[dict]:
    ids = [str(x) for x in keyword_ids if str(x)]
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with _db(root) as db:
        source = "AND l.source='manual'" if manual_only else ""
        required = 1 if mode in ("any", "or") else len(ids)
        sql = f"SELECT l.paper_id, GROUP_CONCAT(DISTINCT l.keyword_id) keyword_ids, SUM(l.occurrences) occurrences FROM keyword_links l JOIN keywords k ON k.id=l.keyword_id AND k.archived=0 WHERE l.keyword_id IN ({marks}) AND {_VISIBLE_LINK} {source} GROUP BY l.paper_id HAVING COUNT(DISTINCT l.keyword_id)>=?"
        return [dict(r) for r in db.execute(sql, (*ids, required)).fetchall()]


def keyword_links_for_paper(root: Path, paper_id: str, keyword_ids: list[str] | None = None) -> list[dict]:
    ids = [str(value) for value in (keyword_ids or []) if str(value)]
    with _db(root) as db:
        sql = f"SELECT l.*, k.name, k.match_text FROM keyword_links l JOIN keywords k ON k.id=l.keyword_id AND k.archived=0 WHERE l.paper_id=? AND {_VISIBLE_LINK}"
        args = [paper_id]
        if ids:
            sql += " AND l.keyword_id IN (" + ",".join("?" for _ in ids) + ")"
            args.extend(ids)
        return [dict(r) for r in db.execute(sql + " ORDER BY k.name", args).fetchall()]


def keyword_exclude(root: Path, keyword_id: str, paper_id: str, excluded: bool) -> None:
    with _db(root) as db:
        if excluded:
            db.execute("INSERT OR IGNORE INTO keyword_exclusions(keyword_id,paper_id,created) VALUES(?,?,?)", (keyword_id, paper_id, _now()))
        else:
            db.execute("DELETE FROM keyword_exclusions WHERE keyword_id=? AND paper_id=?", (keyword_id, paper_id))
        db.commit()


def keyword_archive(root: Path, keyword_ids: str | list[str], archived: bool) -> int:
    ids = [keyword_ids] if isinstance(keyword_ids, str) else list(keyword_ids or [])
    ids = [str(x) for x in ids if str(x).strip()]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    with _db(root) as db:
        if len(ids) == 1 and not db.execute(f"SELECT 1 FROM keywords WHERE id IN ({marks})", ids).fetchone():
            raise ValueError(tr("找不到关键字"))
        cur = db.execute(f"UPDATE keywords SET archived=?, updated=? WHERE id IN ({marks})", (int(archived), _now(), *ids))
        db.commit()
        return cur.rowcount


def keyword_delete(root: Path, keyword_ids: str | list[str]) -> int:
    ids = [keyword_ids] if isinstance(keyword_ids, str) else list(keyword_ids or [])
    ids = [str(x) for x in ids if str(x).strip()]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    with _db(root) as db:
        db.execute(f"DELETE FROM keyword_links WHERE keyword_id IN ({marks})", ids)
        db.execute(f"DELETE FROM keyword_scans WHERE keyword_id IN ({marks})", ids)
        db.execute(f"DELETE FROM keyword_exclusions WHERE keyword_id IN ({marks})", ids)
        cur = db.execute(f"DELETE FROM keywords WHERE id IN ({marks})", ids)
        db.commit()
        return cur.rowcount


def statuses(root: Path) -> list[dict]:
    with _read_db(root) as db:
        values = ([dict(item) for item in DEFAULT_STATUSES] if db is None else
                  [dict(r) for r in db.execute("SELECT * FROM statuses ORDER BY position,id")])
    defaults = {item["id"]: item["label"] for item in DEFAULT_STATUSES}
    for item in values:
        if item.get("builtin") and item["label"] == defaults.get(item["id"]):
            item["label"] = tr(item["label"])
    return values


def validate_statuses(values: list[dict]) -> list[tuple[str, str, str, int, int]]:
    visible_builtins = {s["id"] for s in DEFAULT_STATUSES if s["id"] != "paused"}
    if not isinstance(values, list) or len(values) < len(visible_builtins) or len(values) > 30:
        raise ValueError(tr("状态栏设定不正确"))
    known = visible_builtins
    ids = set()
    rows = []
    for pos, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(tr("状态栏设定不正确"))
        sid = str(item.get("id", ""))[:40]
        label = str(item.get("label", "")).strip()[:32]
        if not sid or sid in ids or not label:
            raise ValueError(tr("每个状态都需要不重复的识别码与名称"))
        ids.add(sid)
        builtin = sid in known or sid == "paused"
        if not builtin and not sid.startswith("custom-"):
            raise ValueError(tr("自订状态识别码格式不正确"))
        color = str(item.get("color") or "#8b8b8b")[:16]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError(tr("状态色彩格式不正确"))
        rows.append((sid, label, color, pos, 1 if builtin else 0))
    if not known.issubset(ids):
        raise ValueError(tr("内建状态不能删除"))
    return rows


def save_statuses(root: Path, values: list[dict], moves: dict | None = None) -> list[dict]:
    rows = validate_statuses(values)
    ids = {row[0] for row in rows}
    moves = moves or {}
    with _db(root) as db:
        old = {r["id"]: dict(r) for r in db.execute("SELECT * FROM statuses")}
        defaults = {item["id"]: item["label"] for item in DEFAULT_STATUSES}
        # A settings round-trip must not persist translated default labels. Real
        # user renames (including renames of builtin statuses) remain untouched.
        rows = [(sid, defaults[sid] if sid in defaults and old.get(sid, {}).get("label") == defaults[sid]
                 and label == tr(defaults[sid]) else label, color, pos, builtin)
                for sid, label, color, pos, builtin in rows]
        # Preserve the old paused status row and any associated item values as
        # hidden legacy data. It no longer appears in the UI or accepts new moves.
        if "paused" in old and "paused" not in ids:
            p = old["paused"]
            rows.append(("paused", p["label"], p["color"], p["position"], p["builtin"]))
            ids.add("paused")
        removed = set(old) - ids
        for sid in removed:
            target = str(moves.get(sid) or "")
            if not target or target not in ids:
                raise ValueError(tr("删除状态前，请指定论文要移到哪一栏"))
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM statuses")
        db.executemany("INSERT INTO statuses(id,label,color,position,builtin) VALUES(?,?,?,?,?)", rows)
        db.commit()
    return statuses(root)


def _saved(row):
    d = dict(row)
    d["metadata"] = json.loads(d.pop("metadata_json"))
    d["plan"] = json.loads(d.pop("plan_json") or "{}")
    d["interested"] = bool(d["interested"])
    d["archived"] = bool(d.get("archived", 0))
    try:
        cats = json.loads(d.get("category") or "[]")
        d["categories"] = cats if isinstance(cats, list) else [str(cats)]
    except (TypeError, json.JSONDecodeError):
        d["categories"] = [d["category"]] if d.get("category") else []
    d["category"] = d["categories"][0] if d["categories"] else ""
    return d


def _milestone(row):
    d = dict(row)
    d["linked"] = json.loads(d.pop("linked_json") or "[]")
    d["exceptions"] = json.loads(d.pop("exceptions_json") or "{}")
    return d


def _follow(row):
    d = dict(row)
    d["results"] = json.loads(d.pop("results_json") or "[]")
    return d


def upsert_saved(root: Path, paper_key: str, work: dict, category: str = "", plan: dict | None = None,
                 interested: bool | None = None, pdf_url: str = "") -> dict:
    now = _now()
    metadata = {k: work.get(k) for k in ("id", "openalex_id", "doi", "arxiv", "title", "authors", "year", "venue", "abstract", "cited_by_count", "is_oa", "url", "source")}
    categories = category if isinstance(category, list) else ([category] if category else [])
    categories_json = json.dumps(list(dict.fromkeys(str(c)[:80] for c in categories if str(c).strip())), ensure_ascii=False)
    with _db(root) as db:
        db.execute("""INSERT INTO saved_papers(paper_key,openalex_id,doi,arxiv,metadata_json,category,status,plan_json,interested,pdf_url,pdf_state,created,updated)
          VALUES(?,?,?,?,?,?,'unread',?,?,?,'pending',?,?)
          ON CONFLICT(paper_key) DO UPDATE SET metadata_json=excluded.metadata_json, category=CASE WHEN excluded.category='[]' THEN saved_papers.category ELSE excluded.category END,
          plan_json=CASE WHEN ? THEN excluded.plan_json ELSE saved_papers.plan_json END, interested=CASE WHEN ? THEN excluded.interested ELSE saved_papers.interested END, pdf_url=CASE WHEN excluded.pdf_url='' THEN saved_papers.pdf_url ELSE excluded.pdf_url END, updated=excluded.updated""",
          (paper_key, metadata.get("openalex_id"), metadata.get("doi"), metadata.get("arxiv"), json.dumps(metadata, ensure_ascii=False), categories_json,
           json.dumps(plan or {}, ensure_ascii=False), int(bool(interested)), pdf_url, now, now, plan is not None, interested is not None))
        db.commit()
        return _saved(db.execute("SELECT * FROM saved_papers WHERE paper_key=?", (paper_key,)).fetchone())


def saved(root: Path, paper_key: str) -> dict | None:
    with _db(root) as db:
        row = db.execute("SELECT * FROM saved_papers WHERE paper_key=?", (paper_key,)).fetchone()
        return _saved(row) if row else None


def get_saved(root: Path) -> list[dict]:
    with _db(root) as db:
        return [_saved(r) for r in db.execute("SELECT * FROM saved_papers ORDER BY updated DESC")]


def candidate_add(root: Path, paper_key: str, work: dict) -> dict:
    now = _now()
    allowed = ("id", "openalex_id", "doi", "arxiv", "title", "authors", "year", "venue", "abstract", "cited_by_count", "is_oa", "pdf_url", "url", "source")
    metadata = {k: work.get(k) for k in allowed}
    with _db(root) as db:
        db.execute("""INSERT INTO candidates(paper_key,metadata_json,summary_status,created,updated) VALUES(?,?, 'queued',?,?)
          ON CONFLICT(paper_key) DO UPDATE SET metadata_json=excluded.metadata_json,updated=excluded.updated""",
          (paper_key, json.dumps(metadata, ensure_ascii=False), now, now))
        db.execute("UPDATE candidates SET summary_status='ready' WHERE paper_key=? AND EXISTS (SELECT 1 FROM paper_summaries WHERE paper_key=?)", (paper_key, paper_key))
        db.commit()
        row = db.execute("SELECT * FROM candidates WHERE paper_key=?", (paper_key,)).fetchone()
    result = _candidate(row)
    result.update(summary(root, paper_key) or {})
    return result


def _candidate(row):
    d = dict(row)
    d["paper"] = json.loads(d.pop("metadata_json"))
    return d


def candidates(root: Path) -> list[dict]:
    with _db(root) as db:
        values = [_candidate(r) for r in db.execute("SELECT * FROM candidates ORDER BY created DESC")]
    summaries = {x["paper_key"]: x for x in summaries_list(root)}
    return [{**value, **summaries.get(value["paper_key"], {})} for value in values]


def candidate_remove(root: Path, paper_key: str) -> bool:
    with _db(root) as db:
        cur = db.execute("DELETE FROM candidates WHERE paper_key=?", (paper_key,))
        db.commit()
        return cur.rowcount > 0


def candidate_save_summary(root: Path, paper_key: str, markdown: str, model: str = "", *, expected_claim: str | None = None, target: str = "") -> dict | None:
    """Manual saves supersede jobs; automatic saves require their current claim."""
    from ..translate.langs import normalize
    target = normalize(target)
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        now = _now()
        row = db.execute("SELECT metadata_json,summary_status,summary_claim FROM candidates WHERE paper_key=?", (paper_key,)).fetchone()
        if not row or (expected_claim is not None and (not expected_claim or row["summary_status"] != "running" or row["summary_claim"] != expected_claim)):
            return None
        db.execute("INSERT INTO paper_summaries(paper_key,metadata_json,summary_markdown,summary_model,created,updated) VALUES(?,?,?,?,?,?)"
                   " ON CONFLICT(paper_key) DO UPDATE SET metadata_json=excluded.metadata_json,summary_markdown=excluded.summary_markdown,summary_model=excluded.summary_model,updated=excluded.updated",
                   (paper_key, row["metadata_json"], markdown[:100000], model[:200], now, now))
        db.execute("UPDATE paper_summaries SET summary_target=? WHERE paper_key=?", (target, paper_key))
        db.execute("UPDATE candidates SET summary_status='ready',summary_error='',summary_claim='',summary_updated=?,summary_model=?,updated=? WHERE paper_key=?",
                   (now, model[:200], now, paper_key))
        db.commit()
        row = db.execute("SELECT * FROM paper_summaries WHERE paper_key=?", (paper_key,)).fetchone()
    return _summary(row) if row else None


def candidate_summary_status(root: Path, paper_key: str, status: str, error: str = "", *, expected_claim: str | None = None) -> bool:
    if status not in ("queued", "running", "failed", "ready"):
         raise ValueError(tr("摘要状态不正确"))
    with _db(root) as db:
        condition = " AND summary_status='running' AND summary_claim=?" if expected_claim is not None else ""
        values = [status, error[:1000], _now(), paper_key]
        if expected_claim is not None:
            if not expected_claim:
                return False
            values.append(expected_claim)
        cur = db.execute("UPDATE candidates SET summary_status=?,summary_error=?,summary_claim='',updated=? WHERE paper_key=?" + condition,
                         values)
        db.commit()
        return cur.rowcount == 1


def recover_candidate_summaries(root: Path) -> int:
    """Requeue jobs interrupted by an application shutdown."""
    with _db(root) as db:
        cur = db.execute("UPDATE candidates SET summary_status='queued',summary_error='上次整理中断，已重新排入伫列。',updated=? WHERE summary_status='running'", # i18n-dom: 固定保存繁中，前端显示时翻译。
                         (_now(),))
        db.commit()
        return cur.rowcount


def candidate_summary_queue(root: Path, limit: int = 5) -> list[dict]:
    with _db(root) as db:
        rows = db.execute("SELECT * FROM candidates WHERE summary_status='queued' AND paper_key NOT IN (SELECT paper_key FROM paper_summaries) ORDER BY created LIMIT ?", (max(1, min(5, limit)),)).fetchall()
    return [_candidate(row) for row in rows]


def candidate_summary_claim(root: Path, paper_keys: list[str]) -> list[dict]:
    if not paper_keys:
        return []
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in paper_keys)
        claim = uuid4().hex
        db.execute(f"UPDATE candidates SET summary_status='running',summary_error='',summary_claim=?,updated=? WHERE summary_status='queued' AND paper_key IN ({placeholders})",
                   [claim, _now(), *paper_keys])
        rows = db.execute("SELECT * FROM candidates WHERE summary_claim=?", (claim,)).fetchall()
        db.commit()
    return [_candidate(row) for row in rows]


def _summary(row):
    value = dict(row)
    value["paper"] = json.loads(value.pop("metadata_json"))
    return value


def summary(root: Path, paper_key: str) -> dict | None:
    with _db(root) as db:
        row = db.execute("SELECT * FROM paper_summaries WHERE paper_key=?", (paper_key,)).fetchone()
    return _summary(row) if row else None


def summary_save(root: Path, paper_key: str, markdown: str, *, expected_updated: str | None = None,
                 expected_markdown: str | None = None) -> dict:
    """Edit an existing summary atomically; never resurrect a deleted summary."""
    if not isinstance(paper_key, str) or not paper_key.strip():
        raise ValueError(tr("论文识别资料不正确。"))
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError(tr("摘要内容是空的，没有可储存的内容。"))
    if len(markdown) > 100000:
        raise ValueError(tr("摘要内容过长，请缩短后再保存。"))
    if any(value is not None and not isinstance(value, str) for value in (expected_updated, expected_markdown)):
        raise ValueError(tr("摘要编辑基准格式不正确。"))
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM paper_summaries WHERE paper_key=?", (paper_key,)).fetchone()
        if not row:
            raise ValueError(tr("找不到这篇论文的摘要。"))
        if ((expected_updated is not None and row["updated"] != expected_updated)
                or (expected_markdown is not None and row["summary_markdown"] != expected_markdown)):
            raise ValueError(tr("摘要已变更，请重新打开后再编辑。"))
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        db.execute("UPDATE paper_summaries SET summary_markdown=?,summary_model='',summary_target='',updated=? WHERE paper_key=?",
                   (markdown, now, paper_key))
        db.execute("UPDATE candidates SET summary_markdown='',summary_model='',summary_status='ready',summary_error='',summary_claim='',summary_updated=?,updated=? WHERE paper_key=?",
                   (now, now, paper_key))
        saved = db.execute("SELECT * FROM paper_summaries WHERE paper_key=?", (paper_key,)).fetchone()
        db.commit()
    return _summary(saved)


def summaries_list(root: Path) -> list[dict]:
    with _db(root) as db:
        return [_summary(row) for row in db.execute("SELECT * FROM paper_summaries ORDER BY updated DESC")]


def summary_move_to_trash(root: Path, paper_key: str) -> dict | None:
    """Move an organized summary to the app Trash without touching its paper."""
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM paper_summaries WHERE paper_key=?", (paper_key,)).fetchone()
        if not row:
            db.rollback()
            return None
        trash_id = uuid4().hex
        deleted_at = _now()
        db.execute("INSERT INTO paper_summary_trash(trash_id,paper_key,metadata_json,summary_markdown,summary_model,created,updated,deleted_at) VALUES(?,?,?,?,?,?,?,?)",
                   (trash_id, row["paper_key"], row["metadata_json"], row["summary_markdown"], row["summary_model"], row["created"], row["updated"], deleted_at))
        db.execute("UPDATE paper_summary_trash SET summary_target=? WHERE trash_id=?", (row["summary_target"], trash_id))
        db.execute("DELETE FROM paper_summaries WHERE paper_key=?", (paper_key,))
        db.execute("UPDATE candidates SET summary_markdown='',summary_model='',summary_updated='',summary_status='',summary_error='',updated=? WHERE paper_key=?",
                   (deleted_at, paper_key))
        db.commit()
        return {**_summary(row), "trash_id": trash_id, "deleted": deleted_at}


def summary_trash_items(root: Path) -> list[dict]:
    with _read_db(root) as db:
        if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_summary_trash'").fetchone():
            return []
        rows = db.execute("SELECT * FROM paper_summary_trash ORDER BY deleted_at DESC").fetchall()
    return [{**_summary(row), "name": row["trash_id"], "type": "summary", "deleted": row["deleted_at"]} for row in rows]


def summary_trash_restore(root: Path, trash_id: str) -> bool:
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM paper_summary_trash WHERE trash_id=?", (trash_id,)).fetchone()
        if not row:
            raise ValueError(tr("回收站里没有这份摘要"))
        if db.execute("SELECT 1 FROM paper_summaries WHERE paper_key=?", (row["paper_key"],)).fetchone():
            raise ValueError(tr("这篇论文已有摘要；请先移除目前的摘要，再还原这份摘要。"))
        db.execute("INSERT INTO paper_summaries(paper_key,metadata_json,summary_markdown,summary_model,created,updated) VALUES(?,?,?,?,?,?)",
                   (row["paper_key"], row["metadata_json"], row["summary_markdown"], row["summary_model"], row["created"], row["updated"]))
        db.execute("UPDATE paper_summaries SET summary_target=? WHERE paper_key=?", (row["summary_target"], row["paper_key"]))
        db.execute("DELETE FROM paper_summary_trash WHERE trash_id=?", (trash_id,))
        now = _now()
        db.execute("UPDATE candidates SET summary_markdown=?,summary_model=?,summary_updated=?,summary_status='ready',summary_error='',updated=? WHERE paper_key=?",
                   (row["summary_markdown"], row["summary_model"], row["updated"], now, row["paper_key"]))
        db.commit()
        return True


def summary_trash_purge(root: Path, trash_id: str) -> int:
    with _db(root) as db:
        cur = db.execute("DELETE FROM paper_summary_trash WHERE trash_id=?", (trash_id,))
        db.commit()
        return cur.rowcount


def summary_trash_empty(root: Path) -> int:
    with _db(root) as db:
        cur = db.execute("DELETE FROM paper_summary_trash")
        db.commit()
        return cur.rowcount


def summary_trash_count(root: Path) -> int:
    with _read_db(root) as db:
        if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_summary_trash'").fetchone():
            return 0
        return db.execute("SELECT count(*) FROM paper_summary_trash").fetchone()[0]


def update_saved(root: Path, paper_key: str, **fields):
    allowed = {"pdf_state", "pdf_error", "library_id", "status", "category", "plan_json", "interested", "manual_order", "archived"}
    sets = [f"{k}=?" for k in fields if k in allowed]
    values = [fields[k] for k in fields if k in allowed]
    if not sets:
        return
    sets.append("updated=?")
    values.extend((_now(), paper_key))
    with _db(root) as db:
        db.execute(f"UPDATE saved_papers SET {','.join(sets)} WHERE paper_key=?", values)
        db.commit()


def claim_pdf_download(root: Path, paper_key: str) -> bool:
    """Atomically claim one pending/failed PDF job across duplicate requests."""
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        cur = db.execute("UPDATE saved_papers SET pdf_state='running',pdf_error='',updated=? WHERE paper_key=? AND pdf_state IN ('pending','failed')",
                         (_now(), paper_key))
        db.commit()
        return cur.rowcount == 1


def move_saved_status(root: Path, old: str, new: str):
    with _db(root) as db:
        db.execute("UPDATE saved_papers SET status=?,updated=? WHERE status=?", (new, _now(), old))
        db.commit()


def add_milestone(root: Path, data: dict) -> dict:
    title = str(data.get("title", "")).strip()[:160]
    start = str(data.get("start_date", ""))
    if not title or len(start) != 10:
        raise ValueError(tr("请填写里程碑名称与日期"))
    end = str(data.get("end_date") or start)
    try:
        start = date.fromisoformat(start).isoformat()
        end = date.fromisoformat(end).isoformat()
    except ValueError as exc:
        raise ValueError(tr("里程碑日期格式不正确")) from exc
    if end < start:
        raise ValueError(tr("里程碑结束日期不能早于开始日期"))
    recurrence = data.get("recurrence", "once")
    if recurrence not in ("once", "weekly"):
        raise ValueError(tr("目前只支援单次或每周重复"))
    linked = data.get("linked") or []
    if not isinstance(linked, list) or len(linked) > 200 or any(not isinstance(x, str) or len(x) > 120 for x in linked):
        raise ValueError(tr("关联论文格式不正确"))
    exceptions = data.get("exceptions") or {}
    if not isinstance(exceptions, dict):
        raise ValueError(tr("重复场次设定格式不正确"))
    if len(json.dumps(exceptions, ensure_ascii=False)) > 30000:
        raise ValueError(tr("重复场次设定内容过多"))
    cancelled = exceptions.get("cancelled") or []
    overrides = exceptions.get("overrides") or {}
    if not isinstance(cancelled, list) or not isinstance(overrides, dict) or len(cancelled) > 500 or len(overrides) > 500:
        raise ValueError(tr("重复场次设定格式不正确"))
    try:
        for occurrence in cancelled:
            date.fromisoformat(str(occurrence))
        for occurrence, override in overrides.items():
            date.fromisoformat(str(occurrence))
            if not isinstance(override, dict):
                raise ValueError
            moved_start = date.fromisoformat(str(override.get("start_date") or occurrence))
            moved_end = date.fromisoformat(str(override.get("end_date") or moved_start.isoformat()))
            if moved_end < moved_start or not isinstance(override.get("linked", []), list) or len(override.get("linked", [])) > 200:
                raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError(tr("重复场次日期或关联论文格式不正确")) from exc
    color = str(data.get("color") or "#6b9eb1")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError(tr("里程碑色彩格式不正确"))
    mid = str(data.get("id") or "m-" + uuid4().hex)
    series = str(data.get("series_id") or mid)
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in (mid, series)):
        raise ValueError(tr("里程碑 ID 无效"))
    now = _now()
    with _db(root) as db:
        db.execute("""INSERT INTO milestones(id,series_id,title,start_date,end_date,recurrence,color,linked_json,exceptions_json,created,updated)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,start_date=excluded.start_date,end_date=excluded.end_date,
          recurrence=excluded.recurrence,color=excluded.color,linked_json=excluded.linked_json,exceptions_json=excluded.exceptions_json,updated=excluded.updated""",
          (mid, series, title, start, end, recurrence, color, json.dumps(linked),
           json.dumps(exceptions, ensure_ascii=False), now, now))
        db.commit()
        return _milestone(db.execute("SELECT * FROM milestones WHERE id=?", (mid,)).fetchone())


def delete_milestone(root: Path, mid: str, whole_series: bool = False):
    with _db(root) as db:
        row = db.execute("SELECT series_id FROM milestones WHERE id=?", (mid,)).fetchone()
        if not row:
            return False
        if whole_series:
            db.execute("DELETE FROM milestones WHERE series_id=?", (row[0],))
        else:
            db.execute("DELETE FROM milestones WHERE id=?", (mid,))
        db.commit()
        return True


def add_follow(root: Path, kind: str, value: str, label: str = "") -> dict:
    if kind not in ("topic", "author") or not value.strip():
        raise ValueError(tr("追踪项目需要主题或作者资料"))
    if kind == "author":
        value = value.rstrip("/").split("/")[-1]
        if not re.fullmatch(r"A\d+", value):
            raise ValueError(tr("请先从作者搜寻结果选定 OpenAlex 作者，避免追踪到同名作者。"))
    fid = "f-" + uuid4().hex
    with _db(root) as db:
        db.execute("INSERT OR IGNORE INTO follows(id,kind,value,label,created) VALUES(?,?,?,?,?)",
                   (fid, kind, value[:500], (label or value)[:160], _now()))
        db.commit()
        row = db.execute("SELECT * FROM follows WHERE kind=? AND value=?", (kind, value[:500])).fetchone()
        return _follow(row)


def update_follow(root: Path, fid: str, checked: str, results: list):
    with _db(root) as db:
        db.execute("UPDATE follows SET last_checked=?,results_json=? WHERE id=?", (checked, json.dumps(results, ensure_ascii=False), fid))
        db.commit()


def remove_follow(root: Path, fid: str):
    with _db(root) as db:
        db.execute("DELETE FROM follows WHERE id=?", (fid,))
        db.commit()


def get_follows(root: Path):
    with _db(root) as db:
        return [_follow(r) for r in db.execute("SELECT * FROM follows ORDER BY created DESC")]


def cache_get(root: Path, key: str):
    with _db(root) as db:
        row = db.execute("SELECT payload_json,updated FROM cache WHERE cache_key=?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else (None, "")


def cache_put(root: Path, key: str, payload: dict):
    with _db(root) as db:
        db.execute("INSERT INTO cache(cache_key,payload_json,updated) VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,updated=excluded.updated",
                   (key, json.dumps(payload, ensure_ascii=False), _now()))
        db.commit()


# The reading-path map is intentionally a single, versioned snapshot per
# library and output locale. Keeping it in the existing cache table avoids a second migration
# for a small piece of workspace state, while the dedicated key means normal
# discovery-cache expiry rules never apply to it.
READING_PATH_CACHE_KEY = "reading-path:latest"


def reading_path_cache_key(target: str = "") -> str:
    from ..app import i18n
    from ..translate import langs
    return READING_PATH_CACHE_KEY + ":" + langs.valid(target or i18n.lang())


def latest_reading_path(root: Path) -> dict | None:
    value, _ = cache_get(root, reading_path_cache_key())
    return value if isinstance(value, dict) else None


def _validate_reading_path_steps(steps: list[dict]) -> list[str]:
    keys = [str(step.get("paper_key") or "").strip() for step in steps if isinstance(step, dict)]
    if not keys or len(keys) != len(steps) or len(set(keys)) != len(keys):
        raise ValueError(tr("阅读路径资料不完整，请重新产生。"))
    return keys


def replace_reading_path(root: Path, snapshot: dict) -> dict:
    steps = list(snapshot.get("results") or [])
    _validate_reading_path_steps(steps)
    now = _now()
    from ..app import i18n
    from ..translate import langs
    target = langs.valid(snapshot.get("target") or i18n.lang())
    record = {**snapshot, "target": target, "path_id": "rp-" + uuid4().hex, "revision": 1,
              "created_at": now, "updated_at": now, "relations": [],
              "relations_checked_at": "", "relations_error": ""}
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO cache(cache_key,payload_json,updated) VALUES(?,?,?) "
                   "ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,updated=excluded.updated",
                   (reading_path_cache_key(target), json.dumps(record, ensure_ascii=False), now))
        db.commit()
    return record


def reorder_reading_path(root: Path, path_id: str, revision: int, paper_keys: list[str]) -> dict:
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload_json FROM cache WHERE cache_key=?", (reading_path_cache_key(),)).fetchone()
        record = json.loads(row[0]) if row else None
        if not isinstance(record, dict) or record.get("path_id") != path_id:
            raise ValueError(tr("这份阅读路径已被较新的结果取代，请重新载入。"))
        if int(record.get("revision") or 0) != int(revision):
            raise ValueError(tr("阅读路径已在其他页面更新，请重新载入后再调整。"))
        current = _validate_reading_path_steps(list(record.get("results") or []))
        order = [str(key or "").strip() for key in paper_keys]
        if len(order) != len(current) or len(set(order)) != len(order) or set(order) != set(current):
            raise ValueError(tr("阅读顺序必须包含目前路径中的每一篇论文，且不能重复。"))
        by_key = {step["paper_key"]: step for step in record["results"]}
        record["results"] = [{**by_key[key], "priority": index + 1} for index, key in enumerate(order)]
        record["manual_order"] = True
        record["revision"] = int(record["revision"]) + 1
        record["updated_at"] = _now()
        db.execute("UPDATE cache SET payload_json=?,updated=? WHERE cache_key=?",
                   (json.dumps(record, ensure_ascii=False), record["updated_at"], reading_path_cache_key()))
        db.commit()
    return record


def save_reading_path_relations(root: Path, path_id: str, revision: int, relations: list[dict], *, checked_at: str = "", error: str = "") -> dict:
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload_json FROM cache WHERE cache_key=?", (reading_path_cache_key(),)).fetchone()
        record = json.loads(row[0]) if row else None
        if not isinstance(record, dict) or record.get("path_id") != path_id:
            raise ValueError(tr("这份阅读路径已被较新的结果取代，请重新载入。"))
        if int(record.get("revision") or 0) != int(revision):
            raise ValueError(tr("阅读路径已在其他页面更新，请重新载入后再更新引用资料。"))
        valid_keys = set(_validate_reading_path_steps(list(record.get("results") or [])))
        clean, seen = [], set()
        for relation in relations or []:
            if not isinstance(relation, dict):
                continue
            source = str(relation.get("source") or "").strip()
            target = str(relation.get("target") or "").strip()
            pair = (source, target)
            if source not in valid_keys or target not in valid_keys or source == target or pair in seen:
                continue
            seen.add(pair)
            clean.append({"source": source, "target": target, "evidence": "openalex"})
        record["relations"] = clean
        record["relations_checked_at"] = checked_at or _now()
        record["relations_error"] = str(error or "")[:500]
        record["revision"] = int(record["revision"]) + 1
        record["updated_at"] = _now()
        db.execute("UPDATE cache SET payload_json=?,updated=? WHERE cache_key=?",
                   (json.dumps(record, ensure_ascii=False), record["updated_at"], reading_path_cache_key()))
        db.commit()
    return record


def skip(root: Path, key: str):
    with _db(root) as db:
        db.execute("INSERT OR IGNORE INTO skipped(paper_key,created) VALUES(?,?)", (key, _now()))
        db.commit()


def skipped(root: Path):
    with _db(root) as db:
        return {r[0] for r in db.execute("SELECT paper_key FROM skipped")}


def claim_reminders(root: Path, candidates: list[dict]) -> list[dict]:
    claimed = []
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        for event in candidates:
            cur = db.execute("INSERT OR IGNORE INTO reminder_claims(event_key,claimed_at) VALUES(?,?)", (event["key"], _now()))
            if cur.rowcount:
                claimed.append(event)
        db.commit()
    return claimed


def keyword_maps(root: Path, identity: str = "") -> list[dict]:
    with _db(root) as db:
        if identity:
            rows = db.execute("SELECT payload_json FROM keyword_maps WHERE id=?", (identity,))
        else:
            rows = db.execute("SELECT payload_json FROM keyword_maps ORDER BY updated DESC,id")
        return [json.loads(row[0]) for row in rows]


def keyword_map_save(root: Path, name: str, data: dict, identity: str = "", revision: int = 0) -> dict:
    name = str(name or "").strip()
    if not name or len(name) > 200 or not isinstance(data, dict):
        raise ValueError(tr("关键词图谱无效"))
    now = _now()
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT payload_json FROM keyword_maps WHERE id=?", (identity,)).fetchone() if identity else None
        previous = json.loads(old[0]) if old else None
        if identity and not previous:
            raise ValueError(tr("找不到关键词图谱"))
        if previous and previous["revision"] != revision:
            raise ValueError(tr("关键词图谱已变更，请重新载入后保存"))
        identity = identity or "km-" + uuid4().hex
        record = {"id": identity, "name": name, "data": data, "revision": revision + 1,
                  "created_at": previous["created_at"] if previous else now, "updated_at": now}
        db.execute("INSERT INTO keyword_maps(id,payload_json,updated) VALUES(?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated=excluded.updated",
                   (identity, json.dumps(record, ensure_ascii=False), now))
        db.commit()
    return record


def keyword_map_delete(root: Path, identity: str) -> None:
    with _db(root) as db:
        db.execute("DELETE FROM keyword_maps WHERE id=?", (identity,))
        db.commit()


def save_mindmap(root: Path, cache_key: str, result: dict, revision: int | None = None) -> dict:
    """Share optimistic revisions between generated and manually edited maps."""
    with _db(root) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload_json FROM cache WHERE cache_key=?", (cache_key,)).fetchone()
        previous = json.loads(row[0]) if row else {}
        current = int(previous.get("revision") or 0)
        if revision is not None and revision != current:
            raise ValueError(tr("心智图已变更，请重新载入后保存"))
        record = {**previous, **result, "revision": current + 1, "updated_at": _now()}
        db.execute("INSERT INTO cache(cache_key,payload_json,updated) VALUES(?,?,?) "
                   "ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,updated=excluded.updated",
                   (cache_key, json.dumps(record, ensure_ascii=False), record["updated_at"]))
        db.commit()
    return record
