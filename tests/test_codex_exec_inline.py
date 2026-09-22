from __future__ import annotations

import json
import os
import stat
import subprocess


def _skill(repo_root, tmp_path):
    skill = tmp_path / "forge"
    (skill / "scripts").mkdir(parents=True)
    (skill / "references").mkdir()
    script = repo_root / "core/skills/forge/scripts/codex-exec.sh"
    target = skill / "scripts/codex-exec.sh"
    target.write_bytes(script.read_bytes())
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    (skill / "forge.config.json").write_text(
        json.dumps(
            {
                "roles": {"review": {"model": "test", "effort": "high"}},
                "codex": {"roles": {"review": {"contract": "none"}}},
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
    }

    completed = subprocess.run(
        _command(script, tmp_path, diff), capture_output=True, text=True, env=env
    )

    assert completed.returncode == 0, completed.stderr
    sent = (tmp_path / "prompt.md.sent").read_text(encoding="utf-8")
    assert f"## DIFF ({diff}, 2 lines)" in sent
    assert "[cut at 160000 of 160123 characters]" in sent
    assert "TAIL" not in sent
