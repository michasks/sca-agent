"""YAML configuration loader for the SCA scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError


class RepositoryConfig(BaseModel):
    """Configuration for a single repository to scan."""

    name: str = Field(description="Display name / key used in results")
    url: str = Field(description="Git URL (HTTPS or SSH)")
    local_path: str = Field(description="Local working directory on the VM")
    branch: Optional[str] = Field(default=None, description="Branch or tag to use")
    schedule_hours: int = Field(
        default=24,
        ge=1,
        description="How often to refresh/scan (hours). Falls back to global default.",
    )


class GlobalConfig(BaseModel):
    """Global scanner configuration."""

    jdk_home: Optional[str] = Field(default=None, description="Path to JDK home directory")
    schedule_hours: int = Field(
        default=24,
        ge=1,
        description="Default interval for all repositories.",
    )


class ScannerConfig(BaseModel):
    """Top-level scanner configuration."""

    global_cfg: GlobalConfig
    repositories: list[RepositoryConfig]

    def get_repo(self, name: str) -> Optional[RepositoryConfig]:
        """Return the repo with the given name, or None."""
        for r in self.repositories:
            if r.name == name:
                return r
        return None


def load_scanner_config(path: str | Path) -> ScannerConfig:
    """Load and validate a scanner_config.yaml file.

    Raises ``ValidationError`` when required fields are missing or types don't match.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValidationError("scanner_config.yaml must be a YAML mapping", errors=[{}])

    # Validate individual repos early so we surface which field is missing
    for entry in raw.get("repositories", []):
        if not isinstance(entry, dict):
            continue
        missing = [f for f in ("name", "url", "local_path") if f not in entry]
        if missing:
            raise ValidationError(
                f"Repository entry missing fields: {missing!r}",
                errors=[{"loc": ("repositories", None), "msg": f"Missing {missing}"}],
            )

    global_cfg = GlobalConfig(**raw.get("global_cfg", {}))
    repos = []
    for entry in raw.get("repositories", []):
        repo_dict = {k: v for k, v in entry.items() if v is not None}
        # schedule_hours defaults via pydantic field; skip explicit None so default applies
        repos.append(RepositoryConfig(**repo_dict))
    return ScannerConfig(global_cfg=global_cfg, repositories=repos)
