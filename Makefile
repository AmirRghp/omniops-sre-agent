.PHONY: setup lint format typecheck test check-all

VENV = .venv
BIN = $(VENV)/bin
ifeq ($(OS),Windows_NT)
    BIN = $(VENV)/Scripts
endif

setup:
	python -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

lint:
	$(BIN)/ruff check src tests evals

format:
	$(BIN)/ruff format src tests evals

typecheck:
	$(BIN)/mypy src

test:
	$(BIN)/pytest -v

check-all: lint typecheck test
