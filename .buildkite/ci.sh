#!/usr/bin/env bash
set -euo pipefail

stage=${1:?stage is required}
mkdir -p reports

upload_reports() {
  result=$?
  trap - EXIT
  buildkite-agent artifact upload "reports/*" || result=1
  exit "$result"
}
trap upload_reports EXIT

setup_tools() {
  local digest tools
  digest=$(sha256sum .buildkite/requirements-ci.txt | cut -d ' ' -f 1)
  tools="${XDG_CACHE_HOME:-$HOME/.cache}/more-itertools-ci/$digest"
  mkdir -p "$tools"
  (
    flock 8
    if [ ! -f "$tools/ready" ]; then
      python3.12 -m venv "$tools/venv"
      "$tools/venv/bin/python" -m pip install --quiet --disable-pip-version-check -r .buildkite/requirements-ci.txt
      touch "$tools/ready"
    fi
  ) 8>"$tools/install.lock"
  export PATH="$tools/venv/bin:$PATH"
}

run_stage() {
  if [ "$stage" != report ]; then setup_tools; fi
  case "$stage" in
    prepare)
      python --version
      ruff --version
      python -m unittest discover -s .buildkite -p 'test_*.py'
      ;;
    lint)
      ruff check more_itertools tests .buildkite
      ;;
    format)
      ruff format --check more_itertools tests .buildkite
      ;;
    types)
      python -m mypy.stubtest more_itertools.more more_itertools.recipes
      ;;
    secrets)
      detect-secrets scan --all-files more_itertools > reports/secrets.json
      python -c 'import json; data = json.load(open("reports/secrets.json")); count = sum(map(len, data["results"].values())); print(f"Source secret scan: {count} findings"); raise SystemExit(bool(count))'
      ;;
    iterators|recipes)
      module=tests.test_more
      if [ "$stage" = recipes ]; then module=tests.test_recipes; fi
      COVERAGE_CORE=sysmon coverage run --source=more_itertools -m unittest --failfast "$module"
      coverage report > "reports/coverage-$stage.txt"
      cat "reports/coverage-$stage.txt"
      ;;
    wheel|sdist)
      python -m build --no-isolation "--$stage"
      buildkite-agent artifact upload "dist/*"
      ;;
    install)
      buildkite-agent artifact download 'dist/*.whl' . --step wheel
      python3.12 -m venv .smoke
      .smoke/bin/python -m pip install --no-index --no-deps dist/*.whl
      .smoke/bin/python -I .buildkite/smoke.py
      ;;
    metadata)
      buildkite-agent artifact download 'dist/*.whl' . --step wheel
      buildkite-agent artifact download 'dist/*.tar.gz' . --step sdist
      python -m twine check --strict dist/*
      sha256sum dist/* > reports/checksums.txt
      wc -c dist/* > reports/package-sizes.txt
      cat reports/checksums.txt reports/package-sizes.txt
      ;;
    report)
      python3.12 .buildkite/report.py
      ;;
    *)
      echo "Unknown CI stage: $stage" >&2
      return 1
      ;;
  esac
}

run_stage 2>&1 | tee "reports/$stage.txt"
