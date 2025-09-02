SHELL := /bin/bash
.DEFAULT_GOAL := help

help:  ## Show targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' Makefile | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Prod-like (nginx + streamlit)
	docker compose -f infra_devops/docker/docker-compose.yml up -d

up-dev: ## Frontend HMR + Streamlit
	docker compose -f infra_devops/docker/docker-compose.yml -f infra_devops/docker/docker-compose-dev.yml up -d frontend-dev streamlit

down: ## Stop all
	docker compose -f infra_devops/docker/docker-compose.yml -f infra_devops/docker/docker-compose-dev.yml down -v

logs: ## Tail logs
	docker compose -f infra_devops/docker/docker-compose.yml -f infra_devops/docker/docker-compose-dev.yml logs -f --tail=200

lint: ## Python + markdown + secrets (fast)
	ruff check .
	black --check .
	markdownlint-cli2 **/*.md
	# fast secrets scan (diff only via pre-commit)
	pre-commit run --all-files

fmt: ## Auto-format Python & Markdown
	ruff check --fix .
	black .
	markdownlint-cli2-fix **/*.md || true

test: ## Placeholder for tests
	pytest -q || true

build: ## Build images (all)
	docker compose -f infra_devops/docker/docker-compose.yml build --no-cache
