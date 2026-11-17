"""Initialize a dedicated CLI HOME without overwriting updates or credentials."""
import fcntl
import os
import shutil
import sys
from pathlib import Path


def copy_missing(source, target):
    if source.is_symlink():
        if not os.path.lexists(target):
            target.symlink_to(os.readlink(source))
    elif source.is_dir():
        if os.path.lexists(target) and not target.is_dir():
            return
        target.mkdir(mode=source.stat().st_mode & 0o777, exist_ok=True)
        for child in source.iterdir():
            copy_missing(child, target / child.name)
    elif not os.path.lexists(target):
        shutil.copy2(source, target)


def initialize(home, seed):
    home.mkdir(parents=True, exist_ok=True)
    with (home / '.easyread-init.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = home / '.easyread-cli-initialized'
        if not marker.exists():
            copy_missing(seed, home)
            marker.touch(mode=0o600)


if __name__ == '__main__':
    initialize(Path.home(), Path('/opt/easyread-cli-seed'))
    if len(sys.argv) < 2:
        raise SystemExit('Missing runtime command')
    if sys.argv[1:] != ['python', '-m', 'easyread', 'serve']:
        from easyread.app import proxy
        proxy.apply_saved()
    os.execvp(sys.argv[1], sys.argv[1:])
