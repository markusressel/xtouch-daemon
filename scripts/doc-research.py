#!/usr/bin/env python3
"""
Blind research in the documentation: for each question of a question file, a reader who knows nothing of the project
looks for the answer on the pages for users, the way a user does (the navigation and the links, no search, no code),
and reports its answer, the pages it read and what disagrees or repeats between pages. A grader then compares the
answers with the answers of the file (AGENTS.md, "Writing docs").

    scripts/doc-research.py scripts/doc-questions.json out/        # all questions, 8 at a time
    scripts/doc-research.py scripts/doc-questions.json out/ q03    # one

The question file is a list of {"id", "question", ...}. Needs the claude CLI; MODEL (default sonnet) picks the model.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

PROMPT = """\
You are a new user of xtouch-daemon: a Linux user, comfortable with a terminal and config files, PipeWire desktop,
a Behringer X-Touch Extender on the desk. You have a question and look for the answer in the documentation, here in
this directory.

Your question: {question}

Rules:
- Start with nav.md (the site's navigation, as in its sidebar) and index.md (the front page). Then open only pages
  that the navigation lists or that a page you read links to, as a user clicks. No search (no Grep, no Glob), no
  other files. Links to pages under development/ are not available.
- Read like a user: stop when you have the answer. Don't read everything.
- Use no knowledge of this project beyond the pages.

Answer in Markdown, then end with one JSON block (```json) with these keys:
- "answer": your answer to the question, as you would act on it (a config snippet or steps), short;
- "pages": the pages you opened, in order (paths as in this directory);
- "confident": true if the pages answered it, false if you had to guess;
- "contradictions": list of {{"pages": [...], "what": "..."}}: two places that disagree;
- "repeats": list of {{"pages": [...], "what": "..."}}: the same thing explained on several pages you read;
- "missing": what you looked for and didn't find, or "".
"""


def navigation() -> str:
    """The navigation of the site without the pages for developers, as a nested list of titles and paths."""
    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    lines: list[str] = []

    def walk(items: list[object], depth: int) -> None:
        for item in items:
            if isinstance(item, str):
                lines.append(f"{'  ' * depth}- {item}")
                continue
            assert isinstance(item, dict)
            for title, target in item.items():
                if title == "Development":
                    continue
                if isinstance(target, list):
                    lines.append(f"{'  ' * depth}- {title}")
                    walk(target, depth + 1)
                else:
                    lines.append(f"{'  ' * depth}- {title}: {target}")

    walk(nav, 0)
    return "\n".join(lines) + "\n"


def research(entry: dict[str, str], out: Path) -> Path:
    with tempfile.TemporaryDirectory() as directory:
        site = Path(directory) / "docs"
        shutil.copytree(DOCS, site, ignore=shutil.ignore_patterns("development", "images", "javascripts", "*.json"))
        (site / "nav.md").write_text(navigation())
        result = subprocess.run(
            [
                "claude", "-p", PROMPT.format(question=entry["question"]),
                "--model", os.environ.get("MODEL", "sonnet"),
                "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config", "--no-session-persistence",
            ],
            cwd=site, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
        )  # fmt: skip
    text = result.stdout
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    report: dict[str, object] = {"id": entry["id"], "question": entry["question"], "raw": text}
    if blocks:
        with contextlib.suppress(json.JSONDecodeError):
            report |= json.loads(blocks[-1])
    listed = report.get("pages")
    pages = [page for page in listed if isinstance(page, str)] if isinstance(listed, list) else []
    report["words"] = sum(len((DOCS / page).read_text().split()) for page in pages if (DOCS / page).is_file())
    path = out / f"{entry['id']}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def main() -> None:
    questions = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    chosen = [entry for entry in questions if len(sys.argv) < 4 or entry["id"] in sys.argv[3:]]
    with ThreadPoolExecutor(8) as pool:
        for path in pool.map(lambda entry: research(entry, out), chosen):
            print(path)


if __name__ == "__main__":
    main()
