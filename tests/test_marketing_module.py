from __future__ import annotations

from pathlib import Path

import pytest

BRIEF_SECTIONS = (
    "## Purpose",
    "## Inputs",
    "## Evidence and confidence",
    "## Steps",
    "## Output template",
    "## Evidence ledger",
    "## QA gate",
    "## Handoff",
)

BRIEFS = (
    "discovery.md",
    "positioning.md",
    "sales-intel.md",
    "voice-of-customer.md",
    "seo-content.md",
    "internal-sources.md",
    "synthesizer.md",
    "persona-seeder.md",
    "evidence-collector.md",
    "persona-analyzer.md",
    "persona-synthesizer.md",
)

MODE_SUBSECTIONS = ("### Purpose", "### Inputs", "### Template")


def headings(text: str, prefix: str) -> list[str]:
    """Headings at the given level, ignoring anything inside a fenced code block."""
    found = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith(prefix):
            found.append(line.strip())
    return found


@pytest.fixture
def references(repo_root: Path) -> Path:
    return repo_root / "modules/marketing/skills/market-research/references"


def test_every_brief_is_present(references: Path):
    assert sorted(path.name for path in references.glob("*.md")) == sorted(BRIEFS)


@pytest.mark.parametrize("name", BRIEFS)
def test_brief_has_the_method_sections_in_order(references: Path, name: str):
    text = (references / name).read_text(encoding="utf-8")

    assert headings(text, "## ") == list(BRIEF_SECTIONS)


@pytest.mark.parametrize("name", BRIEFS)
def test_brief_length_stays_within_the_house_range(references: Path, name: str):
    lines = len((references / name).read_text(encoding="utf-8").splitlines())

    assert 80 <= lines <= 160


def test_content_modes_each_have_purpose_inputs_and_template(repo_root: Path):
    text = (
        repo_root / "modules/marketing/skills/content-pipeline/references/modes.md"
    ).read_text(encoding="utf-8")

    modes = text.split("\n## Mode ")[1:]
    assert len(modes) == 4
    for mode in modes:
        assert headings("## Mode " + mode, "### ") == list(MODE_SUBSECTIONS)
