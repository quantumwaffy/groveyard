#!make

.PHONY: help \
		install \
		lint \
		lint-fix \
		format \
		format-check \
		typecheck \
		test \
		coverage \
		check \
		docs \
		docs-build \
		build \
		clean

# --- Tooling
UV := uv


help: ## Commands
	@echo "Please use 'make <target>' where <target> is one of:"
	@awk -F ':|##' '/^[a-zA-Z\-_0-9]+:/ && !/^[ \t]*all:/ { printf "\t\033[36m%-16s\033[0m %s\n", $$1, $$3 }' $(MAKEFILE_LIST)


# --- Setup
install: ## Install dev + docs dependency groups
	@$(UV) sync --all-groups


# --- Gates (what CI runs — see CONTRIBUTING.md)
lint: ## Lint with ruff
	@$(UV) run ruff check .

lint-fix: ## Lint with ruff, applying safe auto-fixes
	@$(UV) run ruff check --fix .

format: ## Format with ruff (rewrites files, including code fences in Markdown)
	@$(UV) run ruff format .

format-check: ## Check formatting without rewriting files
	@$(UV) run ruff format --check .

typecheck: ## Type check with ty
	@$(UV) run ty check

test: ## Run the test suite (fake transport only, no Pi needed)
	@$(UV) run pytest

coverage: ## Run tests and fail if coverage drops below 85%
	@$(UV) run pytest --cov-fail-under=85

check: lint format-check typecheck test ## Run all four gates, in the order CI runs them


# --- Docs (MkDocs Material + mkdocstrings)
docs: ## Serve the documentation site locally with live reload
	@$(UV) run mkdocs serve

docs-build: ## Build the documentation site, failing on any warning
	@$(UV) run mkdocs build --strict


# --- Packaging
build: ## Build the sdist and wheel into dist/
	@$(UV) build

clean: ## Remove build, cache, and coverage artifacts
	@rm -rf dist build site .coverage coverage.xml .pytest_cache .ruff_cache
	@find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
