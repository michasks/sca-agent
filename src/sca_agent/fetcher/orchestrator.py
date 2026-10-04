"""Orchestrator: fetch-scan-parse-write pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_scan(
    config_path: str | Path,
    output_dir: str | Path = "scans",
) -> dict[str, Any]:
    """Run the full fetch-scan-parse-write pipeline for all configured repos.

    Parameters
    ----------
    config_path : str or Path
        Path to ``scanner_config.yaml``.
    output_dir : str or Path
        Directory where timestamped result JSON files are written.

    Returns
    -------
    dict
        Summary statistics of the scan run.
    """
    # Import here so the main entry point can remain lightweight
    from sca_agent.fetcher.config import load_scanner_config
    from sca_agent.scanner.owasp_scanner import scan_repository, ScanFailedError
    from sca_agent.fetcher.parser import parse_scanner_output
    from sca_agent.fetcher.repo_fetcher import GitCloneError

    cfg = load_scanner_config(config_path)
    output_dir = Path(output_path := str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting scan run for %d repositories", len(cfg.repositories))

    repositories: dict[str, dict[str, Any]] = {}
    successful = 0
    failed = 0

    for repo in cfg.repositories:
        try:
            # Step 1: Fetch / update
            fetched = _fetch(repo.name, repo.url, repo.local_path, repo.branch)

            # Step 2: Scan
            scan_result = _scan(repo.name, repo.local_path, str(output_dir))

            # Step 3: Parse
            if scan_result.returncode == 0:
                parsed = parse_scanner_output(
                    name=repo.name,
                    url=repo.url,
                    branch=repo.branch,
                    commit_hash=fetched.commit_hash,
                    raw_json=scan_result.raw_output,
                    scan_status="success",
                )
            else:
                parsed = parse_scanner_output(
                    name=repo.name,
                    url=repo.url,
                    branch=repo.branch,
                    commit_hash=fetched.commit_hash,
                    raw_json="",
                    scan_status="failed",
                    error_message=scan_result.stderr or f"Exit code {scan_result.returncode}",
                )

            repositories[repo.name] = json.loads(parsed.model_dump_json())

            if parsed.scan_status == "success":
                successful += 1
                logger.info("[%-20s] Done (%d vulnerabilities)", repo.name, len(parsed.vulnerabilities))
            else:
                failed += 1
                logger.warning("[%-20s] Scan failed: %s", repo.name, parsed.error_message)

        except GitCloneError as exc:
            failed += 1
            logger.error("[%-20s] Clone/Update failed: %s", repo.name, exc)
            repositories[repo.name] = {
                "url": repo.url,
                "branch": repo.branch,
                "last_commit": None,
                "vulnerabilities": [],
                "scan_status": "failed",
                "error_message": str(exc),
            }

        except ScanFailedError as exc:
            failed += 1
            logger.error("[%-20s] Scanner error: %s", repo.name, exc)
            repositories[repo.name] = {
                "url": repo.url,
                "branch": repo.branch,
                "last_commit": None,
                "vulnerabilities": [],
                "scan_status": "failed",
                "error_message": str(exc),
            }

    # Write results
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{ts}.json"
    summary = {
        "scan_metadata": {
            "timestamp": ts,
            "total_repos": len(cfg.repositories),
            "successful": successful,
            "failed": failed,
        },
        "repositories": repositories,
    }
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Results written to %s", report_path)

    return {"total": len(cfg.repositories), "successful": successful, "failed": failed}


# ---- internal helpers ---------------------------------------------------------


def _fetch(name: str, url: str, local_path: str, branch: str):
    """Fetch repository (clone or update)."""
    from sca_agent.fetcher.repo_fetcher import fetch_repo

    return fetch_repo(name=name, url=url, local_path=local_path, branch=branch)


def _scan(name: str, local_path: str, output_dir: str):
    """Run OWASP Dependency Check."""
    from sca_agent.scanner.owasp_scanner import scan_repository

    return scan_repository(name=name, local_path=local_path, output_dir=output_dir)
