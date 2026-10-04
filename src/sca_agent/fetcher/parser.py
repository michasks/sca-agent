"""Parse OWASP Dependency Check JSON output into typed models."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sca_agent.fetcher.models import RepositoryScan, SoftwareRef, Vulnerability

logger = logging.getLogger(__name__)


def parse_scanner_output(
    name: str,
    url: str,
    branch: str,
    commit_hash: str,
    raw_json: str,
    scan_status: str = "success",
    error_message: str | None = None,
) -> RepositoryScan:
    """Convert Dependency Check raw JSON into a ``RepositoryScan`` model.

    Parameters
    ----------
    name : str
        Repository display name.
    url : str
        Git URL.
    branch : str
        Branch or tag that was scanned.
    commit_hash : str
        Commit SHA at time of scan.
    raw_json : str
        The stdout returned by *dependency-check --format JSON*.
    scan_status : str
        ``"success"`` or ``"failed"``.
    error_message : str | None
        Optional error details when *scan_status* is ``"failed"``.

    Returns
    -------
    RepositoryScan
        Containing deduplicated vulnerabilities keyed by CVE ID.
    """
    if scan_status != "success":
        logger.warning("[%-20s] Skipping parse due to scan failure: %s", name, error_message)
        return RepositoryScan(
            repo_name=name,
            repo_url=url,
            branch=branch,
            last_commit=commit_hash,
            scan_timestamp=datetime.now(timezone.utc),
            vulnerabilities=[],
            scan_status="failed",
            error_message=error_message,
        )

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("[%-20s] Invalid JSON from scanner: %s", name, exc)
        return RepositoryScan(
            repo_name=name,
            repo_url=url,
            branch=branch,
            last_commit=commit_hash,
            scan_timestamp=datetime.now(timezone.utc),
            vulnerabilities=[],
            scan_status="failed",
            error_message=f"Invalid JSON output: {exc}",
        )

    vulns_by_id: dict[str, Vulnerability] = {}
    _walk_software(data.get("boms", {}).get("vuln", {}).get("software", []), vulns_by_id)

    return RepositoryScan(
        repo_name=name,
        repo_url=url,
        branch=branch,
        last_commit=commit_hash,
        scan_timestamp=datetime.now(timezone.utc),
        vulnerabilities=list(vulns_by_id.values()),
        scan_status="success",
        error_message=None,
    )


# ---- internal helpers ---------------------------------------------------------


def _walk_software(software_list: list[dict[str, Any]], vulns_by_id: dict[str, Vulnerability]) -> None:
    """Recursively walk software nodes and extract vulnerability info."""
    for sw in software_list:
        ref_id = sw.get("refId")
        name = sw.get("name", "")
        version = sw.get("version", "")

        for v in sw.get("vulnerabilities", []):
            cve_id = v.get("id")
            if not cve_id:
                continue

            severity = _normalize_severity(v.get("severity", "").upper())

            # Build or update the Vulnerability entry
            if cve_id not in vulns_by_id:
                vulns_by_id[cve_id] = Vulnerability(
                    cve_id=cve_id,
                    severity=severity,
                    description=v.get("description"),
                    vulnerable_software=[],
                )

            vulns_by_id[cve_id].vulnerable_software.append(
                SoftwareRef(
                    ref_id=ref_id or "",
                    name=name,
                    version=version,
                )
            )


def _normalize_severity(severity: str) -> str:
    """Normalize to a standard severity label."""
    mapping = {
        "CRITICAL": "CRITICAL",
        "HIGH": "HIGH",
        "MEDIUM": "MEDIUM",
        "MODERATE": "MEDIUM",       # NVD sometimes uses MODERATE
        "LOW": "LOW",
        "INFO": "INFO",
        "INFORMATIONAL": "INFO",   # alternative spelling
        "UNKNOWN": "INFO",         # fallback
    }
    return mapping.get(severity, "UNKNOWN")
