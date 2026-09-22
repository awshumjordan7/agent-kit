from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def carry(run_id: str, source: Path, destination: Path) -> None:
    workflow = source / "workflows" / f"{run_id}.json"
    agents = source / "subagents" / "workflows" / run_id
    if not workflow.is_file():
        raise FileNotFoundError(f"workflow record not found: {workflow}")

    workflow_target = destination / "workflows" / workflow.name
    workflow_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(workflow, workflow_target)
    if agents.is_dir():
        shutil.copytree(
            agents,
            destination / "subagents" / "workflows" / run_id,
            dirs_exist_ok=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--to", dest="destination", type=Path, required=True)
    args = parser.parse_args()
    carry(args.run_id, args.source, args.destination)


if __name__ == "__main__":
    main()
