default:
    @just --list

# Full fast gate — pre-commit and CI both invoke this (config/programming-languages/README.md)
ci: lint typecheck test audit

install:
    uv sync
    pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg --hook-type post-commit

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uvx pyright

test:
    uv run pytest

audit:
    uvx pip-audit

run:
    uv run python -m {{`basename $PWD`}}

build:
    uv build

clean:
    rm -rf dist build .pytest_cache .ruff_cache .mypy_cache .pyright htmlcov
    bash scripts/reap-stale-branches.sh
