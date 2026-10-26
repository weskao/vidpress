SHELL := /bin/bash
.PHONY: help install dev sync run doctor test lint check build publish-private

help:
	@printf '%s\n' 'vidpress commands:' \
	  '  make install     install global CLI with uv tool' \
	  '  make dev         editable global CLI install' \
	  '  make sync        install dev dependencies in .venv' \
	  '  make run         launch interactive wizard' \
	  '  make doctor      check FFmpeg and dependencies' \
	  '  make test        run pytest' \
	  '  make lint        ruff check' \
	  '  make check       lint + tests' \
	  '  make build       build wheel via uv' \
	  '  make publish-private  create/push private repo using gh auth'

install:
	uv tool install --force .

dev:
	uv tool install --force --editable .

sync:
	uv sync --group dev

run:
	uv run vidpress

doctor:
	uv run vidpress doctor

test:
	uv run --group dev pytest -q

lint:
	uv run --group dev ruff check .

check: lint test

build:
	uv build

publish-private:
	@command -v gh >/dev/null || { echo 'Install GitHub CLI: brew install gh'; exit 1; }
	@gh auth status
	@test -d .git || git init -b main
	@git add .
	@git diff --cached --quiet || git commit -m 'feat: initialize vidpress CLI'
	@gh repo create weskao/vidpress --private --source . --remote origin --push
