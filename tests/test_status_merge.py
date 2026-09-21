from __future__ import annotations

import json
import subprocess


def test_status_merge_preserves_keys_and_merges_criteria_by_text(repo_root, tmp_path):
    status = tmp_path / "STATUS.json"
    status.write_text(
        json.dumps(
            {
                "custom": {"keep": True},
                "criteria": [{"text": "works", "status": "pending", "note": "keep"}],
                "rounds": {"review": 1},
                "open_findings": [{"summary": "old"}],
            }
        ),
        encoding="utf-8",
    )
    patch = {
        "criteria": [{"text": "works", "status": "pass"}],
        "rounds": {"fix": 2},
        "open_findings": [],
    }

    subprocess.run(
        [
            "python3",
            str(repo_root / "core/skills/forge/scripts/status_merge.py"),
            "--status",
            str(status),
            "--patch-json",
            json.dumps(patch),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(status.read_text(encoding="utf-8"))

    assert result["custom"] == {"keep": True}
    assert result["criteria"] == [{"text": "works", "status": "pass", "note": "keep"}]
    assert result["rounds"] == {"review": 1, "fix": 2}
    assert result["open_findings"] == []


def test_status_merge_normalizes_legacy_collection_shapes(repo_root, tmp_path):
    status = tmp_path / "STATUS.json"
    status.write_text(
        json.dumps({"criteria": {}, "rounds": [], "open_findings": {}}),
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            str(repo_root / "core/skills/forge/scripts/status_merge.py"),
            "--status",
            str(status),
            "--patch-json",
            json.dumps({"rounds": {"fix": 1}}),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(status.read_text(encoding="utf-8"))

    assert result["criteria"] == []
    assert result["rounds"] == {"fix": 1}
    assert result["open_findings"] == []
