from __future__ import annotations

import json
from pathlib import Path

from aisetup.cli import main
from aisetup.profile import load_recommended_profile
from aisetup.tune import collect_metrics, recommendations

TRANSCRIPTS = Path(__file__).parent / "fixtures/transcripts"


def test_metrics_reports_overlap_and_cap_recommendation(repo_root):
    profile, _ = load_recommended_profile(repo_root)
    metrics = collect_metrics(
        repo_root,
        profile,
        TRANSCRIPTS,
        since=None,
        until=None,
        timezone_offset="+00:00",
    )

    assert metrics["peak_concurrent"] == 2
    assert any(row["knob"] == "agents.worker.maxTurns" for row in recommendations(profile, metrics))


def test_tune_does_not_rewrite_profile(repo_root, tmp_path):
    profile, _ = load_recommended_profile(repo_root)
    layers_root = tmp_path / ".ai-setup"
    layers_root.mkdir()
    profile_path = layers_root / "profile.json"
    original = json.dumps(profile, indent=2) + "\n"
    profile_path.write_text(original, encoding="utf-8")

    result = main(
        [
            "tune",
            "--layers-root",
            str(layers_root),
            "--transcripts",
            str(TRANSCRIPTS),
            "--out",
            str(tmp_path / "report.txt"),
        ]
    )

    assert result == 0
    assert profile_path.read_text(encoding="utf-8") == original
