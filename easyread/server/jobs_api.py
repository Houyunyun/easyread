"""后台任务的批量接口：一键停止翻译。单篇的取消仍走 /api/p/<id>/cancel。"""
from __future__ import annotations

from ..app.i18n import tr


def library_state(app):
    """Add live scheduling policy after listing (never bake config into cached summaries)."""
    from .. import __version__
    from ..app import config, cli_models
    from ..library import trash
    from . import research_api
    from .paper_scheduling import auto_translation_enabled
    lib, cfg = app.lib, config.load()
    items = []
    for item in lib.list():
        job = item.get("job")
        if job:
            pending = job.get("state") in ("queued", "running") and auto_translation_enabled(job, cfg)
            item = {**item, "job": {**job, "auto_translate_pending": pending}}
        items.append(item)
    return {"items": items, "token": app.token, "jobs": app.jobs.small_status(),
            "library_status": app.location.status, "other_device": app.location.marker.other_device(),
            "engine": cfg.get("engine"), "engine_label": cli_models.engine_label(cfg),
            "research_statuses": research_api.statuses(lib.root),
            "first_run": config.is_first_run(), "version": __version__,
            "trash": len(trash.items(lib.root)) + research_api.trash_count(lib.root)}


def post(app, path: str, body: dict):
    if path == "/api/jobs/stop":  # ids 不给就是全部
        ids = body.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
            raise ValueError(tr("ids 必须是字符串数组"))
        return {"stopped": app.jobs.stop_model_work(ids)}
    return None


POST = {"/api/jobs/stop"}
