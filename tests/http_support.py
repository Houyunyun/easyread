"""Deterministic access state for HTTP tests that are not testing authentication."""
import os
from unittest.mock import patch

from easyread.server.access import Access


def anonymous_access(root):
    with patch.dict(os.environ, {"EASYREAD_ACCESS_CODE": ""}):
        return Access(root / ".test-access.json")
