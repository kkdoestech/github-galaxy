"""Settings from the environment, a .env file, or the GitHub CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (Path.cwd() / ".env", ROOT / "backend" / ".env", ROOT / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip("\"'"))
    return values


def _gh_cli_token() -> str | None:
    if not shutil.which("gh"):
        return None
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    token = out.stdout.strip()
    return token if out.returncode == 0 and token else None


@dataclass(frozen=True)
class Settings:
    token: str | None
    token_source: str
    cache_path: Path
    frontend_dist: Path


def load_settings() -> Settings:
    dotenv = _read_dotenv()
    token, source = os.environ.get("GITHUB_TOKEN"), "env"
    if not token and dotenv.get("GITHUB_TOKEN"):
        token, source = dotenv["GITHUB_TOKEN"], ".env"
    if not token and os.environ.get("GALAXY_NO_GH_CLI") != "1":
        token, source = _gh_cli_token(), "gh"
    cache_dir = Path(os.environ.get("CACHE_DIR") or dotenv.get("CACHE_DIR") or ROOT / ".cache")
    return Settings(
        token=token or None,
        token_source=source if token else "none",
        cache_path=cache_dir / "galaxy.sqlite3",
        frontend_dist=ROOT / "frontend" / "dist",
    )
