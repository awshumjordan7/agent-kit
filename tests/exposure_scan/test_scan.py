"""Run exposure_scan.py as a command against sanitized fixture transcripts."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "core" / "scripts" / "exposure_scan.py"
FIXTURE_ROOT = HERE / "fixtures" / "projects"
# Planted fake values in the fixture transcripts.
# Built from parts so the repository's token-shape scan does not flag it.
FAKE_AWS_KEY = "AKIA" + "Q7FIXTUREZ3K4W2M"
FAKE_ENV_VALUE = "q8Zr2LmN4vB7xT1pW9sK"


def run_scan(*args: str, home: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=home) if home else None
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False, env=env, timeout=60
    )


class ScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name) / "projects"
        shutil.copytree(FIXTURE_ROOT, root)
        session = root / "-fixture-project" / "session-fixture.jsonl"
        text = session.read_text(encoding="utf-8").replace("__FAKE_AWS_KEY__", FAKE_AWS_KEY)
        session.write_text(text, encoding="utf-8")
        out = Path(cls.tmp.name) / "exposures.jsonl"
        # The fixture timestamps are fixed, so the window must reach back to them.
        cls.result = run_scan("--days", "36500", "--root", str(root), "--out", str(out))
        cls.log = out.read_text(encoding="utf-8") if out.exists() else ""
        cls.rows = [json.loads(line) for line in cls.log.splitlines()]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_planted_key_reported_without_value(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        aws = [row for row in self.rows if row["pattern"] == "aws-access-key-id"]
        self.assertEqual(len(aws), 1)
        self.assertEqual(aws[0]["session"], "-fixture-project/session-fixture.jsonl")
        self.assertEqual(aws[0]["line"], 3)
        self.assertEqual(aws[0]["tool"], "Bash")
        self.assertEqual(aws[0]["kind"], "main")
        for output in (self.log, self.result.stdout, self.result.stderr):
            self.assertNotIn(FAKE_AWS_KEY[4:], output)

    def test_env_assignment_found_in_numbered_read_output(self) -> None:
        env_rows = [row for row in self.rows if row["pattern"] == "env-secret-assign"]
        self.assertEqual(len(env_rows), 1)
        self.assertEqual(env_rows[0]["tool"], "Read")
        self.assertEqual(env_rows[0]["kind"], "subagent")
        self.assertNotIn(FAKE_ENV_VALUE, self.log)

    def test_schedule_dry_run_prints_weekly_plist(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            result = run_scan("--install-schedule", "--dry-run", home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            plist = plistlib.loads(result.stdout.encode("utf-8"))
            self.assertEqual(plist["StartCalendarInterval"], {"Weekday": 1, "Hour": 9, "Minute": 0})
            self.assertEqual(
                plist["ProgramArguments"],
                ["/usr/bin/python3", str(Path(home) / ".claude" / "scripts" / "exposure_scan.py"), "--days", "7"],
            )
            self.assertFalse((Path(home) / "Library" / "LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()
