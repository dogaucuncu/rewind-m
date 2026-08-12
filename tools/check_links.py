#!/usr/bin/env python3
"""Check that every relative link and anchor in the Markdown actually resolves.

A broken link in a README is the kind of thing nobody notices while writing and
everybody notices while reading. External URLs are not fetched - this is a
structural check, not a network one, so it stays fast and cannot fail because
somebody else's site is down.

    python tools/check_links.py
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def anchor_of(heading: str) -> str:
    """GitHub's slug rules, near enough for our own headings."""
    text = heading.strip().lower()
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def anchors_in(path: pathlib.Path) -> set[str]:
    return {
        anchor_of(h) for h in HEADING_RE.findall(path.read_text(encoding="utf-8"))
    }


def main() -> int:
    problems: list[str] = []
    markdown = sorted(REPO.glob("*.md")) + sorted(REPO.glob("docs/*.md"))

    for source in markdown:
        text = source.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue

            path_part, _, anchor = target.partition("#")
            if path_part:
                resolved = (source.parent / path_part).resolve()
                if not resolved.exists():
                    problems.append(
                        f"{source.relative_to(REPO)}: {target} -> no such file"
                    )
                    continue
            else:
                resolved = source

            if anchor and resolved.suffix == ".md":
                if anchor not in anchors_in(resolved):
                    problems.append(
                        f"{source.relative_to(REPO)}: {target} -> no such heading"
                    )

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} broken link(s)", file=sys.stderr)
        return 1
    print(f"all relative links resolve across {len(markdown)} markdown files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
