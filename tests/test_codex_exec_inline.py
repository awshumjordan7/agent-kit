from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest


def _skill(repo_root, tmp_path):
    skill = tmp_path / "forge"
    (skill / "scripts").mkdir(parents=True)
    (skill / "references").mkdir()
    script = repo_root / "core/skills/forge/scripts/codex-exec.sh"
    target = skill / "scripts/codex-exec.sh"
    target.write_bytes(script.read_bytes())
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    (skill / "references/codex-prompt-contract.md").write_bytes(
        (repo_root / "core/skills/forge/references/codex-prompt-contract.md").read_bytes()
    )
    (skill / "forge.config.json").write_text(
        json.dumps(
            {
                "roles": {
                    "review": {"model": "test", "effort": "high"},
                    "impl": {"model": "test", "effort": "high"},
                },
                "codex": {
                    "roles": {
                        "review": {"contract": "review", "maxToolCalls": 90},
                        "impl": {"contract": "impl", "maxToolCalls": 150},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return target


def _command(script, tmp_path, diff):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("review this\n", encoding="utf-8")
    return [
        "bash",
        str(script),
        "start",
        "--foreground",
        "--fresh",
        "--thread-file",
        str(tmp_path / "thread"),
        "--prompt-file",
        str(prompt),
        "--inline-diff",
        str(diff),
        "--log",
        str(tmp_path / "events.jsonl"),
        "--out",
        str(tmp_path / "final.md"),
        "--role",
        "review",
    ]


def _fake_codex(tmp_path, *, calls=0, finish=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "codex"
    call_events = "".join(
        "printf '%s\\n' "
        "'{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\",\"aggregated_output\":\"ok\"}}'\n"
        for _ in range(calls)
    )
    ending = (
        "printf 'done\\n' >\"$out\"\n"
        "printf '%s\\n' '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":1,\"output_tokens\":1}}'\n"
        if finish
        else "sleep 120\n"
    )
    fake.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--output-last-message" ]; then shift; out=$1; fi\n'
        "  shift\n"
        "done\n"
        'printf "%s\\n" "$$" >"$FAKE_PID_FILE"\n'
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"thread-guard\"}'\n"
        f"{call_events}{ending}",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _rollout(tmp_path, context_tokens, message="last agent message"):
    rollout_dir = tmp_path / ".codex/sessions/2026/09/22"
    rollout_dir.mkdir(parents=True)
    rollout = rollout_dir / "rollout-test-thread-guard.jsonl"
    rollout.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": context_tokens}},
                },
            }
        )
        + "\n"
        + json.dumps(
            {"type": "event_msg", "payload": {"type": "agent_message", "message": message}}
        )
        + "\n",
        encoding="utf-8",
    )


def _guard_env(tmp_path, bin_dir):
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CODEX_HOME": str(tmp_path / ".codex"),
        "FAKE_PID_FILE": str(tmp_path / "fake.pid"),
        "FORGE_CODEX_POLL_INTERVAL": "1",
        "FORGE_CODEX_STATE_DIR": str(tmp_path / "state"),
    }


def test_inline_diff_rejects_invalid_file_and_writes_result(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "bad.diff"
    diff.write_text("not a diff\n", encoding="utf-8")

    completed = subprocess.run(_command(script, tmp_path, diff), capture_output=True, text=True)

    assert completed.returncode == 65
    result = json.loads((tmp_path / "events.jsonl.result.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["code"] == 65
    assert result["message"].startswith("CODEX_DIFF_INVALID")


def test_inline_diff_is_capped_in_sent_prompt(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n" + "A" * 160100 + "TAIL", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--output-last-message" ]; then shift; out=$1; fi\n'
        "  shift\n"
        "done\n"
        "printf 'done\\n' >\"$out\"\n"
        'printf \'%s\\n\' \'{"type":"thread.started","thread_id":"thread-1"}\'\n'
        'printf \'%s\\n\' \'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\'\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FORGE_CODEX_STATE_DIR": str(tmp_path / "state"),
        "FORGE_CODEX_POLL_INTERVAL": "1",
    }

    completed = subprocess.run(
        _command(script, tmp_path, diff), capture_output=True, text=True, env=env
    )

    assert completed.returncode == 0, completed.stderr
    sent = (tmp_path / "prompt.md.sent").read_text(encoding="utf-8")
    assert f"## DIFF ({diff}, 2 lines)" in sent
    assert "[cut at 160000 of 160123 characters]" in sent
    assert "TAIL" not in sent
    assert not (tmp_path / "events.jsonl.handoff.md").exists()


def test_context_cap_writes_handoff_and_kills_codex(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")
    state_file = tmp_path / "worker-state.md"
    state_file.write_text("phase one complete\n", encoding="utf-8")
    bin_dir = _fake_codex(tmp_path)
    _rollout(tmp_path, 130000)

    command = [
        *_command(script, tmp_path, diff),
        "--handoff-context-tokens", "120000", "--state-file", str(state_file),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, env=_guard_env(tmp_path, bin_dir)
    )

    assert completed.returncode == 79, completed.stderr
    result = json.loads((tmp_path / "events.jsonl.result.json").read_text(encoding="utf-8"))
    assert result["status"] == "handoff"
    assert result["context_tokens"] == 130000
    handoff = (tmp_path / "events.jsonl.handoff.md").read_text(encoding="utf-8")
    assert all(heading in handoff for heading in ("## Reason", "## State file", "## Last message", "## git diff --stat"))
    assert "phase one complete" in handoff
    assert "last agent message" in handoff
    pid = int((tmp_path / "fake.pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert "outcome=handoff" in (tmp_path / "state/usage.log").read_text(encoding="utf-8")


def test_tool_call_cap_trips_with_low_context(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")
    bin_dir = _fake_codex(tmp_path, calls=3)
    _rollout(tmp_path, 1000)

    completed = subprocess.run(
        [*_command(script, tmp_path, diff), "--handoff-tool-calls", "3"],
        capture_output=True,
        text=True,
        env=_guard_env(tmp_path, bin_dir),
    )

    assert completed.returncode == 79, completed.stderr
    handoff = (tmp_path / "events.jsonl.handoff.md").read_text(encoding="utf-8")
    assert "calls=3/3" in handoff


def test_handoff_checks_can_be_disabled(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")
    bin_dir = _fake_codex(tmp_path, finish=True)
    _rollout(tmp_path, 130000)

    completed = subprocess.run(
        [
            *_command(script, tmp_path, diff),
            "--handoff-context-tokens", "0", "--handoff-tool-calls", "0",
        ],
        capture_output=True,
        text=True,
        env=_guard_env(tmp_path, bin_dir),
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "events.jsonl.handoff.md").exists()


def test_contract_renders_handoff_caps_and_impl_state_template(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")
    bin_dir = _fake_codex(tmp_path, finish=True)
    state_file = tmp_path / "state-file.md"
    command = _command(script, tmp_path, diff)
    command[-1] = "impl"
    command += [
        "--handoff-context-tokens", "12345", "--handoff-tool-calls", "12",
        "--state-file", str(state_file),
    ]

    completed = subprocess.run(
        command, capture_output=True, text=True, env=_guard_env(tmp_path, bin_dir)
    )

    assert completed.returncode == 0, completed.stderr
    sent = (tmp_path / "prompt.md.sent").read_text(encoding="utf-8")
    assert "near 12345 tokens of context or 12 tool calls" in sent
    assert str(state_file) in sent
    assert "Keep " in sent
    state_headings = (
        "## Done", "## In progress", "## Next", "## Validation", "## Gotchas"
    )
    assert all(heading in sent for heading in state_headings)

    command[command.index("--role") + 1] = "review"
    completed = subprocess.run(
        command, capture_output=True, text=True, env=_guard_env(tmp_path, bin_dir)
    )
    assert completed.returncode == 0, completed.stderr
    review_sent = (tmp_path / "prompt.md.sent").read_text(encoding="utf-8")
    assert "Keep " not in review_sent
    assert all(heading not in review_sent for heading in state_headings)


def test_handoff_cap_is_clamped_below_hard_budget(repo_root, tmp_path):
    script = _skill(repo_root, tmp_path)
    diff = tmp_path / "review.diff"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")
    bin_dir = _fake_codex(tmp_path, calls=49)
    _rollout(tmp_path, 1000)

    completed = subprocess.run(
        [
            *_command(script, tmp_path, diff),
            "--handoff-tool-calls", "200", "--max-tool-calls", "50",
        ],
        capture_output=True,
        text=True,
        env=_guard_env(tmp_path, bin_dir),
    )

    assert completed.returncode == 79, completed.stderr
    assert "clamped to 49" in completed.stderr
    assert "calls=49/49" in (tmp_path / "events.jsonl.handoff.md").read_text(encoding="utf-8")
