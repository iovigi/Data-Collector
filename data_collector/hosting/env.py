"""Load deployment environment from a restricted env file outside the web root.

IIS FastCGI and the Windows worker service both start Python with a minimal environment.
Secrets live in a file readable only by their service identities; its *path* (not its
contents) is supplied via ``DC_ENV_FILE``. Variables already present in the process
environment win over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from data_collector.config import reset_settings_cache

ENV_FILE_VAR = "DC_ENV_FILE"


def load_deployment_env(path: str | None = None) -> bool:
    """Load the env file named by ``path`` or ``DC_ENV_FILE``. Returns True if loaded.

    Raises FileNotFoundError when a path is configured but missing, so a misconfigured
    deployment fails at startup instead of silently running with defaults.
    """
    target = path or os.environ.get(ENV_FILE_VAR, "").strip()
    if not target:
        return False
    env_path = Path(target)
    if not env_path.is_file():
        raise FileNotFoundError(f"{ENV_FILE_VAR} points to a missing file")
    load_dotenv(env_path, override=False, encoding="utf-8")
    reset_settings_cache()
    return True
