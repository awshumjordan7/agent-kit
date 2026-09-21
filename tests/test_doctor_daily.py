from __future__ import annotations

import json
import subprocess
from datetime import date

from core.hooks import doctor_daily
from core.scripts import handoff


def test_doctor_daily_runs_once_and_prints_update_notice(tmp_path, monkeypatch):
    layers = tmp_path / "layers"
    layers.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (layers / "profile.json").write_text(
        json.dumps({"layers": {"core": {"path": str(repo)}}, "auto_update": False}),
        encoding="utf-8",
    )
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess(
                [], 0, '{"repo":"agent-kit","behind":3,"ahead":0,"command":"update"}\n', ""
            ),
        ]
    )
    monkeypatch.setattr(doctor_daily, "_run", lambda command: next(responses))

    first = doctor_daily.run_daily(layers, tmp_path / "home", date(2026, 9, 20))
    second = doctor_daily.run_daily(layers, tmp_path / "home", date(2026, 9, 20))

    assert (
        first
        == f"agent-kit: 3 new commits since your install. Run: python3 {repo}/install.py update"
    )
    assert second == ""


def test_doctor_daily_ignores_non_json_update_output(tmp_path, monkeypatch):
    layers = tmp_path / "layers"
    layers.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (layers / "profile.json").write_text(
        json.dumps({"layers": {"core": {"path": str(repo)}}, "auto_update": True}),
        encoding="utf-8",
    )
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "temporary network warning\n", ""),
        ]
    )
    monkeypatch.setattr(doctor_daily, "_run", lambda command: next(responses))

    assert doctor_daily.run_daily(layers, tmp_path / "home", date(2026, 9, 20)) == ""


def test_doctor_daily_ignores_auto_update_timeout(tmp_path, monkeypatch):
    layers = tmp_path / "layers"
    layers.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (layers / "profile.json").write_text(
        json.dumps({"layers": {"core": {"path": str(repo)}}, "auto_update": True}),
        encoding="utf-8",
    )
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "doctor notice", ""),
            subprocess.CompletedProcess(
                [], 0, '{"repo":"agent-kit","behind":1,"ahead":0,"command":"update"}\n', ""
            ),
            subprocess.TimeoutExpired("update", 20),
        ]
    )

    def run(command):
        response = next(responses)
        if isinstance(response, subprocess.TimeoutExpired):
            raise response
        return response

    monkeypatch.setattr(doctor_daily, "_run", run)

    output = doctor_daily.run_daily(layers, tmp_path / "home", date(2026, 9, 20))

    assert "doctor notice" in output
    assert "1 new commits" in output


def test_handoff_skips_osascript_outside_macos(tmp_path, monkeypatch):
    state = tmp_path / "STATE.md"
    state.write_text("state\n", encoding="utf-8")
    monkeypatch.setattr(handoff.sys, "platform", "linux")

    assert handoff.handoff(state, "session", tmp_path) == 0
