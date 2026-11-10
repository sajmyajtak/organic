"""Save the queue's state to git from inside a publish run.

A run that waits for the scheduler's windows can publish several posts over a few
hours. Each one is committed and pushed right away, so a run that is cancelled or
times out never loses what it already published (and never posts it twice).
Only in GitHub Actions (IGBOT_GIT_COMMIT=1); a local run leaves git alone.
"""

from __future__ import annotations

import os
import subprocess

from .config import ROOT


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def save(message: str) -> bool:
    """Commit content/ and push; True if something was pushed."""
    if os.environ.get("IGBOT_GIT_COMMIT") != "1":
        return False
    _git("config", "user.name", "igbot")
    _git("config", "user.email", "igbot@users.noreply.github.com")
    _git("add", "content")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return False
    _git("commit", "-m", message)
    branch = os.environ.get("MEDIA_BRANCH") or "main"
    for _ in range(3):  # someone (Simon, the stats job) may have pushed meanwhile
        _git("pull", "--rebase", "origin", branch)
        if _git("push", "origin", f"HEAD:{branch}").returncode == 0:
            return True
    print("stav fronty se nepodařilo pushnout (zkusí to krok Uložit stav fronty)")
    return False


def refresh() -> None:
    """Pull what was pushed meanwhile (approvals, new posts) before a waiting run looks again."""
    if os.environ.get("IGBOT_GIT_COMMIT") != "1":
        return
    _git("pull", "--rebase", "--autostash", "origin", os.environ.get("MEDIA_BRANCH") or "main")
