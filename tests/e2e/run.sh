#!/bin/sh
set -eu
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
mkdir -p "$tmp_dir/bin"
printf '#!/bin/sh\nexit 0\n' > "$tmp_dir/bin/claude"
chmod +x "$tmp_dir/bin/claude"
PATH="$tmp_dir/bin:$PATH" python3 install.py install --profile tests/fixtures/profiles/public-default.json --yes --home "$tmp_dir/.claude" --layers-root "$tmp_dir/.ai-setup"
PATH="$tmp_dir/bin:$PATH" python3 install.py doctor --selfcheck --json --home "$tmp_dir/.claude" --layers-root "$tmp_dir/.ai-setup"
