#!/usr/bin/env bash
# Mirrors the GitHub runner locally: pinned ruff, no claude binary on PATH,
# a foreign $HOME, and workflow YAML lint.
set -euo pipefail

cd "$(dirname "$0")/.."

uvx ruff@0.15.10 check .
echo "parity: ruff ok"

if command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest -no-color
  echo "parity: actionlint ok"
else
  echo "parity: actionlint SKIPPED (no docker)" >&2
fi

HOME="$(mktemp -d)" uv run --with pytest --python 3.12 python -m pytest -q tests/golden
echo "parity: golden ok"

B="$(mktemp -d)"
for tool in python3 uv git bash sh env perl jq node npx dirname basename sed grep awk cat head tail sort wc tr mktemp mkdir find touch cp mv rm ln ls readlink uname date sleep kill stat nohup; do
  path="$(command -v "$tool" 2>/dev/null || true)"
  if [ -n "$path" ]; then
    ln -s "$path" "$B/$tool"
  fi
done

if PATH="$B" command -v claude >/dev/null 2>&1; then
  echo "parity: no-claude-binary FAILED (claude found on stripped PATH)" >&2
  exit 1
fi

PATH="$B" uv run --with pytest --python 3.12 python -m pytest -q tests
echo "parity: no-claude-binary ok"
