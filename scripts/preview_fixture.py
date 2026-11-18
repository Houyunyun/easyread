"""Serve an original bilingual reading sample in a disposable library."""
import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def serve_sample(home, port, with_web=False):
    library = home / "library"
    folder = library / "sample-paper"
    folder.mkdir(parents=True)
    os.environ.update(EASYREAD_HOME=str(home), EASYREAD_LIBRARY=str(library), EASYREAD_SYSTEM_LANG="zh-CN")
    sys.path.insert(0, str(ROOT))
    from easyread.library.store import empty_discussion, empty_reader
    from easyread.server.launch import serve
    from smoke_backend import probe_pdf

    (folder / "source.pdf").write_bytes(probe_pdf())
    paper = {
        "schema": 2,
        "meta": {"title_zh": "阅读样例", "title_en": "Reading sample", "page_count": 1, "pdf": "source.pdf"},
        "translation": {"done_pages": [1], "gaps_checked": True},
        "blocks": [
            {"id": "s1", "type": "heading", "level": 1, "page": 1, "zh": "观察", "en": "Observation"},
            {"id": "p1-1", "type": "para", "page": 1, "en": "A reader can follow a quotation back to its source.",
             "zh": "读者可以从笔记里的摘录回到原文，重新打开论文后仍能找到当时正在核对的段落。"},
            {"id": "eq1", "type": "math", "page": 1, "tex": "a^2+b^2=c^2", "tag": "1"},
            {"id": "t1", "type": "table", "page": 1, "head": [["A", "B"]], "rows": [["1", "2"]]}
        ],
    }
    for name, data in {"paper": paper, "reader": empty_reader(), "discussion": empty_discussion()}.items():
        (folder / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if with_web:
        from bs4 import BeautifulSoup
        from easyread.weblog.snapshot import freeze
        web = library / "sample-web"
        (web / "figures").mkdir(parents=True)
        text = "A saved web article stays readable offline. Notes and highlights remain attached to the original sentence. " * 3
        html, meta, blocks = freeze(BeautifulSoup('<html><head><title>Offline web sample</title></head><body><article><h1>Offline web sample</h1><p>' + text + '</p></article></body></html>', 'html.parser'), 'https://example.test/article')
        (web / "source.html").write_text(html, encoding="utf-8")
        (web / "figures" / "sample.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="teal"/></svg>')
        blocks.append({"id": "figure-sample", "type": "figure", "src": "figures/sample.svg", "page": 1})
        for name, data in {"paper": {"schema": 2, "meta": meta, "blocks": blocks, "translation": {"done_pages": [1], "gaps_checked": True}}, "reader": empty_reader(), "discussion": empty_discussion()}.items():
            (web / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    (home / "config.json").write_text(json.dumps({"engine": "none", "auto_translate": False,
        "check_updates": False, "library_dir": str(library)}), encoding="utf-8")
    try:
        serve(port)
    finally:
        logging.shutdown()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--with-web", action="store_true", help="Include a network-free archived webpage for PWA regression tests")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="easyread-preview-") as tmp:
        serve_sample(Path(tmp), args.port, args.with_web)
