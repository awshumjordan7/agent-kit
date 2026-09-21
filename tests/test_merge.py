from aisetup.merge import deep_merge


def test_hooks_concatenate_in_layer_order_without_deduplication():
    hook_a = {"matcher": "A", "hooks": [{"type": "command", "command": "a"}]}
    hook_b = {"matcher": "B", "hooks": [{"type": "command", "command": "b"}]}

    merged = deep_merge(
        {"hooks": {"Stop": [hook_a]}},
        {"hooks": {"Stop": [hook_a, hook_b]}},
    )

    assert merged["hooks"]["Stop"] == [hook_a, hook_a, hook_b]


def test_permissions_union_preserves_first_seen_order():
    merged = deep_merge(
        {"permissions": {"allow": ["Read", "Write"], "deny": ["Bash(rm:*)"]}},
        {"permissions": {"allow": ["Write", "Agent"], "deny": ["Bash(sudo:*)"]}},
    )

    assert merged["permissions"]["allow"] == ["Read", "Write", "Agent"]
    assert merged["permissions"]["deny"] == ["Bash(rm:*)", "Bash(sudo:*)"]


def test_later_scalar_wins():
    merged = deep_merge(
        {"theme": "light", "nested": {"value": 1}}, {"theme": "dark", "nested": {"value": 2}}
    )

    assert merged == {"theme": "dark", "nested": {"value": 2}}
