# Spec Delta

## Purpose

Автоматическое получение кодовой базы Java-репозиториев, сканирование их на уязвимые зависимости через OWASP Dependency Check и сохранение результатов в нормализованном формате для последующего анализа LLM-агентом.

## ADDED Requirements

### Requirement: Repository configuration

The system SHALL read a YAML configuration file listing Java repositories to scan, including git URL, target branch/tag, and local working directory path. Each entry MUST support optional per-repository schedule override.

#### Scenario: Valid configuration loaded from file

- **WHEN** `scanner_config.yaml` contains a list of repository entries with `url`, `branch`, and `local_path` fields
- **THEN** the system loads all entries without raising parse errors

#### Scenario: Missing required field rejected

- **WHEN** a repository entry is missing the `url` or `local_path` field
- **THEN** the system raises a validation error with field name and stops scanning

#### Scenario: Default schedule applied when not specified

- **WHEN** a repository entry omits the `schedule` field
- **THEN** the system uses the global default interval from the config (e.g., every 24 hours)

### Requirement: Repository cloning and updating

The system SHALL clone a git repository into its designated local path if it does not exist, and perform a fast update (`git fetch` + `git checkout`) if it already exists. The system MUST track the last committed hash per repository to detect changes.

#### Scenario: First-time clone succeeds

- **WHEN** the local path does not contain a `.git` directory
- **THEN** the system performs a full `git clone --branch <branch>` and verifies the working tree contains at least one `pom.xml` or `build.gradle` file

#### Scenario: Subsequent update reuses existing clone

- **WHEN** the local path already contains a cloned repository
- **THEN** the system executes `git fetch origin` and checks out the configured branch without deleting or recreating the working directory

#### Scenario: Stale scan detected via hash change

- **WHEN** the latest commit SHA differs from the previously recorded hash for a repository
- **THEN** the system marks the repository as requiring a rescan and updates its hash record

### Requirement: OWASP Dependency Check scan execution

The system SHALL invoke OWASP Dependency Check CLI against each repository and produce structured JSON output. The system MUST configure DC to analyze Maven (`pom.xml`) and Gradle (`build.gradle`) dependency trees recursively for transitive dependencies.

#### Scenario: Scan completes successfully

- **WHEN** Dependency Check CLI exits with code 0
- **THEN** the system reads the generated JSON report and proceeds to parsing

#### Scenario: Scan failure is reported

- **WHEN** Dependency Check CLI exits with non-zero code or produces no output
- **THEN** the system logs an error, includes the stderr output, and records the repository as `scan_status: failed`

#### Scenario: Transitive dependencies included

- **WHEN** a project has deep transitive dependency chains (e.g., spring-boot → spring-core → jackson-databind)
- **THEN** the scanned report contains vulnerability data for all levels of the dependency graph

### Requirement: Result normalization and storage

The system SHALL normalize the Dependency Check JSON output into a flat Python data structure where each row represents a single `(repository, CVE, dependency)` triple. The normalized results SHALL be written to a JSON file grouped by repository.

#### Scenario: Normalized output contains expected fields

- **WHEN** a scan finds 3 CVEs across 5 dependencies
- **THEN** the normalized output contains exactly 3 rows, each with `repo_name`, `cve_id`, `severity`, `dependency_name`, `dependency_version`, `vulnerable_range`

#### Scenario: Output file written atomically

- **WHEN** all scans complete (success or failure)
- **THEN** the system writes a single JSON file `scans/<timestamp>.json` containing results from all repositories

#### Scenario: Results are queryable by date and repo

- **WHEN** results are stored in `scans/<timestamp>.json` grouped by repository
- **THEN** any consumer (LLM agent, report generator) can retrieve results for a specific repository by parsing the JSON structure
