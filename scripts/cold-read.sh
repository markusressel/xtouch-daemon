#!/usr/bin/env bash
# A cold read of a documentation page: a reader who knows nothing of the project reads the page and reports where it
# fails a newcomer (explain back, a task, friction, open questions). The reader runs in an empty directory, so no
# project instructions, code or other pages reach it; it sees the front page and Concepts as what it read before.
#
#   scripts/cold-read.sh docs/configuration/slots.md [report.md]
#
# Needs the claude CLI. MODEL (default sonnet) picks the model.
set -euo pipefail

page=${1:?usage: cold-read.sh <page.md> [report.md]}
root=$(cd "$(dirname "$0")/.." && pwd)
page=$(realpath "$page")
rel=${page#"$root"/}
report=${2:-/tmp/cold-read/${rel//\//_}}
model=${MODEL:-sonnet}

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
before=""
for prior in docs/index.md docs/concepts.md; do
    if [[ $rel != "$prior" ]]; then
        cp "$root/$prior" "$dir/before-$(basename "$prior")"
        before+=" before-$(basename "$prior")"
    fi
    [[ $rel == "$prior" ]] && break
done
cp "$page" "$dir/page.md"

prompt=$(cat <<EOF
You are a test reader for documentation. Persona: a Linux user, comfortable with a terminal and config files, on a
PipeWire desktop. You just bought a Behringer X-Touch Extender and found this project; you have never seen it before.

Rules:
- In this directory, page.md is the page under test (its source path: $rel).${before:+ You read these pages before it, skim them first as background:$before.}
- Read only these files. Links to other pages can't be followed: if the page sends you elsewhere for a detail, that is
  fine; say which link you would follow. Images are not available; judge the text alone.
- Use no knowledge of this project beyond the pages. Be honest, not polite: your value is in finding where the page
  fails.

Report on page.md, plain Markdown, at most 800 words:
1. Explain back: in your own words, as to a friend, what the page teaches. Define each term it introduces or relies on,
   one line each, as you understood it. Name any pair of terms you could not tell apart.
2. Task: pick the main thing the page promises you can do after reading it, and try it from the page alone (e.g.
   write the configuration, run the command, follow the steps). Mark every place where you had to guess, and what
   you guessed.
3. Friction: quote every sentence you had to reread, misread at first, or didn't understand. For each: what you first
   thought, what you think now, severity 1 (slowed me down), 2 (needed a reread or a guess), 3 (lost me).
4. Contradictions: any two statements on the pages that disagree.
5. Open questions a newcomer would need answered here.
EOF
)

mkdir -p "$(dirname "$report")"
(cd "$dir" && claude -p "$prompt" --model "$model" --tools Read --allowedTools Read --strict-mcp-config \
    --no-session-persistence) >"$report"
echo "$report"
