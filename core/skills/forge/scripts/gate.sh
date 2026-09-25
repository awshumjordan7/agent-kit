#!/usr/bin/env bash

set -u

die() {
  printf '%s\n' "$1" >&2
  exit 2
}

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

repo=''
run_dir=''
label=''
files_given=false
skip_tests=false
only_stages=''
only_given=false
commit_message=''
push=false
sha=''
no_stages=false
print_mode=false
files=()

while (($#)); do
  case "$1" in
    --repo|--run-dir|--label|--commit|--only|--sha)
      (($# >= 2)) || die "gate.sh: $1 requires a value"
      case "$1" in
        --repo) repo=$2 ;;
        --run-dir) run_dir=$2 ;;
        --label) label=$2 ;;
        --commit) commit_message=$2 ;;
        --only) only_stages=$2; only_given=true ;;
        --sha) sha=$2 ;;
      esac
      shift 2
      ;;
    --files)
      files_given=true
      shift
      (($#)) && [[ $1 != --* ]] || die 'gate.sh: --files requires at least one path'
      while (($#)) && [[ $1 != --* ]]; do
        IFS=',' read -r -a file_parts <<<"$1"
        for file_part in ${file_parts[@]+"${file_parts[@]}"}; do
          [[ -n $file_part ]] && files+=("$file_part")
        done
        shift
      done
      ((${#files[@]})) || die 'gate.sh: --files requires at least one path'
      ;;
    --skip-tests)
      skip_tests=true
      shift
      ;;
    --push)
      push=true
      shift
      ;;
    --no-stages)
      no_stages=true
      shift
      ;;
    --print-mode)
      print_mode=true
      shift
      ;;
    *) die "gate.sh: unknown argument: $1" ;;
  esac
done

all_stages='lint,typecheck,migrations,tests,semgrep,parity'
if $only_given; then
  [[ -n $only_stages ]] || die 'gate.sh: --only requires at least one stage'
  IFS=',' read -r -a requested_stages <<<"$only_stages"
  ((${#requested_stages[@]})) || die 'gate.sh: --only requires at least one stage'
  for requested_stage in "${requested_stages[@]}"; do
    [[ ,$all_stages, == *",$requested_stage,"* ]] || die "gate.sh: unknown --only stage: $requested_stage"
  done
fi
if $no_stages; then
  $only_given && die 'gate.sh: --no-stages conflicts with --only'
  # Matches no stage name, so every stage is skipped and reported in `skipped`.
  only_stages='none'
fi

stage_enabled() {
  [[ -z $only_stages || ,$only_stages, == *",$1,"* ]]
}

if $print_mode; then
  if [[ -z $repo ]]; then
    repo=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null) || die 'gate.sh: --print-mode needs --repo or a git working directory'
  fi
else
  [[ -n $repo ]] || die 'gate.sh: --repo is required'
  [[ -n $run_dir ]] || die 'gate.sh: --run-dir is required'
  [[ -n $label ]] || die 'gate.sh: --label is required'
  [[ $label =~ ^[A-Za-z0-9._-]+$ ]] || die 'gate.sh: --label contains unsupported characters'
fi
if [[ -n $commit_message && $files_given != true ]]; then
  die 'gate.sh: --commit requires --files'
fi
if [[ $push == true && -z $commit_message ]]; then
  die 'gate.sh: --push requires --commit'
fi
if [[ -n $sha ]]; then
  [[ $sha =~ ^[0-9a-fA-F]{7,64}$ ]] || die 'gate.sh: --sha must be a commit id'
  [[ -z $commit_message ]] || die 'gate.sh: --sha conflicts with --commit'
  [[ $files_given == true ]] || die 'gate.sh: --sha requires --files'
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || die 'gate.sh: cannot resolve script directory'
config_file="${GATE_CONFIG:-$script_dir/../forge.config.json}"
if [[ ! -f $config_file ]]; then
  $print_mode && { printf 'full\n'; exit 0; }
  die "gate.sh: missing config: $config_file"
fi

if [[ ! -d $repo ]]; then
  repo_candidates=("$repo")
  if [[ -n ${FORGE_WORKSPACE:-} ]]; then
    repo_candidates+=("$FORGE_WORKSPACE/$repo")
  fi
  config_workspace=$(python3 - "$config_file" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        workspace = json.load(handle).get("workspace", "")
except (OSError, json.JSONDecodeError) as exc:
    print(f"gate.sh: cannot read config: {exc}", file=sys.stderr)
    raise SystemExit(2)
print(workspace if isinstance(workspace, str) else "")
PY
  ) || exit 2
  if [[ -n $config_workspace ]]; then
    repo_candidates+=("$config_workspace/$repo")
  fi
  cwd_root=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null) || cwd_root=''
  if [[ -n $cwd_root ]]; then
    repo_candidates+=("$(dirname "$cwd_root")/$repo")
  fi
  resolved_repo=''
  tried=''
  for candidate in "${repo_candidates[@]}"; do
    tried="${tried}${tried:+, }$candidate"
    if [[ -d $candidate ]]; then
      resolved_repo=$candidate
      break
    fi
  done
  [[ -n $resolved_repo ]] || die "gate.sh: repository not found: $repo; candidates tried: $tried"
  repo=$resolved_repo
fi

repo=$(cd "$repo" 2>/dev/null && pwd -P) || die "gate.sh: cannot open repository: $repo"
git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || die "gate.sh: not a git repository: $repo"
common_raw=$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null) || die "gate.sh: cannot resolve repository metadata: $repo"
common_dir=$(python3 - "$repo" "$common_raw" <<'PY'
import os
import sys
path = sys.argv[2] if os.path.isabs(sys.argv[2]) else os.path.join(sys.argv[1], sys.argv[2])
print(os.path.realpath(path))
PY
) || die "gate.sh: cannot resolve repository metadata: $repo"
repo_git_dir=$(python3 - "$repo/.git" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
) || die "gate.sh: cannot resolve repository metadata: $repo"
common_checkout=$(dirname "$common_dir")
worktree_detected=false
if [[ $common_dir != "$repo_git_dir" || $repo == */.claude/worktrees/* || -n $sha ]]; then
  worktree_detected=true
fi

entry_file=''
if ! $print_mode; then
  mkdir -p "$run_dir" 2>/dev/null || die "gate.sh: cannot create run directory: $run_dir"
  run_dir=$(cd "$run_dir" 2>/dev/null && pwd -P) || die "gate.sh: cannot open run directory: $run_dir"

  state_prefix="$run_dir/.gate-$label"
  entry_file="$state_prefix-config.json"
  commands_file="$state_prefix-commands.nul"
  results_file="$state_prefix-results.tsv"
  files_file="$state_prefix-files.nul"
  trap 'rm -f "$state_prefix"-*' EXIT
  : >"$commands_file" || die "gate.sh: cannot write run directory: $run_dir"
  : >"$results_file" || die "gate.sh: cannot write run directory: $run_dir"
  : >"$files_file" || die "gate.sh: cannot write run directory: $run_dir"
fi

python3 - "$config_file" "$repo" "$common_checkout" "$worktree_detected" "$entry_file" "$print_mode" <<'PY'
import json
import os
import subprocess
import sys

config_path, repo, common_checkout, detected_raw, output_path, print_mode = sys.argv[1:]


def origin_url(path):
    try:
        completed = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    url = completed.stdout.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url
try:
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    print(f"gate.sh: cannot read config: {exc}", file=sys.stderr)
    raise SystemExit(2)

entries = {
    os.path.realpath(os.path.expanduser(path)): entry
    for path, entry in config.get("gate", {}).items()
}
repo_real = os.path.realpath(repo)
common_real = os.path.realpath(common_checkout)
matched_path = common_real if common_real in entries else repo_real if repo_real in entries else None
prefix_fallback = False
if matched_path is None:
    repo_name = os.path.basename(repo_real)
    repo_origin = origin_url(repo_real)
    if repo_origin is not None:
        for path in entries:
            if repo_name.startswith(f"{os.path.basename(path)}-"):
                candidate_origin = origin_url(path)
                if candidate_origin is not None and candidate_origin == repo_origin:
                    matched_path = path
                    prefix_fallback = True
                    break
if print_mode == "true":
    # A repo with no usable entry gets the default mode, so callers run their checks.
    entry = entries.get(matched_path) if matched_path is not None else None
    mode = entry.get("mode", "full") if isinstance(entry, dict) else "full"
    print(mode if mode in {"full", "none"} else "full")
    raise SystemExit(0)
if matched_path is None:
    print(f"gate.sh: unknown repository: {repo}", file=sys.stderr)
    raise SystemExit(2)

entry = entries[matched_path]
if not isinstance(entry, dict):
    print(f"gate.sh: incomplete gate config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
mode = entry.get("mode", "full")
if mode not in {"full", "none"}:
    print(f"gate.sh: invalid gate mode for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
required = {"tests", "lint", "typecheck", "migrations", "testPathRules", "semgrep"}
if mode == "full" and not required.issubset(entry):
    print(f"gate.sh: incomplete gate config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
if mode == "none":
    entry = {
        **entry,
        "tests": "",
        "lint": "",
        "typecheck": "",
        "migrations": "",
        "testPathRules": [],
        "semgrep": False,
        "parity": [],
    }
parity = entry.get("parity", [])
if not isinstance(parity, list) or not all(isinstance(command, str) for command in parity):
    print(f"gate.sh: invalid parity config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
env = entry.get("env", {})
if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
    print(f"gate.sh: invalid env config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
setup = entry.get("setup", "")
if not isinstance(setup, str):
    print(f"gate.sh: invalid setup config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
env_files = entry.get("envFiles", [])
if not isinstance(env_files, list) or not all(
    isinstance(path, str)
    and path
    and not os.path.isabs(path)
    and ".." not in path.replace("\\", "/").split("/")
    for path in env_files
):
    print(f"gate.sh: invalid envFiles config for repository: {repo}", file=sys.stderr)
    raise SystemExit(2)
for rule in entry["testPathRules"]:
    if "command" in rule and not isinstance(rule["command"], str):
        print(f"gate.sh: invalid testPathRules command for repository: {repo}", file=sys.stderr)
        raise SystemExit(2)

worktree_mode = detected_raw == "true" or prefix_fallback or "/.claude/worktrees/" in repo_real
selected = dict(entry)
overrides = entry.get("worktree")
overrides_applied = worktree_mode and isinstance(overrides, dict)
if overrides_applied:
    for key in ("tests", "lint", "typecheck", "migrations"):
        if key in overrides:
            selected[key] = overrides[key]
selected["_worktreeMode"] = worktree_mode
selected["_worktreeOverridesApplied"] = overrides_applied
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(selected, handle)
PY
config_status=$?
((config_status == 0)) || exit 2
$print_mode && exit 0

if $files_given; then
  if ((${#files[@]})); then
    for file in "${files[@]}"; do
      printf '%s\0' "$file" >>"$files_file"
    done
  fi
else
  python3 - "$repo" "$files_file" <<'PY'
import subprocess
import sys

repo, output_path = sys.argv[1:]
try:
    raw = subprocess.check_output(
        ["git", "-C", repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
except subprocess.CalledProcessError as exc:
    print(f"gate.sh: git status failed with exit {exc.returncode}", file=sys.stderr)
    raise SystemExit(2)

records = raw.split(b"\0")
paths = []
index = 0
while index < len(records):
    record = records[index]
    index += 1
    if len(record) < 4:
        continue
    status = record[:2]
    paths.append(record[3:])
    if b"R" in status or b"C" in status:
        index += 1
with open(output_path, "wb") as handle:
    for path in paths:
        handle.write(path + b"\0")
PY
  status_result=$?
  ((status_result == 0)) || exit 2
fi

python3 - "$repo" "$files_file" <<'PY'
import sys
from pathlib import Path

repo, files_path = sys.argv[1:]
repo_root = Path(repo).resolve()
with open(files_path, "rb") as handle:
    paths = [item for item in handle.read().split(b"\0") if item]
kept = []
for raw_path in paths:
    path = raw_path.decode("utf-8", "surrogateescape")
    candidate = Path(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts:
        continue
    try:
        (repo_root / candidate).resolve().relative_to(repo_root)
    except (OSError, RuntimeError, ValueError):
        continue
    kept.append(raw_path)
with open(files_path, "wb") as handle:
    for path in dict.fromkeys(kept):
        handle.write(path + b"\0")
PY
filter_status=$?
((filter_status == 0)) || exit 2

files=()
while IFS= read -r -d '' file; do
  files+=("$file")
done <"$files_file"

diff_command=(python3 "$script_dir/run_context.py" diff --run-dir "$run_dir" --repo "$repo" --label "$label")
if ((${#files[@]})); then
  diff_command+=(--files "${files[@]}")
fi
"${diff_command[@]}" >/dev/null || die 'gate.sh: cannot build diff'

gate_checkout=''
semgrep_base_rev=HEAD
if [[ -n $sha ]]; then
  git -C "$repo" cat-file -e "$sha^{commit}" 2>/dev/null || die "gate.sh: unknown commit: $sha"
  gate_checkout="$run_dir/gate-checkout"
  checkout_log="$run_dir/gate-$label-checkout.log"
  git -C "$repo" worktree prune >"$checkout_log" 2>&1 || die "gate.sh: git worktree prune failed; see $checkout_log"
  reuse_checkout=false
  if [[ -d $gate_checkout ]]; then
    checkout_top=$(git -C "$gate_checkout" rev-parse --show-toplevel 2>/dev/null) || checkout_top=''
    checkout_common=$(git -C "$gate_checkout" rev-parse --git-common-dir 2>/dev/null) || checkout_common=''
    if [[ -n $checkout_top && -n $checkout_common ]]; then
      reuse_checkout=$(python3 - "$gate_checkout" "$checkout_top" "$checkout_common" "$common_dir" <<'PY'
import os
import sys

checkout, top, common, repo_common = sys.argv[1:]
common = common if os.path.isabs(common) else os.path.join(checkout, common)
same_checkout = os.path.realpath(top) == os.path.realpath(checkout)
print("true" if same_checkout and os.path.realpath(common) == repo_common else "false")
PY
      ) || reuse_checkout=false
    fi
  fi
  # One checkout per run: moving it between SHAs keeps installed dependencies.
  if [[ $reuse_checkout == true ]]; then
    git -C "$gate_checkout" checkout --force --detach "$sha" >>"$checkout_log" 2>&1 \
      || die "gate.sh: cannot move gate checkout to $sha; see $checkout_log"
  else
    if [[ -e $gate_checkout ]]; then
      find "$gate_checkout" -mindepth 1 -delete && rmdir "$gate_checkout" \
        || die "gate.sh: cannot remove stale gate checkout: $gate_checkout"
    fi
    git -C "$repo" worktree add --detach "$gate_checkout" "$sha" >>"$checkout_log" 2>&1 \
      || die "gate.sh: cannot create gate checkout at $sha; see $checkout_log"
  fi
  python3 - "$entry_file" "$repo" "$gate_checkout" "$sha" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

entry_path, source, target, sha = sys.argv[1:]
with open(entry_path, encoding="utf-8") as handle:
    env_files = json.load(handle).get("envFiles", [])
for relative in env_files:
    # A tracked copy from the primary worktree would replace the committed version being gated.
    tracked = subprocess.run(
        ["git", "-C", source, "ls-files", "--error-unmatch", "--", f":(literal){relative}"],
        capture_output=True,
    ).returncode == 0
    in_commit = subprocess.run(
        ["git", "-C", source, "cat-file", "-e", f"{sha}:./{relative}"],
        capture_output=True,
    ).returncode == 0
    if tracked or in_commit:
        where = f"tracked in {source}" if tracked else f"present in commit {sha}"
        print(f"gate.sh: envFiles entry {relative} is {where}; envFiles may list only untracked files", file=sys.stderr)
        raise SystemExit(2)
    origin = Path(source) / relative
    if not origin.is_file():
        continue
    destination = Path(target) / relative
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    except OSError as exc:
        print(f"gate.sh: cannot copy envFiles entry {relative}: {exc.strerror}", file=sys.stderr)
        raise SystemExit(2)
PY
  (( $? == 0 )) || exit 2
  # Semgrep compares against the run's starting commit, since HEAD in the checkout is the SHA itself.
  semgrep_base_rev=$(python3 - "$run_dir/baseline.json" "$sha" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        head = json.load(handle).get("head") or ""
except (OSError, json.JSONDecodeError):
    head = ""
print(head or f"{sys.argv[2]}^")
PY
  ) || die 'gate.sh: cannot read the run baseline'
  repo=$gate_checkout
fi

config_value() {
  python3 - "$entry_file" "$1" "${2-}" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle).get(sys.argv[2], sys.argv[3])
if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, list):
    print(json.dumps(value, separators=(",", ":")))
elif isinstance(value, dict):
    print(json.dumps(value, separators=(",", ":")))
else:
    print(value)
PY
}

timeout_for() {
  python3 - "$entry_file" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
default = 900 if sys.argv[2] == "tests" else 300
print(config.get("timeoutSeconds", {}).get(sys.argv[2], default))
PY
}

record_command() {
  printf '%s\0' "$1" >>"$commands_file"
}

repo_command_prefix=$(python3 - "$entry_file" <<'PY'
import json
import shlex
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    entry = json.load(handle)
parts = [f"export {key}={shlex.quote(value)}" for key, value in sorted(entry.get("env", {}).items())]
setup = entry.get("setup", "").strip()
if setup:
    parts.append(setup)
print("; ".join(parts))
PY
) || die 'gate.sh: cannot read repo command context'

wrap_repo_command() {
  if [[ -n $repo_command_prefix ]]; then
    printf '%s && %s' "$repo_command_prefix" "$1"
  else
    printf '%s' "$1"
  fi
}

run_tool() {
  local tool=$1
  local command=$2
  local timeout_seconds=$3
  local log="$run_dir/gate-$label-$tool.log"
  local log_name=${4:-$tool}
  log="$run_dir/gate-$label-$log_name.log"
  local result
  record_command "$command"
  local wrapped
  wrapped=$(wrap_repo_command "$command")
  (cd "$repo" && perl -e 'alarm shift @ARGV; exec @ARGV' "$timeout_seconds" bash -c "$wrapped") >"$log" 2>&1
  result=$?
  printf '%s\t%s\t%s\t%s\n' "$tool" "$result" "$timeout_seconds" "$log" >>"$results_file"
}

run_parity() {
  local index=$1
  local command=$2
  local timeout_seconds
  local log="$run_dir/gate-$label-parity-$index.log"
  local result
  local summary_log="$state_prefix-parity-$index-summary.log"
  timeout_seconds=$(timeout_for parity) || die 'gate.sh: cannot read parity timeout'
  record_command "$command"
  local wrapped
  wrapped=$(wrap_repo_command "$command")
  (cd "$repo" && perl -e 'alarm shift @ARGV; exec @ARGV' "$timeout_seconds" bash -c "$wrapped") >"$log" 2>&1
  result=$?
  if ((result == 0)); then
    printf '%s\t%s\t%s\t%s\n' parity 0 "$timeout_seconds" "$log" >>"$results_file"
    return
  fi
  python3 - "$command" "$result" "$log" "$summary_log" <<'PY'
import sys

command, status, log_path, summary_path = sys.argv[1:]
last = ""
with open(log_path, encoding="utf-8", errors="replace") as handle:
    for line in handle:
        if line.strip():
            last = line.strip()
with open(summary_path, "w", encoding="utf-8") as handle:
    handle.write(f"{command} (exit {status}): {last[:160]}\n")
PY
  printf '%s\t%s\t%s\t%s\n' parity "$result" "$timeout_seconds" "$summary_log" >>"$results_file"
}

attempt_tool() {
  local tool=$1
  local command=$2
  local timeout_seconds=$3
  local log="$run_dir/gate-$label-$tool.log"
  record_command "$command"
  local wrapped
  wrapped=$(wrap_repo_command "$command")
  (cd "$repo" && perl -e 'alarm shift @ARGV; exec @ARGV' "$timeout_seconds" bash -c "$wrapped") >"$log" 2>&1
}

record_failure() {
  local tool=$1
  local summary=$2
  local log="$run_dir/gate-$label-$tool.log"
  printf '%s\n' "$summary" >"$log"
  printf '%s\t1\t0\t%s\n' "$tool" "$log" >>"$results_file"
}

record_warning() {
  local tool=$1
  local summary=$2
  local log="$run_dir/gate-$label-$tool-warning.log"
  printf '%s\n' "$summary" >"$log"
  printf '%s\twarning\t0\t%s\n' "$tool" "$log" >>"$results_file"
}

run_configured_tool() {
  local tool=$1
  local command=$2
  local extensions_key=$3
  local timeout_seconds
  local selected_file="$state_prefix-$tool-paths.nul"
  local selected=()
  local path_args=''
  local expanded
  local extensions_label
  [[ -n $command ]] || return 0
  timeout_seconds=$(timeout_for "$tool") || die "gate.sh: cannot read $tool timeout"
  if [[ $command != *'<paths>'* ]]; then
    run_tool "$tool" "$command" "$timeout_seconds"
    return 0
  fi
  python3 - "$repo" "$entry_file" "$extensions_key" "$files_file" "$selected_file" <<'PY'
import json
import os
import sys

repo, config_path, extensions_key, files_path, output_path = sys.argv[1:]
with open(config_path, encoding="utf-8") as handle:
    extensions = set(json.load(handle).get(extensions_key, []))
with open(files_path, "rb") as handle:
    files = [item.decode("utf-8", "surrogateescape") for item in handle.read().split(b"\0") if item]
with open(output_path, "wb") as handle:
    for path in files:
        if os.path.isfile(os.path.join(repo, path)) and os.path.splitext(path)[1].lower() in extensions:
            handle.write(path.encode("utf-8", "surrogateescape") + b"\0")
PY
  while IFS= read -r -d '' path; do
    selected+=("$path")
  done <"$selected_file"
  if ((${#selected[@]} == 0)); then
    extensions_label=$(python3 - "$entry_file" "$extensions_key" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    extensions = [item.lstrip(".") for item in json.load(handle).get(sys.argv[2], [])]
print(f"*.{extensions[0]}" if len(extensions) == 1 else "*.{" + ",".join(extensions) + "}")
PY
)
    record_command "$tool skipped: no changed $extensions_label"
    return 0
  fi
  for path in "${selected[@]}"; do
    path_args+=" $(shell_quote "$path")"
  done
  path_args=${path_args# }
  expanded="${command//<paths>/"$path_args"}"
  run_tool "$tool" "$expanded" "$timeout_seconds"
}

lint_command=$(config_value lint) || die 'gate.sh: cannot read lint config'
typecheck_command=$(config_value typecheck) || die 'gate.sh: cannot read typecheck config'
migrations_command=$(config_value migrations) || die 'gate.sh: cannot read migrations config'
tests_command=$(config_value tests) || die 'gate.sh: cannot read tests config'
create_db_arg=''
if ((${#files[@]})); then
  for changed_file in "${files[@]}"; do
    if [[ $changed_file == */migrations/*.py ]]; then
      create_db_arg=' --create-db'
      break
    fi
  done
fi
tests_command=${tests_command//<create-db>/$create_db_arg}
parity_commands_file="$state_prefix-parity-commands.nul"
python3 - "$entry_file" "$parity_commands_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    commands = json.load(handle).get("parity", [])
with open(sys.argv[2], "wb") as handle:
    for command in commands:
        handle.write(command.encode("utf-8") + b"\0")
PY
(( $? == 0 )) || die 'gate.sh: cannot read parity config'
parity_commands=()
while IFS= read -r -d '' command; do
  parity_commands+=("$command")
done <"$parity_commands_file"
semgrep_enabled=$(config_value semgrep) || die 'gate.sh: cannot read semgrep config'
semgrep_config=$(config_value semgrepConfig auto) || die 'gate.sh: cannot read Semgrep config'
diff_exclude=$(config_value diffExclude '[]') || die 'gate.sh: cannot read diff exclude config'
worktree_mode=$(config_value _worktreeMode) || die 'gate.sh: cannot read worktree mode'
worktree_overrides=$(config_value _worktreeOverridesApplied) || die 'gate.sh: cannot read worktree config'

if [[ $worktree_mode == true && $no_stages != true ]]; then
  record_command 'mode: worktree'
  if [[ $worktree_overrides != true ]]; then
    worktree_warning='warning: worktree without worktree commands; docker forms may target the main checkout'
    record_command "$worktree_warning"
    if [[ "$tests_command $lint_command $typecheck_command $migrations_command" == *'docker exec'* ]]; then
      record_failure gate.sh "$worktree_warning"
    fi
  fi
fi

stage_enabled lint && run_configured_tool lint "$lint_command" lintExtensions
stage_enabled typecheck && run_configured_tool typecheck "$typecheck_command" typecheckExtensions
if stage_enabled migrations && [[ -n $migrations_command ]]; then
  run_tool migrations "$migrations_command" "$(timeout_for migrations)"
fi

if ! stage_enabled tests; then
  :
elif $skip_tests; then
  record_command 'tests skipped'
elif [[ -z $tests_command ]]; then
  record_command 'tests skipped by config'
else
  test_commands_file="$state_prefix-test-commands.nul"
  python3 - "$repo" "$entry_file" "$files_file" "$test_commands_file" "$tests_command" "$create_db_arg" <<'PY'
import fnmatch
import json
import os
import shlex
import sys

repo, config_path, files_path, output_path, default_command, create_db_arg = sys.argv[1:]
with open(config_path, encoding="utf-8") as handle:
    test_config = json.load(handle)
rules = test_config["testPathRules"]
root_tests_fallback = bool(test_config.get("rootTestsFallback", False))
with open(files_path, "rb") as handle:
    files = [item.decode("utf-8", "surrogateescape") for item in handle.read().split(b"\0") if item]

source_suffixes = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}
groups = {}


def add_target(command, target):
    targets = groups.setdefault(command.replace("<create-db>", create_db_arg), [])
    if target and target not in targets:
        targets.append(target)


for path in files:
    normalized = path.replace(os.sep, "/").removeprefix("./")
    full_path = os.path.join(repo, normalized)
    if not os.path.exists(full_path):
        continue
    if "/tests/" in f"/{normalized}" or os.path.basename(normalized).startswith("test_"):
        add_target(default_command, normalized)
        continue
    if os.path.splitext(normalized)[1] not in source_suffixes:
        continue
    matched = False
    for rule in rules:
        pattern = str(rule.get("match", ""))
        if normalized.startswith(pattern) or fnmatch.fnmatch(normalized, pattern):
            target = str(rule.get("tests", "")).strip()
            if target.startswith("-k ") or (target and os.path.exists(os.path.join(repo, target))):
                add_target(str(rule.get("command", default_command)), target)
            matched = True
    if matched:
        continue
    parent = os.path.dirname(normalized)
    while parent not in ("", "."):
        candidate = os.path.join(parent, "tests")
        if os.path.isdir(os.path.join(repo, candidate)):
            add_target(default_command, candidate.replace(os.sep, "/"))
            break
        parent = os.path.dirname(parent)
    else:
        if root_tests_fallback and os.path.isdir(os.path.join(repo, "tests")):
            add_target(default_command, "tests")

with open(output_path, "wb") as handle:
    for command, targets in groups.items():
        path_args = []
        for target in targets:
            if target.startswith("-k "):
                path_args.extend(["-k", target[3:]])
            else:
                path_args.append(target)
        paths = " ".join(shlex.quote(item) for item in path_args)
        expanded = command.replace("<paths>", paths)
        handle.write(expanded.encode("utf-8", "surrogateescape") + b"\0")
PY
  target_status=$?
  ((target_status == 0)) || die 'gate.sh: cannot select targeted tests'
  test_commands=()
  while IFS= read -r -d '' test_command; do
    test_commands+=("$test_command")
  done <"$test_commands_file"
  if ((${#test_commands[@]} == 0)); then
    record_command 'tests skipped: no matching targeted tests'
  else
    test_index=0
    for test_command in "${test_commands[@]}"; do
      ((test_index += 1))
      run_tool tests "$test_command" "$(timeout_for tests)" "tests-$test_index"
    done
  fi
fi

semgrep_files=()
if ((${#files[@]})); then
  for file in "${files[@]}"; do
    [[ -f "$repo/$file" ]] && semgrep_files+=("$file")
  done
fi
semgrep_bin="${GATE_SEMGREP_BIN:-semgrep}"
if stage_enabled semgrep && [[ $semgrep_enabled == true ]]; then
  if ! command -v "$semgrep_bin" >/dev/null 2>&1; then
    record_command 'semgrep skipped: binary not found'
  elif ((${#semgrep_files[@]} == 0)); then
    record_command 'semgrep skipped: no changed files'
  else
    if [[ $semgrep_config != auto && $semgrep_config != p/* && $semgrep_config != r/* && $semgrep_config != /* && -e "$repo/$semgrep_config" ]]; then
      semgrep_config=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$repo/$semgrep_config")
    fi
    semgrep_paths=''
    semgrep_base_paths=''
    semgrep_base_dir="$run_dir/gate-$label-semgrep-base"
    semgrep_current_json="$run_dir/gate-$label-semgrep-current.json"
    semgrep_base_json="$run_dir/gate-$label-semgrep-base.json"
    semgrep_new_json="$run_dir/gate-$label-semgrep-new.json"
    mkdir -p "$semgrep_base_dir" || die 'gate.sh: cannot create Semgrep baseline directory'
    find "$semgrep_base_dir" -mindepth 1 -delete || die 'gate.sh: cannot clear Semgrep baseline directory'
    for file in "${semgrep_files[@]}"; do
      semgrep_paths+=" $(shell_quote "$file")"
      if git -C "$repo" cat-file -e "$semgrep_base_rev:$file" 2>/dev/null; then
        mkdir -p "$semgrep_base_dir/$(dirname "$file")" || die 'gate.sh: cannot create Semgrep baseline path'
        git -C "$repo" show "$semgrep_base_rev:$file" >"$semgrep_base_dir/$file" || die "gate.sh: cannot read $semgrep_base_rev:$file"
        semgrep_base_paths+=" $(shell_quote "$file")"
      fi
    done
    semgrep_paths=${semgrep_paths# }
    semgrep_base_paths=${semgrep_base_paths# }
    registry_command="$(shell_quote "$semgrep_bin") --json --quiet --config $(shell_quote "$semgrep_config") $semgrep_paths >$(shell_quote "$semgrep_current_json")"
    registry_status=0
    attempt_tool semgrep-registry "$registry_command" 120 || registry_status=$?
    semgrep_log="$run_dir/gate-$label-semgrep-registry.log"
    semgrep_use_inline=false
    if ((registry_status <= 1)) && [[ -n $semgrep_base_paths ]]; then
      registry_base_command="cd $(shell_quote "$semgrep_base_dir") && $(shell_quote "$semgrep_bin") --json --quiet --config $(shell_quote "$semgrep_config") $semgrep_base_paths >$(shell_quote "$semgrep_base_json")"
      registry_base_status=0
      attempt_tool semgrep-registry-base "$registry_base_command" 120 || registry_base_status=$?
      ((registry_base_status <= 1)) || semgrep_use_inline=true
    elif ((registry_status > 1)); then
      semgrep_use_inline=true
    else
      printf '{"results":[]}\n' >"$semgrep_base_json"
    fi
    if $semgrep_use_inline; then
      record_command 'semgrep: registry unavailable, inline rules only'
      semgrep_rules="$state_prefix-semgrep-rules.json"
      python3 - "$semgrep_rules" <<'PY'
import json
import sys

rules = {
    "rules": [
        {
            "id": "forge-security-hardcoded-private-key",
            "languages": ["generic"],
            "message": "Private key material must not be committed",
            "severity": "ERROR",
            "pattern-regex": "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        },
        {
            "id": "forge-python-eval",
            "languages": ["python"],
            "message": "Avoid eval on application input",
            "severity": "WARNING",
            "pattern": "eval(...)",
        },
    ]
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(rules, handle)
PY
      inline_command="$(shell_quote "$semgrep_bin") --json --quiet --config $(shell_quote "$semgrep_rules") $semgrep_paths >$(shell_quote "$semgrep_current_json")"
      inline_status=0
      attempt_tool semgrep "$inline_command" 120 || inline_status=$?
      semgrep_log="$run_dir/gate-$label-semgrep.log"
      if ((inline_status <= 1)) && [[ -n $semgrep_base_paths ]]; then
        inline_base_command="cd $(shell_quote "$semgrep_base_dir") && $(shell_quote "$semgrep_bin") --json --quiet --config $(shell_quote "$semgrep_rules") $semgrep_base_paths >$(shell_quote "$semgrep_base_json")"
        inline_base_status=0
        attempt_tool semgrep-base "$inline_base_command" 120 || inline_base_status=$?
        ((inline_base_status <= 1)) || inline_status=$inline_base_status
      elif ((inline_status <= 1)); then
        printf '{"results":[]}\n' >"$semgrep_base_json"
      fi
      if ((inline_status > 1)); then
        printf '%s\t%s\t120\t%s\n' semgrep "$inline_status" "$semgrep_log" >>"$results_file"
        continue_semgrep=false
      else
        continue_semgrep=true
      fi
    else
      continue_semgrep=true
    fi
    if $continue_semgrep; then
      semgrep_comparison="$state_prefix-semgrep-comparison.txt"
      if python3 - "$semgrep_current_json" "$semgrep_base_json" "$semgrep_new_json" "$repo" "$semgrep_base_dir" "$semgrep_comparison" <<'PY'
import collections
import fnmatch
import json
import os
import sys

current_path, baseline_path, new_path, repo, baseline_dir, comparison_path = sys.argv[1:]


def load_results(path):
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return document.get("results", [])


def relative_path(path, root):
    if os.path.isabs(path):
        path = os.path.relpath(path, root)
    path = path.replace(os.sep, "/")
    return path[2:] if path.startswith("./") else path


def finding_key(finding, root):
    extra = finding.get("extra") or {}
    lines = " ".join(str(extra.get("lines", "")).split())
    return finding.get("check_id", ""), relative_path(finding.get("path", ""), root), lines


current = load_results(current_path)
baseline = load_results(baseline_path)
baseline_counts = collections.Counter(finding_key(finding, baseline_dir) for finding in baseline)
new_findings = []
pre_existing = 0
for finding in current:
    key = finding_key(finding, repo)
    if baseline_counts[key]:
        baseline_counts[key] -= 1
        pre_existing += 1
    else:
        new_findings.append(finding)


def is_test_path(path):
    parts = path.split("/")
    name = os.path.basename(path)
    return (
        any(part in {"tests", "test", "e2e"} for part in parts[:-1])
        or name.startswith("test_") and name.endswith(".py")
        or name.endswith("_test.py")
        or fnmatch.fnmatch(name, "*.spec.*")
        or fnmatch.fnmatch(name, "*.test.*")
    )


blocking = []
warning_findings = []
for finding in new_findings:
    check_id = str(finding.get("check_id", ""))
    path = relative_path(finding.get("path", ""), repo)
    severity = str((finding.get("extra") or {}).get("severity", "")).upper()
    if severity == "ERROR" and "security" in check_id.lower() and not is_test_path(path):
        blocking.append(finding)
    else:
        warning_findings.append(finding)

with open(new_path, "w", encoding="utf-8") as handle:
    json.dump({"results": new_findings}, handle, ensure_ascii=True, separators=(",", ":"))
    handle.write("\n")

with open(comparison_path, "w", encoding="utf-8") as handle:
    handle.write(
        f"{len(current)} {pre_existing} {len(new_findings)} "
        f"{len(blocking)} {len(warning_findings)}\n"
    )
    for category, findings in (("BLOCK", blocking), ("WARN", warning_findings)):
        for finding in findings[:15]:
            check_id = finding.get("check_id", "")
            path = relative_path(finding.get("path", ""), repo)
            line = (finding.get("start") or {}).get("line", "?")
            handle.write(f"{category}\t{check_id} {path}:{line}\n")
PY
      then
        read -r semgrep_total semgrep_pre_existing semgrep_new semgrep_blocking semgrep_warnings <"$semgrep_comparison"
        record_command "semgrep: $semgrep_total findings, $semgrep_pre_existing pre-existing at HEAD, $semgrep_new new"
        if ((semgrep_blocking > 0)); then
          semgrep_failure=$(sed -n $'s/^BLOCK\t//p' "$semgrep_comparison")
          record_failure semgrep "$semgrep_failure"
        else
          printf '%s\t0\t120\t%s\n' semgrep "$semgrep_log" >>"$results_file"
        fi
        if ((semgrep_warnings > 0)); then
          semgrep_warning=$(sed -n $'s/^WARN\t//p' "$semgrep_comparison")
          record_warning semgrep "$semgrep_warning"
        fi
      else
        record_failure semgrep 'semgrep: could not compare current findings with HEAD'
      fi
    fi
  fi
fi

parity_index=0
if stage_enabled parity && ((${#parity_commands[@]})); then
  for parity_command in "${parity_commands[@]}"; do
    ((parity_index += 1))
    run_parity "$parity_index" "$parity_command"
  done
fi

result_path="$run_dir/gate-$label.json"
diff_path="$run_dir/gate-$label.diff"
python3 - "$repo" "$files_given" "$files_file" "$commands_file" "$results_file" "$result_path" "$diff_path" "$diff_exclude" "$commit_message" "$push" "$only_stages" "$gate_checkout" <<'PY'
import fnmatch
import json
import os
import re
import subprocess
import sys

(
    repo,
    files_given_raw,
    files_path,
    commands_path,
    results_path,
    result_path,
    diff_path,
    diff_exclude_raw,
    commit_message,
    push_raw,
    only_stages_raw,
    gate_checkout,
) = sys.argv[1:]
files_given = files_given_raw == "true"
push = push_raw == "true"
diff_exclude = json.loads(diff_exclude_raw)
if not isinstance(diff_exclude, list):
    diff_exclude = []
DIFF_INLINE_CAP = 40000
with open(files_path, "rb") as handle:
    files = [item.decode("utf-8", "surrogateescape") for item in handle.read().split(b"\0") if item]
with open(commands_path, "rb") as handle:
    commands = [item.decode("utf-8", "replace") for item in handle.read().split(b"\0") if item]

failures = []
warnings = []
checkout_prefix = gate_checkout.rstrip("/") + "/" if gate_checkout else ""


def repository_relative(text):
    # Fixers work in the primary worktree, so gate-checkout paths must not reach them.
    return text.replace(checkout_prefix, "") if checkout_prefix else text


def failure_location(tool, log_text):
    if tool == "tests":
        failed = re.search(r"^FAILED\s+([^:\s]+)::", log_text, re.MULTILINE)
        if failed:
            file = failed.group(1)
            traceback = re.search(rf"^{re.escape(file)}:(\d+):", log_text, re.MULTILINE)
            return file, int(traceback.group(1)) if traceback else None
    location = re.search(
        r"(?:^|\s)([A-Za-z0-9_./-]+\.[A-Za-z0-9]+):(\d+)(?::\d+)?(?::|\s|$)",
        log_text,
        re.MULTILINE,
    )
    if location:
        return location.group(1), int(location.group(2))
    return None, None


with open(results_path, encoding="utf-8") as handle:
    for row in handle:
        tool, status, timeout_seconds, log_path = row.rstrip("\n").split("\t", 3)
        if status == "0":
            continue
        if status == "warning":
            try:
                with open(log_path, encoding="utf-8", errors="replace") as log:
                    summary = repository_relative(log.read().strip())
            except OSError as exc:
                summary = f"warning log unavailable: {exc}"
            warnings.append({"tool": tool, "summary": summary[-2048:]})
            continue
        if status == "142":
            summary = f"timed out after {timeout_seconds} s"
            log_text = summary
        else:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as log:
                    log_text = repository_relative(log.read())
                lines = log_text.splitlines(keepends=True)[-25:]
                while lines and lines[0].strip() in {"", "|"}:
                    lines.pop(0)
                summary = "".join(lines).strip()
            except OSError as exc:
                log_text = f"command exited {status}; log unavailable: {exc}"
                summary = f"command exited {status}; log unavailable: {exc}"
            if not summary:
                summary = f"command exited {status}"
        summary = summary[-2048:]
        file, line = failure_location(tool, log_text)
        failures.append({"tool": tool, "summary": summary, "file": file, "line": line})

all_stages = ["lint", "typecheck", "migrations", "tests", "semgrep", "parity"]
requested_stages = set(filter(None, only_stages_raw.split(",")))
skipped = [stage for stage in all_stages if requested_stages and stage not in requested_stages]
result = {
    "passed": not failures,
    "failures": failures,
    "warnings": warnings,
    "skipped": skipped,
    "commands": commands,
    "commit": None,
}
if files_given:
    result["files"] = files
    excluded = []
    for path in files:
        if any(fnmatch.fnmatch(path, pattern) for pattern in diff_exclude):
            excluded.append(path)
    result["diffExcluded"] = excluded

with open(diff_path, "rb") as handle:
    diff = handle.read()
result["diffPath"] = diff_path
result["diffBytes"] = len(diff)
diff_text = diff.decode("utf-8", errors="replace")
result["diff"] = diff_text[:DIFF_INLINE_CAP]
result["diffTruncated"] = len(diff_text) > DIFF_INLINE_CAP

commit_error = ""
if not failures and commit_message:
    dropped = []
    result["commit"] = {"sha": None, "pushed": False, "error": "", "dropped": dropped}

    def command_error(prefix, completed):
        detail = " ".join((completed.stderr or completed.stdout or "").split())
        return f"{prefix}: {detail or 'command failed'}"[:2048]

    branch = subprocess.run(
        ["git", "-C", repo, "branch", "--show-current"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if branch.returncode != 0:
        commit_error = command_error("cannot determine current branch", branch)
    branch_name = branch.stdout.strip()
    if not commit_error and branch_name in {"develop", "main", "master"}:
        commit_error = f"refusing to commit on protected branch {branch_name}"

    def path_location(path):
        if os.path.lexists(os.path.join(repo, path)):
            return "worktree"
        indexed = subprocess.run(
            ["git", "-C", repo, "ls-files", "--error-unmatch", "--", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if indexed.returncode == 0:
            return "worktree"
        in_head = subprocess.run(
            ["git", "-C", repo, "ls-tree", "-r", "--name-only", "HEAD", "--", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if in_head.returncode == 0 and in_head.stdout.strip():
            return "head"
        return None

    # HEAD-only paths are deletions already staged with `git rm`; `git add` would reject them.
    stage_files = []
    head_only_files = []
    if not commit_error:
        for entry in files:
            path, location = entry, path_location(entry)
            if location is None:
                # Implementers sometimes annotate entries, as in "gone/ (3 files removed)".
                annotated = re.match(r"^(.*\S)\s+\([^()]*\)$", entry)
                if annotated:
                    path, location = annotated.group(1), path_location(annotated.group(1))
            if location is None:
                print(
                    f"gate.sh: dropped --files entry {entry}: matches no file on disk, in the index, or in HEAD",
                    file=sys.stderr,
                )
                dropped.append(entry)
                continue
            parts = path.replace("\\", "/").split("/")
            if ".envs" in parts or fnmatch.fnmatch(os.path.basename(path), "*.env*"):
                continue
            ignored = subprocess.run(
                ["git", "-C", repo, "check-ignore", "--quiet", "--no-index", "--", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if ignored.returncode == 0:
                continue
            (head_only_files if location == "head" else stage_files).append(path)
        # A rerun after a deletion-only commit drops every entry, so HEAD adoption is still checked below.
        if not stage_files and not head_only_files and not dropped:
            commit_error = "no committable --files paths remain after safety filters"
    commit_paths = stage_files + head_only_files

    if not commit_error and stage_files:
        staged = subprocess.run(
            ["git", "-C", repo, "add", "--", *stage_files],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if staged.returncode != 0:
            commit_error = command_error("staging failed", staged)

    head_adopted = False
    if not commit_error:
        # With no paths, `git diff --cached` would inspect the whole index, so it is skipped.
        changed = subprocess.run(
            ["git", "-C", repo, "diff", "--cached", "--quiet", "--", *commit_paths],
            check=False,
        ) if commit_paths else None
        if changed is None or changed.returncode == 0:
            # A rerun after an interrupted report finds its own commit already at HEAD.
            head_subject = subprocess.run(
                ["git", "-C", repo, "log", "-1", "--format=%s"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            if head_subject.returncode == 0 and head_subject.stdout.rstrip("\n") == commit_message:
                head_adopted = True
                print("gate.sh: nothing staged; HEAD already carries this commit message, reporting HEAD", file=sys.stderr)
            else:
                commit_error = "no staged changes to commit" if commit_paths else "no committable --files paths remain after safety filters"

    if not commit_error and not head_adopted:
        committed = subprocess.run(
            ["git", "-C", repo, "commit", "-m", commit_message, "--", *commit_paths],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if committed.returncode != 0:
            rewritten = subprocess.run(
                ["git", "-C", repo, "diff", "--quiet", "--", *commit_paths],
                check=False,
            )
            # A pre-commit hook that rewrote files fails the first attempt; stage its edits and retry once.
            if rewritten.returncode == 1 and stage_files:
                restaged = subprocess.run(
                    ["git", "-C", repo, "add", "--", *stage_files],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if restaged.returncode == 0:
                    committed = subprocess.run(
                        ["git", "-C", repo, "commit", "-m", commit_message, "--", *commit_paths],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
        if committed.returncode != 0:
            commit_error = command_error("commit failed", committed)

    sha = ""
    if not commit_error:
        resolved = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if resolved.returncode != 0:
            commit_error = command_error("cannot read committed sha", resolved)
        else:
            sha = resolved.stdout.strip()

    if not commit_error and push:
        pushed = subprocess.run(
            ["git", "-C", repo, "push", "-u", "origin", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if pushed.returncode != 0:
            commit_error = command_error("push failed", pushed)

    result["commit"] = {
        "sha": None if commit_error else sha,
        "pushed": push and not commit_error,
        "error": commit_error,
        "dropped": dropped,
    }

encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":"))
with open(result_path, "w", encoding="utf-8") as handle:
    handle.write(encoded + "\n")
print(encoded)
if commit_error:
    print(f"gate.sh: {commit_error}", file=sys.stderr)
    raise SystemExit(2)
PY
final_status=$?
((final_status == 2)) && exit 2
((final_status == 0)) || die 'gate.sh: cannot build result JSON'
exit 0
