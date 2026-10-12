"""Build the fake fixture repos described in fixtures.json under $FIXTURES_ROOT/<name>/
(default: fixtures/<name>/ next to this file).

Build them outside any git repo: the nogit fixture must not sit inside one. The root path
must not contain `env` as a separate word, because the hook reads that word in a command
as an environment dump and changes its verdicts.

Get or create: an existing fixture dir is left alone and only checked
(files present, and for git fixtures `git ls-files` equals `track`). A fixture with
"break": "index" gets an empty .git/index after its commit, and its check is that
`git ls-files` exits 128 with an error other than "not a git repository".
"""
import json
import os
import pathlib
import re
import subprocess
import sys

here = pathlib.Path(__file__).resolve().parent
spec = json.loads((here / "fixtures.json").read_text())
root = pathlib.Path(os.environ.get("FIXTURES_ROOT", here / "fixtures")).resolve()
if re.search(r"\benv\b", str(root), re.IGNORECASE):
    sys.exit(f"fixture root {root} contains the word env; pick another path")
root.mkdir(parents=True, exist_ok=True)


def git(cwd: pathlib.Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout


def check(name: str, d: pathlib.Path, fx: dict) -> list[str]:
    problems = [f"missing {rel}" for rel in fx["files"] if not (d / rel).is_file()]
    if fx.get("break") == "index":
        # The hook must see a git error other than "not a git repository".
        r = subprocess.run(["git", "ls-files"], cwd=d, capture_output=True, text=True, check=False)
        if r.returncode != 128 or "not a git repository" in r.stderr:
            problems.append(f"git ls-files exited {r.returncode} ({r.stderr.strip()[:120]}), want 128")
    elif fx["git"]:
        tracked = sorted(git(d, "ls-files").splitlines())
        if tracked != sorted(fx["track"]):
            problems.append(f"ls-files {tracked} != track {sorted(fx['track'])}")
    elif (d / ".git").exists():
        problems.append("has .git but git=false")
    return problems


def build(d: pathlib.Path, fx: dict) -> None:
    for rel, body in fx["files"].items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    if fx["git"]:
        git(d, "init", "-q")
        if fx["track"]:
            git(d, "add", "-f", "--", *fx["track"])
        git(d, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-q", "--allow-empty", "-m", "fixture")
        if fx.get("break") == "index":
            (d / ".git" / "index").write_bytes(b"")


failed = False
for name, fx in spec.items():
    if name.startswith("_"):
        continue
    d = root / name
    if d.exists():
        action = "exists"
    else:
        d.mkdir(parents=True)
        build(d, fx)
        action = "created"
    problems = check(name, d, fx)
    status = "OK" if not problems else "FAIL " + "; ".join(problems)
    failed |= bool(problems)
    print(f"{name:8} {action:8} {status}")
sys.exit(1 if failed else 0)
