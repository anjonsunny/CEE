"""Section I — Documentation consistency.

I1, I2: manual. I3: auto (memory file index)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import MEMORY_DIR  # noqa: E402


@pytest.mark.warn
@pytest.mark.human
@pytest.mark.skip(reason="I1: CLAUDE.md research stages content is HUMAN-only per TESTS.md")
def test_i1_claude_md_research_stages():
    pass


@pytest.mark.warn
@pytest.mark.human
@pytest.mark.skip(reason="I2: REGEN_LOG.md freshness is HUMAN-only per TESTS.md")
def test_i2_regen_log_current():
    pass


@pytest.mark.warn
def test_i3_memory_index_entries_resolve():
    """I3 — Every `[Title](file.md)` link in MEMORY.md points to an existing
    file, and that file's `description:` frontmatter line is non-empty."""
    mem = MEMORY_DIR / "MEMORY.md"
    if not mem.is_file():
        pytest.skip(f"MEMORY.md not found at {mem}; nothing to verify")
    text = mem.read_text(encoding="utf-8")
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")
    failures: list[str] = []
    for title, fname in link_re.findall(text):
        target = MEMORY_DIR / fname
        if not target.is_file():
            failures.append(f"[{title}]({fname}) — file missing at {target}")
            continue
        body = target.read_text(encoding="utf-8")
        # Look for a description: line in the frontmatter.
        m = re.search(r"^description:\s*(.+)$", body, re.MULTILINE)
        if not m or not m.group(1).strip().strip("\"'"):
            failures.append(f"[{title}]({fname}) — missing/empty description: frontmatter")
    assert not failures, "Memory index issues:\n  " + "\n  ".join(failures)
