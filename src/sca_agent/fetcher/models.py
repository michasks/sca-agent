"""Pydantic models for SCA scan results."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SoftwareRef(BaseModel):
    """Reference to a piece of software (dependency) in the dependency tree."""

    ref_id: str = Field(description="Internal reference ID from the scanner report")
    name: str = Field(description="Software / group-ID + artifact-name, e.g. org.springframework:spring-core")
    version: str = Field(description="Affected library version")


class Vulnerability(BaseModel):
    """Represents a single CVE found in a dependency."""

    cve_id: str = Field(description="CVE identifier, e.g. CVE-2025-2293")
    severity: str = Field(description="Severity level: CRITICAL, HIGH, MEDIUM, LOW, INFO")
    description: Optional[str] = Field(default=None, description="Human-readable vulnerability description")
    vulnerable_software: list[SoftwareRef] = Field(
        default_factory=list,
        description="Dependencies directly affected by this CVE",
    )

    def __hash__(self) -> int:
        return hash(self.cve_id)


class RepositoryScan(BaseModel):
    """Aggregated scan result for a single repository."""

    repo_name: str = Field(description="Name / key of the repository (user/project)")
    repo_url: str = Field(description="Git URL of the repository")
    branch: str = Field(description="Branch or tag that was scanned")
    last_commit: Optional[str] = Field(default=None, description="Commit SHA at time of scan")
    scan_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the scan was performed",
    )
    vulnerabilities: list[Vulnerability] = Field(
        default_factory=list,
        description="List of unique vulnerabilities across all dependencies",
    )
    scan_status: str = Field(
        default="success",
        description="success | failed",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details when scan_status is 'failed'",
    )
