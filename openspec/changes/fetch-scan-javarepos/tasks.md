# Tasks

## 1. Project setup & config

- [ ] 1.1 Add `pyyaml` to `pyproject.toml` dependencies and verify `uv lock` succeeds
- [ ] 1.2 Create `src/scanner/__init__.py`, `src/scanner/models.py` (dataclasses for Vulnerability, RepositoryScan) and verify imports work via `python -c "from src.scanner.models import RepositoryScan"`
- [ ] 1.3 Create sample `scanner_config.yaml` with 2 example repos (one with override schedule, one without) and verify it parses into typed dataclasses without errors

## 2. Repo fetcher module

- [ ] 2.1 Implement `RepoFetcher.fetch_repo()` method that checks if `.git` exists at `local_path` — if not, runs `git clone --branch <branch>`; if yes, runs `git fetch origin && git checkout <branch>` and verify both code paths in unit tests using `unittest.mock` on subprocess calls
- [ ] 2.2 Add integrity check: after checkout, call `git rev-parse HEAD` to get commit hash, return it alongside repo name and URL
- [ ] 2.3 Verify first-time clone fails gracefully with clear error message when URL is invalid (`GitCloneError` exception with stderr captured)

## 3. OWASP Dependency Check integration

- [ ] 3.1 Implement `OwaspScanner.scan_repository()` that executes `dependency-check --scan <repo_path> --format JSON --out <temp_dir>/report.json` via `subprocess.run(capture_output=True)` and verify success path returns exit code 0 + report path
- [ ] 3.2 Add JVM memory configuration: read `DC_MAX_HEAP` env var (default `-Xmx2g`) and pass it as an argument to DC subprocess; verify with mock that correct args are constructed
- [ ] 3.3 Handle non-zero exit codes by raising `ScanFailedError` with stderr content included; verify test case covers OOM scenario (exit code != 0)

## 4. Parser & normalization

- [ ] 4.1 Read the latest DC JSON output schema (run `dependency-check --format JSON` against a real project) and implement parser in `src/scanner/parser.py` that maps `boms.vuln.software[]` → `SoftwareRef` models
- [ ] 4.2 Build flat list of `(repo_name, cve_id, severity, dep_name, dep_version, vulnerable_range)` tuples from DC JSON; verify output contains correct CVE count matching input
- [ ] 4.3 Wrap results in `RepositoryScan(repo_name, vulnerabilities, scan_status)` model instances; verify `model.model_dump_json()` produces valid JSON matching the spec scenarios

## 5. Result storage & orchestration

- [ ] 5.1 Implement orchestrator function `run_scan(config_path)` that iterates over all repos in config, calls fetcher + scanner + parser per-repo, collects results, writes single `scans/<timestamp>.json` file grouped by repository
- [ ] 5.2 Add basic logging: INFO for completed scans, WARNING for partial failures, ERROR for unrecoverable errors; verify logs contain repo name and status
- [ ] 5.3 End-to-end test: run `run_scan()` against a real public Java repo (e.g., `https://github.com/apache/commons-lang`) — verify output JSON contains CVEs from commons-lang dependencies
