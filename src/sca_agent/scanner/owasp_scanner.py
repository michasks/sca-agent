"""OWASP Dependency Check CLI integration."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    """Raw scan output from Dependency Check."""

    repo_name: str
    local_path: str
    report_json_path: str       # path to the DC JSON report on disk
    raw_output: str             # full stdout (DC JSON)
    returncode: int
    stderr: str                 # stderr captured from the process


class ScanFailedError(Exception):
    """Raised when OWASP Dependency Check returns a non-zero exit code."""

    def __init__(self, message: str, stderr: str = "") -> None:
        self.stderr = stderr
        super().__init__(message)


def scan_repository(
    name: str,
    local_path: str | Path,
    output_dir: str | Path = "scans",
    timeout_seconds: int = 1800,
) -> ScanResult:
    """Run OWASP Dependency Check against a repository.

    Parameters
    ----------
    name : str
        Repository display name (used in log messages and metadata).
    local_path : str or Path
        Local working directory containing pom.xml / build.gradle.
    output_dir : str or Path
        Directory where the DC JSON report is written. Defaults to ``scans/<repo_name>/``
        so that report files never pollute the project tree.
    timeout_seconds : int
        Maximum wall-clock time for the scan. Defaults to 1800 (30 minutes).
        Set via ``DC_SCAN_TIMEOUT`` env var or passed explicitly.

    Returns
    -------
    ScanResult
        With ``returncode == 0`` on success.

    Raises
    ------
    ScanFailedError
        When the dependency-check process exits with a non-zero code, is missing
        from PATH, or times out.
    """
    path = Path(local_path).resolve()
    out_dir = Path(output_dir).resolve() / name
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "dc_report.json"

    # Configure JVM heap via environment variable (DC reads JAVA_OPTS)
    env = dict(os.environ)
    java_heap = f"-Xmx{env.get('DC_MAX_HEAP', '2g')}"
    existing = env.get("JAVA_OPTS", "")
    if "-Xmx" not in existing:
        env["JAVA_OPTS"] = f"{existing} {java_heap}".strip()

    cmd = [
        "dependency-check",
        "--project", name,
        "--scan", str(path),
        "--out", str(report_path),
        "--format", "JSON",
        "--cveValidTimeMaximum", "9999999d",   # don't filter out expired CVEs
    ]

    logger.info("[%-20s] Running OWASP Dependency Check (heap %s)", name, java_heap)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise ScanFailedError(
            "dependency-check command not found — ensure it is installed and on PATH",
            stderr=str(exc),
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ScanFailedError(
            f"Dependency Check timed out after {timeout_seconds}s for {name}",
            stderr=exc.output,
        ) from exc

    returncode = result.returncode

    # Verify the report file was actually created
    if returncode != 0 or not report_path.is_file():
        msg = f"Dependency Check exited with code {returncode} for {name}"
        if not report_path.is_file():
            msg += " — no report file generated (project may lack build descriptors)"
        logger.error("%s\nstderr: %s", msg, result.stderr.strip())
        return ScanResult(
            repo_name=name,
            local_path=str(path),
            report_json_path=str(report_path),
            raw_output=result.stdout.strip(),
            returncode=returncode,
            stderr=result.stderr,
        )

    report_text = report_path.read_text(encoding="utf-8")
    logger.info("[%-20s] Scan complete (%d bytes written to %s)", name, len(report_text), report_path)
    return ScanResult(
        repo_name=name,
        local_path=str(path),
        report_json_path=str(report_path),
        raw_output=report_text,
        returncode=0,
        stderr="",
    )
