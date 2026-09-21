from __future__ import annotations

import pytest

from aisetup.render import RenderError, render_agent_frontmatter, render_text


def test_agent_frontmatter_renders_values_and_removes_nulls():
    source = "---\nname: scout\nmodel: haiku\neffort: low\nmaxTurns: 10\n---\nBody\n"

    rendered = render_agent_frontmatter(
        source,
        {"model": "sonnet", "maxTurns": 50, "effort": None},
    )

    assert "model: sonnet" in rendered
    assert "maxTurns: 50" in rendered
    assert "effort:" not in rendered
    assert rendered.endswith("Body\n")


def test_agent_frontmatter_preserves_declared_model_without_profile_override():
    source = "---\nname: overlay-agent\nmodel: opus\n---\nBody\n"

    assert "model: opus" in render_agent_frontmatter(source, {})


def test_template_json_encodes_maps():
    rendered = render_text(
        "{{json forge.gate}}", {"forge": {"gate": {"repo": {"lint": "ruff"}}}}, source="config"
    )

    assert rendered == '{"repo": {"lint": "ruff"}}'


def test_template_missing_key_names_key_and_source():
    with pytest.raises(RenderError, match=r"missing template key forge\.gate in config\.tmpl"):
        render_text("{{json forge.gate}}", {}, source="config.tmpl")
