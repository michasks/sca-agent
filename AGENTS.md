# sca-agent — AI-агент для triage SCA-уязвимостей Java-репозиториев

## Зачем нужен проект

У пользователя есть несколько Java-репозиториев, в которых регулярно появляются уязвимые зависимости из-за обновления сторонних библиотек (включая транзитивные). Вручную проверять каждую CVE на применимость к конкретному коду невозможно при масштабе.

**Цель проекта** — автоматизировать полный конвейер от клонирования репозитория до готового обоснования: "эта уязвимость вредит вашему коду / не вредит / требует ручного разбора" с ссылками на конкретные файлы и строки.

Агент построен на Python + LangChain и использует локальную LLM (GigaChat) для принятия решений о применимости уязвимостей.

---

## Архитектура (высокий уровень)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Repo Fetcher │───>│   Scanner    │───>│  Parser      │
│              │    │              │    │              │
│ - Clone/Update│   │ OWASP DC     │───>│ Normalize    │
│ - Config     │    │ CLI          │    │ JSON → models│
└──────────────┘    └──────────────┘    └──────────────┘
                                           ↓
                                    scan_results.json
                                           ↓
                          ┌──────────────────────────────┐
                          │      LLM Agent               │
                          │                              │
                          │  "Эта CVE вредит моему коду? │
                          │   Проверь импорты и usage"   │
                          └──────────────┬───────────────┘
                                         ↓
                                   Обоснование + ссылки на код
```

На текущий момент реализована **первая часть** — `fetch-scan-parse` пайплайн. Модуль LLM-агента находится за рамками этого slice.

---

## Структура проекта

```
sca-agent/
├── src/
│   ├── config/                  # Конфигурация GigaChat (LangChain tools)
│   │   ├── ai_model_config.py   # Pydantic Settings для GigaChat credentials
│   │   └── __init__.py
│   ├── scanner/                 # ← РЕАЛИЗОВАНО: SCA scan pipeline
│   │   ├── __init__.py          # Empty marker
│   │   ├── models.py            # Data models: Vulnerability, SoftwareRef, RepositoryScan
│   │   ├── config.py            # YAML loader: load_scanner_config()
│   │   ├── repo_fetcher.py      # Git clone/update per-repo
│   │   ├── owasp_scanner.py     # Subprocess wrapper for dependency-check CLI
│   │   ├── parser.py            # Parse DC JSON → typed models
│   │   └── orchestrator.py      # Pipeline: run_scan(config_path)
│   └── __main__.py              # Entry point: list GigaChat models
├── tests/scanner/               # ← РЕАЛИЗОВАНО: unit-тесты
│   ├── test_models.py           # Models serialization
│   ├── test_config.py           # YAML config loading & validation
│   ├── test_repo_fetcher.py     # Clone/update paths & error handling
│   ├── test_owasp_scanner.py    # Scanner subprocess calls & errors
│   ├── test_parser.py           # JSON parsing & deduplication
│   └── test_orchestrator.py     # Full pipeline integration (mocked)
├── openspec/                    # OpenSpec change management
│   ├── changes/fetch-scan-javarepos/
│   │   ├── proposal.md
│   │   ├── design.md
│   │   ├── specs/repo-scan/spec.md
│   │   └── tasks.md
│   └── ...
├── scanner_config.yaml          # Sample repos configuration
├── pyproject.toml               # uv dependencies
├── Makefile                     # Build/test/run commands
└── README.md                    # User-facing documentation
```

---

## Реализованные компоненты

### 1. `src/scanner/models.py` — Типизированные модели данных

Pydantic models для представления результатов сканирования. Все модели сериализуются через `.model_dump_json()` в формат, совместимый с downstream consumers (LLM-агент, отчётчик).

| Модель | Описание |
|--------|----------|
| `Vulnerability` | Одна CVE: id, severity, description, список affected libs |
| `SoftwareRef` | Ссылка на библиотеку (refId, name, version) |
| `RepositoryScan` | Агрегат по одному репозиторию: метаданные + список уникальных CVE |

**Почему Pydantic:** валидация при парсинге, типизация для IDE/auto-complete, нативная JSON-сериализация без boilerplate.

### 2. `src/scanner/config.py` — Загрузка конфигурации

Функция `load_scanner_config(path)` читает YAML-файл (`scanner_config.yaml`) и возвращает валидированную модель `ScannerConfig`.

YAML-формат:
```yaml
global_cfg:
  schedule_hours: 24
  jdk_home: ""                    # опционально

repositories:
  - name: "my-app"                # обязательные поля
    url: "https://github.com/x/y.git"
    branch: "main"
    local_path: "/data/repos/my-app"
    schedule_hours: 12            # опциональный override
```

Валидирует наличие `name`, `url`, `local_path`. Если поле отсутствует — поднимает `ValidationError`. Каждый репозиторий может иметь свой `schedule_hours`; если опущен — берётся глобальный default.

### 3. `src/scanner/repo_fetcher.py` — Клонирование и обновление репозиториев

Функция `fetch_repo(name, url, local_path, branch)` управляет жизненным циклом рабочей копии репозитория:

| Путь | Поведение |
|------|-----------|
| **Первый запуск** (`.git` отсутствует) | `git clone --depth 1 --branch <branch>` → проверка наличия `pom.xml` или `build.gradle` |
| **Обновление** (`.git` существует) | `git fetch origin` → `git checkout -f <branch>` → `git fetch --deepen 50` (для полноты транзитивных зависимостей) |

Возвращает `FetchedRepo` dataclass с полями: `name`, `url`, `branch`, `local_path`, `commit_hash` (текущий SHA HEAD).

**Ошибка:** `GitCloneError` с полем `stderr` — поднимается при любой неудаче git-команды, проходит дальше к оркестратору.

### 4. `src/scanner/owasp_scanner.py` — Интеграция OWASP Dependency Check

Функция `scan_repository(name, local_path)` оборачивает вызов CLI `dependency-check` через `subprocess.run()`.

Команда:
```bash
dependency-check \
  --project <repo_name> \
  --scan <local_path> \
  --out dc_report.json \
  --format JSON \
  --cveValidTimeMaximum 9999999d
```

**JVM heap:** читается из env var `DC_MAX_HEAP` (default `-Xmx2g`). Можно переопределить аргументом `max_heap=""`.

**Результат:** `ScanResult` dataclass с полями `repo_name`, `local_path`, `report_json_path`, `raw_output` (stdout), `returncode`, `stderr`.

**Ошибка:** `ScanFailedError` — поднимается при `FileNotFoundError` (CLI нет на PATH), timeout (>30 min), non-zero exit code.

### 5. `src/scanner/parser.py` — Парсинг вывода Dependency Check

Функция `parse_scanner_output(...)` превращает сырой JSON Dependency Check в `RepositoryScan` модель:

1. Проверяет статус сканирования; при `"failed"` → сразу пустой `RepositoryScan`
2. Десериализует JSON → dict
3. Рекурсивно обходит `boms.vuln.software[]` → извлекает `id`, `severity`, `description` для каждой vulnerability
4. **Дедупликация** по CVE ID: одна и та же CVE в разных lib становится одним объектом `Vulnerability` с массивом affected `SoftwareRef`
5. Нормализует severity: `MODERATE` → `MEDIUM`, `INFORMATIONAL` → `INFO`

### 6. `src/scanner/orchestrator.py` — Оркестратор всего пайплайна

Функция `run_scan(config_path, output_dir="scans")` — точка входа для запуска полного цикла:

```
Для каждого репозитория в конфиге:
  1. _fetch() → FetchedRepo
  2. _scan()  → ScanResult
  3. parse_scanner_output(...) → RepositoryScan
  4. model_dump_json() → dict[r]
Записать scans/<timestamp>.json с metadata + repositories dict
```

Ошибки отдельного репозитория не ломают весь цикл: failed repo записывается с `scan_status: "failed"`, продолжение со следующими.

Возвращает summary: `{"total": N, "successful": N, "failed": N}`.

Логгирует INFO/WARNING/ERROR для каждого этапа с именем репозитория.

### 7. Тесты (`tests/scanner/`)

| Файл | Покрытие |
|------|----------|
| `test_models.py` | Сериилизация Pydantic моделей, валидный JSON-roundtrip |
| `test_config.py` | Чтение YAML, fallback defaults, валидация пропущенных полей |
| `test_repo_fetcher.py` | Mock'нутые clone vs update пути, `GitCloneError` |
| `test_owasp_scanner.py` | Mock'нутые subprocess вызовы, `DC_MAX_HEAP`, `ScanFailedError` |
| `test_parser.py` | Mapping JSON → models, дедупликация CVE, нормализация severity |
| `test_orchestrator.py` | E2E интеграция через mock'и всех подмодулей |

Все тесты работают полностью оффлайн (mockнутые subprocess). E2E с реальным `dependency-check` требует установленного JDK + CLI на VM.

---

## Не реализовано (следующие slices)

| Компонент | Статус | Что нужно |
|-----------|--------|-----------|
| **LLM Agent** | ❌ Не начато | LangChain agent с GigaChat, который читает результаты парсера и проверяет applicability каждой CVE в коде |
| **Code relevance search** | ❌ Не начато | grep/search по кодовой базе для поиска затронутых методов/импортов перед запросом к LLM |
| **Scheduler/cron** | ❌ Не начато | Cron job или periodic loop для запуска `run_scan()` каждые N часов |
| **PostgreSQL storage** | ❌ Не начато | Сохранение результатов в БД вместо/параллельно JSON-файлов |
| **Notifications** | ❌ Не начато | Отправка отчётов (email, Slack, Telegram) с сводкой по критичным уязвимостям |
| **Static code analysis** | ❌ Не начато | AST/call-graph анализ вместо простого grep (пока вне MVP scope) |
