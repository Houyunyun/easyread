"""Model activity shared by CLI updates and exit-on-last-page behavior."""
from ..research import background, tasks


def model_work(app) -> bool:
    return (app.jobs.busy() or bool(app.babeldoc.running) or tasks.busy()
            or background.busy(app.lib.root))
