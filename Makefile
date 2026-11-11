# BankMonitor — developer commands. Run `make` to see the list.
# Lint and tests run inside the `tests` container, so the host needs only Docker and make.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE     := docker compose
COMPOSE_DEV := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
TESTS_RUN   := $(COMPOSE) --profile test run --rm
TESTS_IMAGE := bankmon-tests

.PHONY: help env up up-dev down clean ps logs lint fmt unit e2e check-ports tests-image

help: ## Показати перелік команд
	@echo "BankMonitor — команди:"
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-z0-9-]*:.*## / { printf "  make %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

env: ## Створити .env з .env.example, якщо його ще немає
	@if [ ! -f .env ]; then cp .env.example .env && echo "Створено .env з .env.example"; fi

up: env ## Зібрати й запустити стенд (назовні відкрито лише gateway)
	$(COMPOSE) up -d --build --wait

up-dev: env ## Те саме, плюс порти сервісів на 127.0.0.1 для налагодження
	$(COMPOSE_DEV) up -d --build --wait

down: env ## Зупинити стенд, дані зберегти
	$(COMPOSE) --profile test down --remove-orphans

clean: env ## Зупинити стенд і видалити всі дані (томи)
	$(COMPOSE) --profile test down --volumes --remove-orphans

ps: env ## Стан контейнерів
	$(COMPOSE) ps

logs: env ## Останні логи: make logs S=<сервіс> (без S — усіх сервісів)
	$(COMPOSE) logs --tail=200 $(S)

tests-image: env
	@$(COMPOSE) --profile test build --quiet tests

lint: tests-image ## Перевірити код лінтером і форматером (ruff)
	$(TESTS_RUN) --no-deps tests sh -c 'ruff check --no-cache . && ruff format --check --no-cache .'

fmt: tests-image ## Відформатувати код (ruff format)
	docker run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR):/repo" -w /repo $(TESTS_IMAGE) ruff format --no-cache .

unit: tests-image ## Юніт-тести (стенд не потрібен)
	$(TESTS_RUN) --no-deps tests pytest tests/unit -q

e2e: tests-image ## Наскрізні тести на живому стенді: make e2e [K=<вираз>]
	$(TESTS_RUN) tests pytest tests/e2e -q $(if $(K),-k "$(K)")

check-ports: ## Перевірити, що назовні опубліковано лише gateway
	@scripts/check_ports.sh
