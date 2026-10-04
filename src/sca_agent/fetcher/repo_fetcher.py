"""Git repository cloning and updating for scanned projects (via Dulwich)."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dulwich import porcelain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedRepo:
    """Result of a fetch operation on a single repository."""

    name: str
    url: str
    branch: str
    local_path: str
    commit_hash: str


class GitFetchError(Exception):
    """Raised when a git clone or fetch fails."""

    def __init__(self, message: str, details: str = "") -> None:
        self.details = details
        super().__init__(message)


def fetch_repo(
    name: str,
    url: str,
    local_path: str | Path,
    branch: str,
) -> FetchedRepo:
    """Clone or update a repository and return metadata about it.

    * If ``local_path`` does **not** contain a ``.git`` → fresh clone via Dulwich.
    * Otherwise → fast update via ``git fetch`` + ``checkout`` (Dulwich porcelain).

    Raises
    ------
    GitFetchError
        When the clone or update fails.
    """
    path = Path(local_path).resolve()

    if not _is_git_repo(path):
        logger.info("[%-20s] Cloning %s (branch %s)", name, url, branch)
        _clone(name, url, path, branch)
    else:
        logger.info("[%-20s] Updating existing clone (branch %s)", name, branch)
        _update(path, branch)

    has_build = any((path / f).exists() for f in ("pom.xml", "build.gradle"))
    if not has_build:
        logger.warning("[%-20s] No pom.xml or build.gradle found — is this a Java project?", name)

    commit_hash = _get_commit_hash(path)
    return FetchedRepo(
        name=name,
        url=url,
        branch=branch,
        local_path=str(path),
        commit_hash=commit_hash,
    )


# ---- internal helpers ---------------------------------------------------------


def _is_git_repo(path: Path) -> bool:
    """Return True if *path* looks like a cloned Git repository."""
    return (path / ".git").exists()


def _clone(name: str, url: str, path: Path, branch: str) -> None:
    """Perform a fresh git clone with depth-1."""
    try:
        porcelain.clone(url, str(path), checkout=True, depth=1, ref=branch)
    except Exception as exc:
        raise GitFetchError(f"Failed to clone {url} into {path}", details=str(exc)) from exc

    logger.info("[%-20s] Clone complete", name)


def _update(path: Path, branch: str) -> None:
    """Fetch latest changes and checkout the target branch."""
    # Check dirty state
    repo = porcelain.open_repository(str(path))
    dirty = not repo.state.clean()  # type: ignore[attr-defined]
    if dirty:
        logger.warning("Dirty working tree in %s — ignoring uncommitted changes", path)

    # Fetch origin
    try:
        porcelain.fetch(str(path), ["origin"])
    except Exception as exc:
        raise GitFetchError(f"git fetch origin failed for {path}", details=str(exc)) from exc

    # Checkout target branch (force)
    try:
        porcelain.checkout(repo, branch.encode())
    except Exception as exc:
        raise GitFetchError(f"git checkout {branch} failed for {path}", details=str(exc)) from exc

    # Deepen history for full transitive dependency analysis
    try:
        porcelain.fetch(str(path), ["origin"], deepen=[50])
    except Exception as exc:
        logger.warning("[git fetch --deepen failed for %s — scanning may miss transitive deps]", path)


def _get_commit_hash(path: Path) -> str:
    """Return the current 40-char SHA-1 of HEAD."""
    try:
        with porcelain.open_repository(str(path)) as repo:
            ref = repo.refs.get(b"HEAD")
            if ref is None:
                raise GitFetchError(f"No HEAD ref for {path}")
            return ref.decode() if isinstance(ref, bytes) else ref
    except Exception as exc:
        raise GitFetchError(f"Could not read commit hash for {path}", details=str(exc)) from exc
