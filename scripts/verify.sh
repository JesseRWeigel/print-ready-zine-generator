#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VERIFY_TMP=$(mktemp -d "${TMPDIR:-/tmp}/media038-verify.XXXXXX")
trap 'rm -rf -- "$VERIFY_TMP"' EXIT

for required in python3 pdflatex mutool git; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "FAIL missing required executable: $required" >&2
    exit 1
  fi
done

UNIT_LOG="$VERIFY_TMP/unit.log"
if ! (cd "$PROJECT_ROOT" && python3 -m unittest discover -s tests -v) >"$UNIT_LOG" 2>&1; then
  cat "$UNIT_LOG" >&2
  exit 1
fi
if ! grep -Fq "Ran 8 tests" "$UNIT_LOG"; then
  cat "$UNIT_LOG" >&2
  echo "FAIL unit test count changed, update the verified status deliberately" >&2
  exit 1
fi
echo "PASS unit: 8 tests"

SADDLE_OUTPUT="$VERIFY_TMP/saddle"
MINI_OUTPUT="$VERIFY_TMP/mini"
if ! (cd "$PROJECT_ROOT" && python3 zinegen.py examples/field-notes.json --output "$SADDLE_OUTPUT" --mode saddle --paper letter) >"$VERIFY_TMP/saddle.log" 2>&1; then
  cat "$VERIFY_TMP/saddle.log" >&2
  exit 1
fi
if ! (cd "$PROJECT_ROOT" && python3 zinegen.py examples/field-notes.json --output "$MINI_OUTPUT" --mode mini --paper letter) >"$VERIFY_TMP/mini.log" 2>&1; then
  cat "$VERIFY_TMP/mini.log" >&2
  exit 1
fi
(cd "$PROJECT_ROOT" && python3 tests/inspect_outputs.py \
  --input examples/field-notes.json \
  --saddle "$SADDLE_OUTPUT" \
  --mini "$MINI_OUTPUT")

python3 - "$PROJECT_ROOT" <<'PY'
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
readme = (root / "README.md").read_text(encoding="utf-8")
required = [
    "## Status",
    "PASS unit: 8 tests",
    "PASS clean clone: verified committed snapshot from outside the source tree",
    "## Unfinished",
]
missing = [item for item in required if item not in readme]
if missing:
    raise SystemExit(f"README is missing required status text: {missing}")
if "TODO" in readme:
    raise SystemExit("README still contains TODO text")

listed = subprocess.run(
    ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
).stdout.split(b"\0")
secret_patterns = [
    re.compile(rb"ghp_[A-Za-z0-9]{30,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# WHY A NUL BYTE IS NORMALLY A FAILURE. The scans below read tracked files as bytes and look for
# credentials, home paths and em dashes. That is only worth anything if the files are readable text;
# a binary blob could carry any of them in a compressed stream where no pattern here would match. So
# "contains a NUL" is really "this file cannot be scanned", and it fails.
#
# ONE FILE IS ALLOWED TO BE BINARY, AND IT IS NAMED. This tool imposes zines and the published page
# links the imposed PDF, so the PDF is a deliverable rather than a stray artifact. Naming it keeps
# the exemption from spreading: a second binary appearing is still a failure, and the list is
# checked in both directions so it cannot rot.
BINARY_BY_DESIGN = {"docs/zine-saddle.pdf"}
seen_binary = set()

for relative in listed:
    if not relative:
        continue
    name = relative.decode()
    path = root / name
    data = path.read_bytes()
    if len(data) > 1_000_000:
        raise SystemExit(f"tracked file exceeds 1 MB: {name}")
    if b"\0" in data:
        if name not in BINARY_BY_DESIGN:
            raise SystemExit(f"tracked file contains a NUL byte: {name}")
        seen_binary.add(name)
    if (b"/" + b"home/") in data:
        raise SystemExit(f"tracked file contains an absolute home path: {name}")
    if b"\xe2\x80\x94" in data:
        raise SystemExit(f"tracked file contains an em dash: {name}")
    for pattern in secret_patterns:
        if pattern.search(data):
            raise SystemExit(f"tracked file contains a credential-shaped string: {name}")

# The exemption is checked the other way round too. A name left here after the file stops being
# binary, or stops being tracked, is an exemption nobody is looking at any more.
if seen_binary != BINARY_BY_DESIGN:
    stale = sorted(BINARY_BY_DESIGN - seen_binary)
    raise SystemExit(f"these files are exempted from the text scan but are not tracked binaries: "
                     f"{', '.join(stale)}")
PY
echo "PASS project: README status, tracked text, size, and credential scan"

if [[ "${ZINEGEN_CLONE_CHECK:-0}" != "1" ]]; then
  CLONE_DIR="$VERIFY_TMP/clone"
  if ! git clone -q "$PROJECT_ROOT" "$CLONE_DIR" >"$VERIFY_TMP/clone.log" 2>&1; then
    cat "$VERIFY_TMP/clone.log" >&2
    exit 1
  fi
  if ! (cd "$CLONE_DIR" && ZINEGEN_CLONE_CHECK=1 bash scripts/verify.sh) >>"$VERIFY_TMP/clone.log" 2>&1; then
    cat "$VERIFY_TMP/clone.log" >&2
    exit 1
  fi
  echo "PASS clean clone: verified committed snapshot from outside the source tree"
fi
