# Makefile

.PHONY: run dev test shell system-dependencies setup

# Определяем ОС (Linux / macOS)
UNAME_S := $(shell uname -s)


# Удобная обёртка
setup: system-dependencies
	uv sync

## Запуск приложения с переменными окружения
run:
	@uv run --env-file=.env python main.py

generate-models:
	@uv run datamodel-codegen --input specs/dependency-track-api-v1.yaml --output src/sca_agent/models/dependency_track_dto.py --input-file-type openapi