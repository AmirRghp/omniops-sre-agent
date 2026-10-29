.PHONY: setup lint format typecheck test eval eval-dry-run eval-compare run-api run-ui seed docker-up docker-down docker-ps check-all

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
	$(BIN)/ruff check src tests evals app.py main.py

format:
	$(BIN)/ruff format src tests evals app.py main.py

typecheck:
	$(BIN)/mypy src evals app.py main.py

test:
	$(BIN)/pytest -v

eval: eval-dry-run

eval-dry-run:
	$(BIN)/python -m evals.run_agent_benchmark --dry-run

eval-compare:
	$(BIN)/python -m evals.run_agent_benchmark --compare evals/results/eval_1_5b.json evals/results/eval_7b.json

run-api:
	$(BIN)/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

run-ui:
	$(BIN)/chainlit run app.py -w

seed:
	$(BIN)/python -m src.db.seed

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-ps:
	docker compose ps

check-all: lint typecheck test eval-dry-run
