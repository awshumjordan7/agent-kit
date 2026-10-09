"""Feed each case to the hook on stdin; print OK|BAD id exp today rule ms, then per-prefix summaries.

Usage: FIXTURES_ROOT=<dir> HOOK=<hook.py> CASES=<cases.json> python3 run_cases.py [--show ID,ID,...]
HOOK defaults to the repo's core/hooks/block_secret_reads.py, FIXTURES_ROOT to fixtures/ here.
Exits 1 when any case is BAD.
Cases carry either "cmd" (a Bash command) or "tool" plus "input" (a path-tool payload).
{tracked} {ignored} {visible} {clean} {nogit} expand to absolute fixture paths. The hook runs
with cwd = the case's "cwd" fixture (default clean), and the payload carries that "cwd" unless
"payload_cwd" is false. An optional "proc_cwd" (a fixture name, optionally "name/sub") moves only
the hook process cwd; the payload keeps the case's "cwd". Every "stderr_has" substring must
appear in stderr for OK.
"""
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import time

here = pathlib.Path(__file__).resolve().parent
HOOK = os.environ.get("HOOK", str(here.parent.parent / "core" / "hooks" / "block_secret_reads.py"))
CASES = os.environ.get("CASES", "cases.json")
fixtures_root = pathlib.Path(os.environ.get("FIXTURES_ROOT", here / "fixtures"))
FIXTURES = {n: str((fixtures_root / n).resolve())
            for n in json.loads((here / "fixtures.json").read_text()) if not n.startswith("_")}
cases = json.loads((here / CASES).read_text())
show: set[str] = set()
if "--show" in sys.argv:
    show = set(sys.argv[sys.argv.index("--show") + 1].split(","))


def fill(value):
    if isinstance(value, str):
        for name, path in FIXTURES.items():
            value = value.replace("{" + name + "}", path)
        return value
    if isinstance(value, dict):
        return {k: fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v) for v in value]
    return value


def payload_for(case: dict, cwd: str) -> str:
    if "tool" in case:
        p = {"tool_name": case["tool"], "tool_input": fill(case["input"])}
    else:
        p = {"tool_name": "Bash", "tool_input": {"command": fill(case["cmd"])}}
    if case.get("payload_cwd", True):
        p["cwd"] = cwd
    return json.dumps(p)


def prefix(case_id: str) -> str:
    return "D" if case_id.startswith("D-") else re.match(r"[A-Za-z]+", case_id).group(0)


summary: dict[str, list[int]] = {}
bad: dict[str, list[str]] = {}
times: list[float] = []
for c in cases:
    if show and c["id"] not in show:
        continue
    cwd = FIXTURES[c.get("cwd", "clean")]
    proc_cwd = cwd
    if "proc_cwd" in c:
        name, _, sub = c["proc_cwd"].partition("/")
        proc_cwd = str(pathlib.Path(FIXTURES[name], sub)) if sub else FIXTURES[name]
    start = time.perf_counter()
    r = subprocess.run([sys.executable, HOOK], input=payload_for(c, cwd), capture_output=True,
                       text=True, cwd=proc_cwd)
    ms = (time.perf_counter() - start) * 1000
    times.append(ms)
    today = {0: "pass", 2: "block"}.get(r.returncode, f"exit{r.returncode}")
    m = re.search(r"\(rule ([\w-]+)", r.stderr)
    rule = m.group(1) if m else "-"
    if "Traceback" in r.stderr:
        rule += " TRACEBACK"
    missing = [s for s in c.get("stderr_has", []) if s not in r.stderr]
    if missing and today == c["exp"]:
        rule += " MISSING-STDERR"
    ok = today == c["exp"] and "Traceback" not in r.stderr and not missing
    s = summary.setdefault(prefix(c["id"]), [0, 0])
    s[0 if ok else 1] += 1
    if not ok:
        bad.setdefault(prefix(c["id"]), []).append(c["id"])
    print(f"{'OK ' if ok else 'BAD'} {c['id']:7} exp={c['exp']:5} today={today:5} {rule} {ms:.0f}ms")
    if show:
        print(r.stderr)

print("---")
for p, (n_ok, n_bad) in summary.items():
    print(f"SUMMARY {p}: OK={n_ok} BAD={n_bad} {' '.join(bad.get(p, []))}".rstrip())
if times:
    print(f"MAX {max(times):.0f}ms MEDIAN {statistics.median(times):.0f}ms N={len(times)}")
sys.exit(1 if bad else 0)
