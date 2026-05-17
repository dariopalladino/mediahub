.PHONY: install lint typecheck test test-cov clean help

PYTHON ?= python
UV ?= uv

help:
	@echo "Available targets:"
	@echo "  install    Install package + dev deps with uv"
	@echo "  lint       Run ruff linter"
	@echo "  typecheck  Run mypy"
	@echo "  test       Run pytest"
	@echo "  test-cov   Run pytest with coverage report"
	@echo "  clean      Remove __pycache__, .mypy_cache, .pytest_cache"

install:
	$(UV) sync

lint:
	$(UV) run ruff check mediactl/ tests/

typecheck:
	$(UV) run mypy mediactl/

test:
	$(UV) run pytest -q

test-cov:
	$(UV) run pytest -q --cov=mediactl --cov-report=term-missing

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
