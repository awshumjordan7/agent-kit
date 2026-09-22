import json
import subprocess
import sys
from pathlib import Path

import pytest

H = [sys.executable, str(Path(__file__).parents[1] / "core/hooks/block_secret_reads.py")]


def run(t, ti):
    return subprocess.run(
        H,
        input=json.dumps({"tool_name": t, "tool_input": ti}),
        capture_output=True,
        text=True,
    ).returncode


HOME = "/Users/jfierro"
cases = [
    ("Grep", {"pattern": "x", "path": "/proj/.env"}, 2, "grep env file"),
    ("Write", {"file_path": HOME + "/.aws/credentials"}, 2, "write credentials"),
    ("Artifact", {"file_path": HOME + "/.npmrc"}, 2, "artifact credential file"),
    ("NotebookEdit", {"notebook_path": "/proj/.env"}, 2, "notebook env file"),
    ("Edit", {"file_path": "/proj/.env"}, 2, "edit env file"),
    ("Read", {"file_path": "/proj/.envs/.django"}, 2, "read env file"),
    ("Read", {"file_path": HOME + "/.ssh/id_rsa"}, 2, "read key file"),
    ("Grep", {"pattern": "x", "path": "/proj", "glob": ".envs/*"}, 2, "glob secrets directory"),
    ("Read", {"file_path": "/proj/.env.example"}, 0, "allowlisted template path"),
    ("Bash", {"command": "echo $API_TOKEN"}, 2, "shell secret variable"),
    ("Bash", {"command": "gh auth token"}, 2, "credential printing command"),
    ("Read", {"file_path": "/proj/README.md"}, 0, "allowed sibling path"),
]


@pytest.mark.parametrize("t,ti,want,label", cases, ids=[c[3] for c in cases])
def test_case(t, ti, want, label):
    assert run(t, ti) == want, label


if __name__ == "__main__":
    fail = 0
    for t, ti, want, label in cases:
        got = run(t, ti)
        ok = got == want
        fail += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label:28} want={want} got={got}")
    print("\nALL PASS" if not fail else f"\n{fail} FAILURE(S)")
    sys.exit(1 if fail else 0)
