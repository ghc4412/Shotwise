"""Resolve the agent_runtime_profile directory.

Default: ``<PROJECT_ROOT>/agent_runtime_profile``. Set ``SHOTWISE_PROFILE_DIR``
when the runtime profile lives outside the source tree (e.g. read-only
installations that ship the profile at a fixed path).
"""

from __future__ import annotations

import os
from pathlib import Path

from lib.env_init import PROJECT_ROOT


def agent_profile_dir() -> Path:
    override = os.getenv("SHOTWISE_PROFILE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "agent_runtime_profile"
