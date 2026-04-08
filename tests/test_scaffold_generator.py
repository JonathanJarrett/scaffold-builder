from pathlib import Path
import datetime as dt
import json

import pytest

import scaffold_generator as sg


def write_structure_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "structure.txt"
    path.write_text(content, encoding="utf-8")
    return path


def test_normalize_language_accepts_aliases():
    assert sg.normalize_language("python") == "python"
    assert sg.normalize_language("promptfile") == "promptfile"
    assert sg.normalize_language("C#") == "csharp"
    assert sg.normalize_language("cs") == "csharp"


def test_normalize_language_rejects_unknown():
    with pytest.raises(sg.ScaffoldError):
        sg.normalize_language("ruby")


def test_planned_branch_name_format():
    fixed = dt.datetime(2026, 3, 14, 9, 8, 7)
    assert sg.planned_branch_name(fixed) == "Generator_20260314_090807"


def test_strip_root_line_removes_single_root_marker():
    lines = [
        "prompt-repo/",
        "├─ Promptfile.yaml",
        "└─ dist/",
    ]
    stripped = sg.strip_root_line(lines)
    assert stripped == [
        "├─ Promptfile.yaml",
        "└─ dist/",
    ]


def test_parse_tree_line_file():
    depth, name, is_dir = sg.parse_tree_line("├─ build_prompt.py")
    assert depth == 0
    assert name == "build_prompt.py"
    assert is_dir is False


def test_parse_tree_line_nested_directory():
    depth, name, is_dir = sg.parse_tree_line("│  └─ formatting/")
    assert depth == 1
    assert name == "formatting"
    assert is_dir is True


def test_parse_tree_file_parses_sample_structure(tmp_path: Path):
    structure = """prompt-repo/
├─ Promptfile.yaml
├─ build_prompt.py
├─ components/
│  ├─ base/
│  │  ├─ system.md
│  │  └─ safety.md
│  ├─ capabilities/
│  │  └─ research.md
│  └─ formatting/
│     └─ output.md
└─ dist/
"""
    structure_file = write_structure_file(tmp_path, structure)

    entries = sg.parse_tree_file(structure_file)

    assert entries == [
        sg.TreeEntry(0, "Promptfile.yaml", False),
        sg.TreeEntry(0, "build_prompt.py", False),
        sg.TreeEntry(0, "components", True),
        sg.TreeEntry(1, "base", True),
        sg.TreeEntry(2, "system.md", False),
        sg.TreeEntry(2, "safety.md", False),
        sg.TreeEntry(1, "capabilities", True),
        sg.TreeEntry(2, "research.md", False),
        sg.TreeEntry(1, "formatting", True),
        sg.TreeEntry(2, "output.md", False),
        sg.TreeEntry(0, "dist", True),
    ]


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("main.py", "# TODO: STUBBED FILE PLEASE IMPLEMENT\n"),
        ("Promptfile.yaml", "# TODO: STUBBED FILE PLEASE IMPLEMENT\n"),
        ("readme.md", "<!-- TODO: STUBBED FILE PLEASE IMPLEMENT -->\n"),
        ("site.css", "/* TODO: STUBBED FILE PLEASE IMPLEMENT */\n"),
        ("app.cs", "// TODO: STUBBED FILE PLEASE IMPLEMENT\n"),
        ("notes.txt", "TODO: STUBBED FILE PLEASE IMPLEMENT\n"),
    ],
)
def test_build_stub_content(filename: str, expected: str):
    assert sg.build_stub_content(Path(filename)) == expected


def test_materialize_structure_creates_directories_and_files(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "main.py", False),
        sg.TreeEntry(0, "docs", True),
        sg.TreeEntry(1, "readme.md", False),
    ]

    sg.materialize_structure(tmp_path, entries)

    assert (tmp_path / "src").is_dir()
    assert (tmp_path / "docs").is_dir()
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == (
        "# TODO: STUBBED FILE PLEASE IMPLEMENT\n"
    )
    assert (tmp_path / "docs" / "readme.md").read_text(encoding="utf-8") == (
        "<!-- TODO: STUBBED FILE PLEASE IMPLEMENT -->\n"
    )


def test_materialize_structure_does_not_overwrite_non_empty_file(tmp_path: Path):
    target = tmp_path / "main.py"
    target.write_text("print('real code')\n", encoding="utf-8")

    entries = [sg.TreeEntry(0, "main.py", False)]
    sg.materialize_structure(tmp_path, entries)

    assert target.read_text(encoding="utf-8") == "print('real code')\n"


def test_materialize_structure_does_not_overwrite_empty_file_without_flag(tmp_path: Path):
    target = tmp_path / "main.py"
    target.write_text("", encoding="utf-8")

    entries = [sg.TreeEntry(0, "main.py", False)]
    sg.materialize_structure(tmp_path, entries, overwrite_stubs=False)

    assert target.read_text(encoding="utf-8") == ""


def test_materialize_structure_overwrites_empty_file_with_flag(tmp_path: Path):
    target = tmp_path / "main.py"
    target.write_text("", encoding="utf-8")

    entries = [sg.TreeEntry(0, "main.py", False)]
    sg.materialize_structure(tmp_path, entries, overwrite_stubs=True)

    assert target.read_text(encoding="utf-8") == "# TODO: STUBBED FILE PLEASE IMPLEMENT\n"


def test_materialize_structure_raises_if_file_path_exists_as_directory(tmp_path: Path):
    bad_dir = tmp_path / "main.py"
    bad_dir.mkdir()

    entries = [sg.TreeEntry(0, "main.py", False)]
    with pytest.raises(sg.ScaffoldError):
        sg.materialize_structure(tmp_path, entries)


def test_materialize_structure_dry_run_makes_no_changes(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "main.py", False),
    ]

    sg.materialize_structure(tmp_path, entries, dry_run=True)

    assert not (tmp_path / "src").exists()
    assert not (tmp_path / "src" / "main.py").exists()


def test_ensure_gitignore_creates_entries(tmp_path: Path):
    result = sg.ensure_gitignore(tmp_path, "python")

    content = result.read_text(encoding="utf-8")
    assert result == tmp_path / ".gitignore"
    assert "# Added by scaffold generator for language: python" in content
    assert "__pycache__/" in content
    assert ".pytest_cache/" in content


def test_ensure_gitignore_is_additive_and_not_duplicate(tmp_path: Path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("__pycache__/\nexisting.txt\n", encoding="utf-8")

    sg.ensure_gitignore(tmp_path, "python")
    content = gitignore.read_text(encoding="utf-8")

    assert "existing.txt" in content
    assert content.count("__pycache__/") == 1


def test_ensure_gitignore_dry_run_makes_no_changes(tmp_path: Path):
    gitignore = tmp_path / ".gitignore"
    original = "existing.txt\n"
    gitignore.write_text(original, encoding="utf-8")

    sg.ensure_gitignore(tmp_path, "python", dry_run=True)

    assert gitignore.read_text(encoding="utf-8") == original


def test_collect_planned_actions_reports_expected_work(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "main.py", False),
    ]

    actions = sg.collect_planned_actions(
        parent_dir=tmp_path,
        repo_root=tmp_path,
        language="python",
        entries=entries,
        overwrite_stubs=False,
    )

    joined = "\n".join(actions)
    assert "Would create and switch to branch: Generator_" in joined
    assert "Would create/update .gitignore:" in joined
    assert "Would create directory:" in joined
    assert "Would create stub file:" in joined


def test_collect_planned_actions_non_git_repo_message(tmp_path: Path):
    entries = [sg.TreeEntry(0, "src", True)]

    actions = sg.collect_planned_actions(
        parent_dir=tmp_path,
        repo_root=None,
        language="promptfile",
        entries=entries,
        overwrite_stubs=False,
    )

    assert any("not in a Git repository" in action for action in actions)


def test_validate_inputs_rejects_missing_parent(tmp_path: Path):
    missing_parent = tmp_path / "missing"
    structure = write_structure_file(tmp_path, "├─ file.txt\n")

    with pytest.raises(sg.ScaffoldError):
        sg.validate_inputs(missing_parent, structure)


def test_validate_inputs_rejects_missing_structure(tmp_path: Path):
    with pytest.raises(sg.ScaffoldError):
        sg.validate_inputs(tmp_path, tmp_path / "missing.txt")

def test_infer_python_source_roots_detects_common_roots_and_python_dirs(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "pkg", True),
        sg.TreeEntry(2, "__init__.py", False),
        sg.TreeEntry(2, "main.py", False),
        sg.TreeEntry(0, "tests", True),
        sg.TreeEntry(1, "test_main.py", False),
        sg.TreeEntry(0, "docs", True),
        sg.TreeEntry(1, "readme.md", False),
        sg.TreeEntry(0, "tools", True),
        sg.TreeEntry(1, "helper.py", False),
    ]

    roots = sg.infer_python_source_roots(tmp_path, entries)

    assert roots == ["src", "tests", "tools"]


def test_infer_python_source_roots_ignores_top_level_python_files(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "main.py", False),
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "pkg", True),
        sg.TreeEntry(2, "core.py", False),
    ]

    roots = sg.infer_python_source_roots(tmp_path, entries)

    assert roots == ["src"]


def test_ensure_vscode_settings_for_python_creates_settings_file(tmp_path: Path):
    settings_path = sg.ensure_vscode_settings_for_python(
        parent_dir=tmp_path,
        source_roots=["src", "tests"],
        dry_run=False,
    )

    assert settings_path == tmp_path / ".vscode" / "settings.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["python.analysis.extraPaths"] == ["src", "tests"]
    assert data["python.analysis.autoSearchPaths"] is True
    assert data["python.analysis.useLibraryCodeForTypes"] is True
    assert data["files.exclude"]["**/__pycache__"] is True


def test_ensure_vscode_settings_for_python_merges_existing_settings(tmp_path: Path):
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    settings_path = vscode_dir / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "editor.formatOnSave": True,
                "python.analysis.extraPaths": ["lib"],
                "files.exclude": {"**/.git": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    sg.ensure_vscode_settings_for_python(
        parent_dir=tmp_path,
        source_roots=["src", "tests"],
        dry_run=False,
    )

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["editor.formatOnSave"] is True
    assert data["python.analysis.extraPaths"] == ["lib", "src", "tests"]
    assert data["files.exclude"]["**/.git"] is True
    assert data["files.exclude"]["**/__pycache__"] is True


def test_ensure_vscode_settings_for_python_dry_run_makes_no_changes(tmp_path: Path):
    settings_path = tmp_path / ".vscode" / "settings.json"

    result = sg.ensure_vscode_settings_for_python(
        parent_dir=tmp_path,
        source_roots=["src"],
        dry_run=True,
    )

    assert result == settings_path
    assert not settings_path.exists()


def test_ensure_vscode_settings_for_python_rejects_invalid_json(tmp_path: Path):
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    settings_path = vscode_dir / "settings.json"
    settings_path.write_text("{ invalid json", encoding="utf-8")

    with pytest.raises(sg.ScaffoldError, match="invalid JSON"):
        sg.ensure_vscode_settings_for_python(
            parent_dir=tmp_path,
            source_roots=["src"],
            dry_run=False,
        )


def test_collect_vscode_python_actions_reports_settings_and_paths(tmp_path: Path):
    entries = [
        sg.TreeEntry(0, "src", True),
        sg.TreeEntry(1, "pkg", True),
        sg.TreeEntry(2, "main.py", False),
    ]

    actions = sg.collect_vscode_python_actions(tmp_path, entries)

    joined = "\n".join(actions)
    assert "Would create/update VS Code settings" in joined
    assert "python.analysis.extraPaths" in joined
    assert "src" in joined        