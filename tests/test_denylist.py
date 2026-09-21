from __future__ import annotations

from aisetup.cli import main
from aisetup.denylist import scan_tree


def test_denylist_reports_seeded_path_and_line(tmp_path):
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("private-brand\n", encoding="utf-8")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "example.txt").write_text("safe\nPRIVATE-BRAND value\n", encoding="utf-8")

    result = main(["doctor", "--denylist", str(denylist), "--root", str(root)])

    assert result == 1


def test_denylist_cli_prints_path_and_line(tmp_path, capsys):
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("private-brand\n", encoding="utf-8")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "example.txt").write_text("safe\nPRIVATE-BRAND value\n", encoding="utf-8")

    main(["doctor", "--denylist", str(denylist), "--root", str(root)])

    assert capsys.readouterr().out == "example.txt:2: private-brand\n"


def test_denylist_clean_tree_passes(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "example.txt").write_text("safe\n", encoding="utf-8")

    denylist = tmp_path / "denylist.txt"
    denylist.write_text("private-brand\n", encoding="utf-8")

    assert main(["doctor", "--denylist", str(denylist), "--root", str(root)]) == 0


def test_denylist_always_scans_token_shapes(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    token = "sk-" + "abcdefgh"
    (root / "example.txt").write_text(f"token {token}\n", encoding="utf-8")

    hits = scan_tree(root)

    assert hits[0].entry == token


def test_denylist_skips_dependency_and_cache_directories(tmp_path):
    root = tmp_path / "tree"
    for directory in (".venv", "node_modules", "__pycache__", ".pytest_cache"):
        path = root / directory
        path.mkdir(parents=True)
        (path / "example.txt").write_text("sk-" + "abcdefgh\n", encoding="utf-8")

    assert scan_tree(root) == []
