set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

default: check

lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

test:
    uv run pytest -q

fmt:
    uv run ruff format .
    uv run ruff check --fix .

check: lint test
