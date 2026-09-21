from __future__ import annotations

import os
import shutil
import stat
import subprocess


def test_resolve_base_branch_unsets_configured_gh_environment(repo_root, tmp_path):
    skill = tmp_path / "ship-pr"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "resolve-base-branch.sh"
    shutil.copy2(repo_root / "core/skills/ship-pr/scripts/resolve-base-branch.sh", script)
    binary = tmp_path / "bin"
    binary.mkdir()
    git = binary / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2 $3" = "remote get-url origin" ]; then echo https://github.com/example/repo.git; exit 0; fi\n'
        'if [ "$1 $2 $3" = "config --get aisetup.gh-unset-env" ]; then echo "GH_TOKEN GITHUB_TOKEN"; exit 0; fi\n'
        'if [ "$1" = "ls-remote" ]; then exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    record = tmp_path / "gh-env.txt"
    gh = binary / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf "%s:%s\\n" "${{GH_TOKEN-unset}}" "${{GITHUB_TOKEN-unset}}" > "{record}"\n'
        "echo main\n",
        encoding="utf-8",
    )
    for path in (git, gh, script):
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    environment = {
        **os.environ,
        "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "work-token",
        "GITHUB_TOKEN": "other-token",
    }

    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "main"
    assert record.read_text(encoding="utf-8").strip() == "unset:unset"
