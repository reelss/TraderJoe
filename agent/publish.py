"""Publish dashboard.html to GitHub Pages (github.com/reelss/TraderJoe).

Maintains a persistent clone of the Pages repo outside the vault, copies the
freshly built dashboard in as index.html, and commits+pushes only when it
changed. Called at the end of the daily digest run so the live page refreshes
at market close. Best-effort: any failure is logged, never fatal.

Auth uses the machine's Git Credential Manager (same creds that work for manual
pushes). Only index.html is ever published — never the vault or any secret.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import logbook as log
from .config import ROOT

REPO_URL = "https://github.com/reelss/TraderJoe.git"
REPO_DIR = Path.home() / ".traderjoe-pages"
_GIT_FALLBACK = r"C:\Program Files\Git\cmd\git.exe"


def _git_exe() -> str:
    return shutil.which("git") or _GIT_FALLBACK


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([_git_exe(), *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


def publish_dashboard() -> bool:
    dash = ROOT / "dashboard.html"
    if not dash.exists():
        log.info("publish: dashboard.html missing — nothing to publish")
        return False

    # Ensure the persistent clone exists.
    if not (REPO_DIR / ".git").exists():
        REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
        if REPO_DIR.exists():
            shutil.rmtree(REPO_DIR, ignore_errors=True)
        r = subprocess.run([_git_exe(), "clone", "--quiet", REPO_URL, str(REPO_DIR)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            log.info(f"publish: clone failed — {r.stderr.strip()[:200]}")
            return False
    else:
        _run(["pull", "--quiet"], REPO_DIR)

    shutil.copyfile(dash, REPO_DIR / "index.html")
    _run(["add", "index.html"], REPO_DIR)

    # Also publish about.html if it exists alongside the dashboard.
    about = ROOT / "about.html"
    if about.exists():
        shutil.copyfile(about, REPO_DIR / "about.html")
        _run(["add", "about.html"], REPO_DIR)

    # Commit only if anything actually changed.
    if not _run(["status", "--porcelain"], REPO_DIR).stdout.strip():
        log.info("publish: no change since last publish")
        return True

    _run(["-c", "user.name=reelss", "-c", "user.email=reelss@gmail.com",
          "commit", "--quiet", "-m", "Update Joe dashboard"], REPO_DIR)
    push = _run(["push", "--quiet"], REPO_DIR)
    if push.returncode != 0:
        log.info(f"publish: push failed — {push.stderr.strip()[:200]}")
        return False
    log.info("publish: dashboard pushed to GitHub Pages")
    return True
