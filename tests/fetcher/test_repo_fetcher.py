"""Tests for sca_agent.fetcher.repo_fetcher — clone/update paths and error handling (via Dulwich)."""

from pathlib import Path
from unittest import mock

import pytest

from sca_agent.fetcher.repo_fetcher import GitFetchError, fetch_repo


def _mock_porcelain():
    """Return a mocked dulwich.porcelain module."""
    return mock.patch("sca_agent.fetcher.repo_fetcher.porcelain")


class MockRepo:
    """Minimal Dulwich repo stub used in update-path tests."""

    def __init__(self):
        self._dirty = False

    @property
    def refs(self):
        class Refs(dict):
            def get(self, key):
                return b"abc123def456" if key == b"HEAD" else None
        return Refs()

    @property
    def state(self):
        class State:
            def clean(self):
                return not self._dirty
        return State()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestFetchRepo:
    """Verify both clone and update code paths via mocked Dulwich."""

    def test_first_time_clone_calls_dulwich_clone(self, tmp_path: Path):
        """Task 2.1: clone path — .git does not exist."""
        local = tmp_path / "repo"
        with _mock_porcelain() as mock_porcelain:
            fetch_repo(name="test-repo", url="https://github.com/x/y.git", local_path=local, branch="main")

        mock_porcelain.clone.assert_called_once_with(
            "https://github.com/x/y.git", str(local), checkout=True, depth=1, ref="main"
        )

    def test_subsequent_update_calls_fetch_and_checkout(self, tmp_path: Path):
        """Task 2.1: update path — .git already exists."""
        local = tmp_path / "repo"
        (local / ".git").mkdir(parents=True)

        mock_repo_inst = MockRepo()

        with _mock_porcelain() as mock_porcelain:
            mock_porcelain.open_repository.return_value.__enter__ = lambda s: mock_repo_inst  # type: ignore[assignment]
            fetch_repo(name="test-repo", url="https://github.com/x/y.git", local_path=local, branch="feature")

        mock_porcelain.fetch.assert_any_call(str(local), ["origin"])
        mock_porcelain.checkout.assert_called()

    def test_git_error_on_clone_failure(self, tmp_path: Path):
        """GitFetchError raised on clone failure, details contain original message."""
        local = tmp_path / "bad"
        with _mock_porcelain() as mock_porcelain:
            mock_porcelain.clone.side_effect = Exception("auth failed")
            with pytest.raises(GitFetchError) as exc_info:
                fetch_repo(name="bad", url="https://github.com/x/secret.git", local_path=local, branch="main")

            err = exc_info.value
            assert err.details == "auth failed"

    def test_commit_hash_returned(self, tmp_path: Path):
        """Task 2.2: integrity check — commit hash returned from HEAD ref."""
        local = tmp_path / "repo"
        mock_repo_inst = MockRepo()

        with _mock_porcelain() as mock_porcelain:
            mock_porcelain.open_repository.return_value.__enter__ = lambda s: mock_repo_inst  # type: ignore[assignment]
            mock_porcelain.open_repository.return_value.__exit__ = lambda *a: None
            mock_porcelain.clone.return_value = None

            fetched = fetch_repo(name="hash-test", url="https://github.com/x/y.git", local_path=local, branch="main")
            assert fetched.commit_hash == "abc123def456"
