# Design

## Context

Проект sca-agent находится на ранней стадии: есть базовая структура Python-пакета с конфигурацией для GigaChat (через pydantic-settings), PostgreSQL настроен через docker-compose, но модуль SCA-сканирования отсутствует полностью. Нужно реализовать первый slice — fetch и scan — который станет фундаментом для AI-обоснования уязвимостей.

## Goals

- Загрузка кода из Git по YAML-конфигурации (clone + update)
- Вызов OWASP Dependency Check CLI как subprocess против локальной копии репозитория
- Парсинг DC JSON-вывода в типизированные Python dataclasses
- Сохранение нормализованных результатов в JSON на диск
- Базовая логирование всех этапов (fetch, scan, parse, write)

## Decisions

### Decision 1: Использовать subprocess для запуска OWASP DC CLI

OWASP Dependency Check работает как отдельное JVM-приложение. Самый простой способ интегрировать его из Python — вызвать через `subprocess.run()`. Это даёт полный контроль над параметрами сканера и не требует писать Java/CLI binding'и.

```python
# Pseudocode вызова
result = subprocess.run(
    [
        "dependency-check",
        "--project", repo_name,
        "--scan", repo_local_path,
        "--out", f"scans/{repo_name}_dc_report.json",
        "--format", "JSON"
    ],
    capture_output=True,
    text=True
)
```

**Alternatives considered:**
- Docker-контейнер DC: усложняет setup на VM (нужен Docker daemon), subprocess проще для MVP
- Python API wrapper (`pip install dependency-check`): обёртки часто отстают от upstream'а, лучше использовать стабильный CLI

### Decision 2: Pydantic Dataclasses для модели результатов

Уже используем `pydantic` + `pydantic-settings` в проекте для конфигурации. Логично расширить его на модели данных сканирования:

```python
# Модели будут структурой так:
class Vulnerability(BaseModel):
    cve_id: str
    severity: str          # CRITICAL, HIGH, MEDIUM, LOW, INFO
    description: Optional[str]
    vulnerable_software: list[SoftwareRef]

class SoftwareRef(BaseModel):
    ref_id: str            # boms.vuln.json.software[].refId
    name: str
    version: str
    vulnerable_versions: str  # версия из DC JSON

class RepositoryScan(BaseModel):
    repo_name: str
    repo_url: str
    branch: str
    scan_timestamp: datetime
    vulnerabilities: list[Vulnerability]
    scan_status: str       # success | failed
    error_message: Optional[str]
```

Pydantic обеспечивает:
- Валидацию при парсинге DC JSON
- JSON serialization без extra work
- Типизацию для downstream consumers (LLM agent)

**Alternatives considered:**
- `dataclasses`: нет валидации, нужно писать кастомный JSON-parsing
- Raw dicts: нет type safety, сложно поддерживать

### Decision 3: Одномерная JSON-структура для хранения результатов

Результаты пишутся в плоскую JSON-структуру с группировкой по репозиторию — просто и читаемо для следующего slice (LLM agent):

```json
{
  "scan_metadata": {
    "timestamp": "2026-09-20T10:00:00Z",
    "scanner_version": "12.1.0",
    "total_repos": 3,
    "successful": 3
  },
  "repositories": {
    "my-java-app": {
      "url": "https://github.com/user/my-java-app.git",
      "branch": "main",
      "last_commit": "abc123def",
      "vulnerabilities": [...],
      "scan_status": "success"
    }
  }
}
```

Это формат, который LLM-агент сможет легко распарсить и проанализировать — не нужно сложных SQL-запросов или API-вызовов.

**Alternatives considered:**
- PostgreSQL сразу: излишне для MVP, следующий slice может сам решить, писать ли в БД
- CSV: не поддерживает вложенную структуру зависимостей

### Decision 4: Config-driven discovery вместо hard-coded репозиториев

Список репозиториев хранится в `scanner_config.yaml`, читаемом при старте приложения:

```yaml
global:
  schedule_hours: 24
  jdk_home: "/usr/lib/jvm/java-17-openjdk"  # где установлен JDK

repositories:
  - name: "my-java-app"
    url: "https://github.com/user/my-java-app.git"
    branch: "main"
    local_path: "/data/repos/my-java-app"
    schedule_hours: 12  # optional override

  - name: "legacy-service"
    url: "https://github.com/user/legacy-service.git"
    tag: "v2.3.1"
    local_path: "/data/repos/legacy-service"
```

Этот подход позволяет добавлять новые репозитории без изменений в коде.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| JDK на VM может быть занят другой задачей (другой JVM-процесс) | Использовать изолированную переменную окружения `JAVA_HOME`; проверять доступность при старте |
| OWASP DC может занять много RAM (JVM heap 2-4GB) | Настроить `-Xmx` через env var `DC_MAX_HEAP` или `dependency-check --data` для ограничения памяти; alert если OOM |
| Клонирование больших репозиториев (>500MB) занимает время | Использовать `--depth 1` для fast clone; показать progress-логи |
| OWASP DC обновляет базу periodically (~hourly) — scan может дать разные результаты при каждом запуске | Фиксировать версию базы DC в metadata; фиксировать scan timestamp для дедупликации |
| `git checkout` может конфликтовать с незакоммиченными изменениями в рабочей директории | Проверять чистоту `git status` перед checkout; делать `--force` только если config разрешает |
| JSON результат большой (сотни KB — MB) — нагрузка на disk | Ограничить число сохраняемых файлов (retention policy: keep last N days); архивировать старые |

## Migration Plan

Этот slice — первый шаг, поэтому миграции нет. Он создаёт новую функциональность поверх существующего минимального проекта.

После внедрения этого slice архитектура будет выглядеть так:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Repo Fetcher │───>│   Scanner    │───>│  Parser      │
│              │    │              │    │              │
│ - Clone/Update│   │ Subprocess   │───>│- Normalize   │
│ - Config     │    │ - OWASP DC   │    │- Write JSON  │
└──────────────┘    └──────────────┘    └──────────────┘
                                          ↓
                                    scans/results.json
                                    (готово для LLM slice)
```
