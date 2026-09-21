import json
import subprocess
import sys
from pathlib import Path

import pytest

H = [sys.executable, str(Path(__file__).parents[1] / "core/hooks/require_agent_model.py")]


def run(t, ti):
    return subprocess.run(
        H,
        input=json.dumps({"tool_name": t, "tool_input": ti}),
        capture_output=True,
        text=True,
    ).returncode


cases = [
    ("Bash", {"command": "ls"}, 0, "non-Agent tool (allow)"),
    (
        "Agent",
        {"subagent_type": "fork", "description": "x", "prompt": "x"},
        0,
        "fork subagent_type (allow)",
    ),
    (
        "Agent",
        {"phase": "plan", "description": "x", "prompt": "x"},
        0,
        "forge-core phase key (allow)",
    ),
    (
        "Agent",
        {"label": "impl", "description": "x", "prompt": "x"},
        0,
        "forge-core label key (allow)",
    ),
    (
        "Agent",
        {"description": "commit and push the branch", "prompt": "x"},
        2,
        "missing model (block)",
    ),
    (
        "Agent",
        {"description": "x", "prompt": "x", "subagent_type": "worker"},
        2,
        "missing model, subagent_type set (block)",
    ),
    (
        "Agent",
        {
            "description": "x",
            "prompt": "x",
            "subagent_type": "general-purpose",
            "model": "sonnet",
        },
        2,
        "general-purpose with model (block)",
    ),
    (
        "Agent",
        {"description": "x", "prompt": "x", "subagent_type": "claude", "model": "sonnet"},
        2,
        "claude subagent_type with model (block)",
    ),
    (
        "Agent",
        {"description": "x", "prompt": "x", "model": "sonnet"},
        2,
        "absent subagent_type with model (block)",
    ),
    (
        "Agent",
        {"description": "x", "prompt": "x", "subagent_type": "worker", "model": "sonnet"},
        0,
        "typed agent with model (allow)",
    ),
    (
        "Agent",
        {"description": "commit this branch", "prompt": "x"},
        2,
        "heuristic: commit -> shipper",
    ),
    (
        "Agent",
        {"description": "where is the config loaded", "prompt": "x"},
        2,
        "heuristic: where is -> locator",
    ),
    (
        "Agent",
        {"description": "run the tests and edit the file", "prompt": "x"},
        2,
        "heuristic: run/edit -> worker",
    ),
    (
        "Agent",
        {"description": "think about the architecture", "prompt": "x"},
        2,
        "heuristic: default -> scout",
    ),
]


@pytest.mark.parametrize("t,ti,want,label", cases, ids=[case[3] for case in cases])
def test_case(t, ti, want, label):
    assert run(t, ti) == want, label


if __name__ == "__main__":
    fail = 0
    for t, ti, want, label in cases:
        got = run(t, ti)
        ok = got == want
        fail += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label:40} want={want} got={got}")
    print("\nALL PASS" if not fail else f"\n{fail} FAILURE(S)")
    sys.exit(1 if fail else 0)
