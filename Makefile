.PHONY: install ci lint fmt typecheck test audit run serve clean

# Full fast gate — pre-commit and CI both invoke this.
ci: lint typecheck test audit

install:
	uv venv --python 3.13 .venv
	uv pip install --python .venv/bin/python -r requirements-dev.txt
	pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg --hook-type post-commit

lint:
	uvx ruff check .
	uvx ruff format --check .
	uvx codespell

fmt:
	uvx ruff check --fix .
	uvx ruff format .

typecheck:
	uvx pyright

test:
	.venv/bin/python -m pytest

audit:
	uvx pip-audit -r requirements.txt

# Print the .ics to stdout (needs an authorized token cache).
run:
	.venv/bin/python app.py

# Serve the Flask app locally — this is what you hit to do the one-time OAuth2
# authorization at http://localhost:5000/oauth2/login
serve:
	.venv/bin/python app.py --serve

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .pyright htmlcov __pycache__ tests/__pycache__
	bash scripts/reap-stale-branches.sh
