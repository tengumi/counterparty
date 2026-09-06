# Counterparty Workspace — one entry point for the local stack and checks.
# Everything is thin wiring over `docker compose`; see README.md «Локальный запуск».

COMPOSE ?= docker compose
URL     ?= http://localhost:5173
PYSVC    = services/ui_api services/agent services/mcp
PKG      = packages/contracts packages/domain packages/storage

.DEFAULT_GOAL := help

.PHONY: help up down restart reset rebuild logs ps smoke seed open \
        test test-web test-py $(addprefix test-,ui_api agent mcp)

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  App:  $(URL)   (press «Войти в демо» once)"

up: ## Build images if needed and bring the whole stack up (waits for health)
	$(COMPOSE) up -d --build --wait
	@echo "\nReady → $(URL)"

down: ## Stop the stack, keep the database volume
	$(COMPOSE) down

restart: ## Recreate the long-running services without touching data
	$(COMPOSE) up -d --wait ui_api agent mcp web proxy

rebuild: ## Rebuild and restart the app services (web/ui_api/agent/mcp) + refresh the proxy
	$(COMPOSE) up -d --build --wait web ui_api agent mcp
	$(COMPOSE) restart proxy
	@echo "\nReady → $(URL)"

reset: ## Wipe the database volume and bring everything up fresh (re-imports)
	$(COMPOSE) down -v
	$(MAKE) up

logs: ## Follow logs of the service processes
	$(COMPOSE) logs -f ui_api agent mcp web proxy

ps: ## Show container status
	$(COMPOSE) ps

smoke: ## Curl every health endpoint through the host ports
	@for p in "proxy 5173" "ui_api 8000" "agent 8001" "mcp 8002"; do \
	  set -- $$p; \
	  printf '%-8s ' "$$1"; \
	  curl -sf -o /dev/null -w '%{http_code}\n' "http://localhost:$$2/healthz" || echo DOWN; \
	done

seed: ## Create a ready-to-poke demo check and print its URL
	@sh scripts/seed_demo.sh

open: ## Open the app in a browser (macOS)
	@open "$(URL)/checks" 2>/dev/null || xdg-open "$(URL)/checks" 2>/dev/null || echo "$(URL)/checks"

test: test-web test-py ## Run every check (web + all Python services)

test-web: ## Web: lint, typecheck, unit tests, production build
	cd apps/web && npm install --no-audit --no-fund && npm run lint && npm run typecheck && npm test && npm run build

test-py: $(addprefix test-,ui_api agent mcp) ## All Python services: ruff, mypy, pytest

test-ui_api test-agent test-mcp: test-%:
	cd services/$* && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
