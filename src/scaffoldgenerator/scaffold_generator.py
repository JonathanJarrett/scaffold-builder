#!/usr/bin/env python3
"""
Scaffold generator for a rooted directory structure.

Features:
- Accepts a parent directory where the structure is rooted
- Accepts a project language selector (initially: python, promptfile, csharp / c#)
- If parent directory is inside a Git repo:
    - creates a new branch named Generator_<YYYYMMDD_HHMMSS>
    - aborts if the branch creation/switch would fail
    - creates or updates .gitignore with language-specific ignore entries
- If language is python:
    - runs `uv init` in the parent directory
- Accepts a text file containing a tree-style directory structure
- Creates directories and stub files
- Stub files contain a language-appropriate TODO comment:
      TODO: STUBBED FILE PLEASE IMPLEMENT
- Supports --dry-run to show planned actions without changing the filesystem or Git state
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
import json


TODO_TEXT = "TODO: STUBBED FILE PLEASE IMPLEMENT"


class ScaffoldError(Exception):
    """Raised for expected scaffold-generation failures."""


@dataclass(frozen=True)
class TreeEntry:
    depth: int
    name: str
    is_dir: bool


LANGUAGE_GITIGNORE_MAP = {
    "python": [
        "__pycache__/",
        "*.py[cod]",
        "*$py.class",
        ".Python",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".pyre/",
        ".hypothesis/",
        ".tox/",
        ".nox/",
        ".coverage",
        ".coverage.*",
        "htmlcov/",
        "dist/",
        "build/",
        "*.egg-info/",
        ".eggs/",
        "pip-wheel-metadata/",
        ".venv/",
        "venv/",
        "env/",
        "ENV/",
        ".ipynb_checkpoints/",
        ".idea/",
        ".vscode/",
    ],
    "promptfile": [
        "dist/",
        "build/",
        "*.tmp",
        "*.temp",
        "*.log",
        "*.bak",
        ".DS_Store",
        "Thumbs.db",
        ".idea/",
        ".vscode/",
    ],
    "csharp": [
        "bin/",
        "obj/",
        ".vs/",
        "*.user",
        "*.rsuser",
        "*.suo",
        "*.cache",
        "*.pdb",
        "*.mdb",
        "*.opendb",
        "*.VC.db",
        "TestResults/",
        "packages/",
        ".idea/",
        ".vscode/",
    ],
    "text": [
        ".idea/",
        ".vscode/",
    ]
}

LANGUAGE_ALIASES = {
    "python": "python",
    "promptfile": "promptfile",
    "c#": "csharp",
    "text": "text",
    "csharp": "csharp",
    "cs": "csharp",
    "english": "text",
}

EXTENSION_COMMENT_MAP = {
    ".py": "#",
    ".sh": "#",
    ".bash": "#",
    ".zsh": "#",
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".ini": ";",
    ".cfg": "#",
    ".conf": "#",
    ".env": "#",
    ".js": "//",
    ".ts": "//",
    ".tsx": "//",
    ".jsx": "//",
    ".java": "//",
    ".c": "//",
    ".cpp": "//",
    ".cc": "//",
    ".h": "//",
    ".hpp": "//",
    ".cs": "//",
    ".go": "//",
    ".swift": "//",
    ".kt": "//",
    ".rs": "//",
    ".php": "//",
    ".html": "<!--",
    ".xml": "<!--",
    ".md": "<!--",
    ".css": "/*",
    ".scss": "/*",
    ".sql": "--",
    ".ps1": "#",
}

PYTHON_SOURCE_ROOT_CANDIDATES = {
    "src",
    "app",
    "lib",
    "tests",
    "test",
    "packages",
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate directories/files from a tree file and manage Git/.gitignore."
    )
    parser.add_argument(
        "-p",
        "--parent-dir",
        required=True,
        help="Parent directory where the structure is rooted.",
    )
    parser.add_argument(
        "-l",
        "--language",
        required=True,
        help="Project language selector. Initially supports: python, promptfile, C#, text...",
    )
    parser.add_argument(
        "-s",
        "--structure-file",
        required=True,
        help="Text file containing the directory structure tree.",
    )
    parser.add_argument(
        "-o",
        "--overwrite-stubs",
        action="store_true",
        help="Overwrite existing empty files with TODO stubs. Existing non-empty files are never overwritten.",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Show what would be done without changing Git state or the filesystem.",
    )
    return parser.parse_args()


def normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in LANGUAGE_ALIASES:
        supported = ", ".join(sorted(list(set(LANGUAGE_ALIASES.values()))))
        raise ScaffoldError(
            f"Unsupported language '{language}'. Supported values: {supported}"
        )
    return LANGUAGE_ALIASES[normalized]


def run_command(
    cmd: List[str],
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ScaffoldError(f"Command not found: {cmd[0]}") from exc

    if check and proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "No additional details returned."
        raise ScaffoldError(f"Command failed: {' '.join(cmd)}\n{details}")
    return proc


def run_git(
    args: List[str],
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *args], cwd=cwd, check=check)


def find_git_repo_root(start_dir: Path) -> Optional[Path]:
    proc = run_git(["rev-parse", "--show-toplevel"], cwd=start_dir, check=False)
    if proc.returncode != 0:
        return None
    repo_root = (proc.stdout or "").strip()
    return Path(repo_root) if repo_root else None


def planned_branch_name(now: Optional[dt.datetime] = None) -> str:
    current_time = now or dt.datetime.now()
    return f"Generator_{current_time.strftime('%Y%m%d_%H%M%S')}"


def create_generator_branch(repo_root: Path, dry_run: bool = False) -> str:
    branch_name = planned_branch_name()
    if dry_run:
        return branch_name

    proc = run_git(["switch", "-c", branch_name], cwd=repo_root, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "Unknown git error."
        raise ScaffoldError(
            "Unable to create and switch to the new Git branch. "
            "This likely means the current state would cause "
            "`git switch -c` to fail.\n"
            f"Git output:\n{details}"
        )
    return branch_name


def ensure_gitignore(repo_root: Path, language: str, dry_run: bool = False) -> Path:
    entries = LANGUAGE_GITIGNORE_MAP.get(language)
    if not entries:
        raise ScaffoldError(f"No .gitignore mapping exists for language '{language}'.")

    gitignore_path = repo_root / ".gitignore"
    existing_lines: List[str] = []
    existing_normalized = set()

    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        existing_normalized = {line.strip() for line in existing_lines if line.strip()}

    additions = [entry for entry in entries if entry.strip() not in existing_normalized]
    if not additions or dry_run:
        return gitignore_path

    content_lines = list(existing_lines)
    if content_lines and content_lines[-1].strip():
        content_lines.append("")

    content_lines.append(f"# Added by scaffold generator for language: {language}")
    content_lines.extend(additions)
    content_lines.append("")

    gitignore_path.write_text("\n".join(content_lines), encoding="utf-8")
    return gitignore_path


def should_run_uv_init(parent_dir: Path) -> bool:
    """
    Conservative guard to avoid running `uv init` into a directory that already
    appears initialized as a Python project.
    """
    markers = [
        parent_dir / "pyproject.toml",
        parent_dir / ".python-version",
    ]
    return not any(marker.exists() for marker in markers)


def run_uv_init(parent_dir: Path, dry_run: bool = False) -> bool:
    """
    Returns True if uv init was run (or would be run in dry-run mode),
    False if it was skipped because the directory already appears initialized.
    """
    if not should_run_uv_init(parent_dir):
        return False

    if dry_run:
        return True

    proc = run_command(["uv", "init"], cwd=parent_dir, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "Unknown uv error."
        raise ScaffoldError(
            "Unable to initialize the Python project with `uv init`.\n"
            f"uv output:\n{details}"
        )
    return True


def strip_root_line(lines: List[str]) -> List[str]:
    if not lines:
        return lines

    first = lines[0].strip()
    if (
        first
        and first.endswith("/")
        and not first.startswith(("├", "└", "│"))
        and "/" not in first[:-1]
    ):
        return lines[1:]
    return lines


def parse_tree_file(structure_file: Path) -> List[TreeEntry]:
    raw_lines = structure_file.read_text(encoding="utf-8").splitlines()
    lines = [line.rstrip("\n\r") for line in raw_lines if line.strip()]
    lines = strip_root_line(lines)

    entries: List[TreeEntry] = []

    for line in lines:
        depth, name, is_dir = parse_tree_line(line)
        if not name:
            continue
        entries.append(TreeEntry(depth=depth, name=name, is_dir=is_dir))

    return entries


def parse_tree_line(line: str) -> tuple[int, str, bool]:
    working = line.rstrip()
    depth = 0

    while True:
        if working.startswith("│  ") or working.startswith("├──") or working.startswith("└──"):
            depth += 1
            working = working[4:]
        elif working.startswith("   "):
            depth += 1
            working = working[4:]
        else:
            break

    working = re.sub(r"^[├└|]─\s*", "", working).strip()

    is_dir = working.endswith("/")

    name = working[:-1] if is_dir else working

    name = sanitize_tree_name(name)

    return depth, name, is_dir

def build_stub_content(path: Path, msg: str) -> str:
    suffix = path.suffix.lower()

    if suffix in {".html", ".xml", ".md"}:
        return f"<!-- {msg} -->\n"

    if suffix in {".css", ".scss"}:
        return f"/* {msg} */\n"

    comment_prefix = EXTENSION_COMMENT_MAP.get(suffix)
    if comment_prefix == "<!--":
        return f"<!-- {msg} -->\n"
    if comment_prefix == "/*":
        return f"/* {msg} */\n"
    if comment_prefix:
        return f"{comment_prefix} {msg}\n"

    return f"{msg}"


def materialize_structure(
    parent_dir: Path,
    entries: Iterable[TreeEntry],
    overwrite_stubs: bool = False,
    dry_run: bool = False,
) -> None:
    stack: List[Path] = []

    for entry in entries:
        while len(stack) >= entry.depth:
            stack.pop()

        name = entry.name.split("#")
        current_parent = parent_dir if not stack else stack[-1]
        target = current_parent / name[0].strip()

        if entry.is_dir:
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            stack.append(target)
            continue

        if target.exists() and target.is_dir():
            raise ScaffoldError(
                f"Cannot create file '{target}' because a directory already exists at that path."
            )

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            if target.stat().st_size > 0:
                continue
            if not overwrite_stubs:
                continue

        if not dry_run:
            msg = TODO_TEXT if len(name) == 1 else name[1].strip()
            target.write_text(build_stub_content(target, msg), encoding="utf-8")


def validate_inputs(parent_dir: Path, structure_file: Path) -> None:
    if not parent_dir.exists():
        raise ScaffoldError(f"Parent directory does not exist: {parent_dir}")
    if not parent_dir.is_dir():
        raise ScaffoldError(f"Parent directory is not a directory: {parent_dir}")
    if not structure_file.exists():
        raise ScaffoldError(f"Structure file does not exist: {structure_file}")
    if not structure_file.is_file():
        raise ScaffoldError(f"Structure file is not a file: {structure_file}")


def collect_planned_actions(
    parent_dir: Path,
    repo_root: Optional[Path],
    language: str,
    entries: Iterable[TreeEntry],
    overwrite_stubs: bool,
) -> List[str]:
    actions: List[str] = []

    if repo_root is not None:
        actions.append(f"[DRY-RUN] Would create and switch to branch: {planned_branch_name()}")
        gitignore_path = repo_root / ".gitignore"
        actions.append(f"[DRY-RUN] Would create/update .gitignore: {gitignore_path}")

        existing = set()
        if gitignore_path.exists():
            existing = {
                line.strip()
                for line in gitignore_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

        for entry in LANGUAGE_GITIGNORE_MAP[language]:
            if entry not in existing:
                actions.append(f"[DRY-RUN] Would add .gitignore entry: {entry}")
    else:
        actions.append("[DRY-RUN] Parent directory is not in a Git repository; would skip branch creation and .gitignore changes.")

    if language == "python":
        if should_run_uv_init(parent_dir):
            actions.append(f"[DRY-RUN] Would run command: uv init (cwd={parent_dir})")
        else:
            actions.append(f"[DRY-RUN] Would skip `uv init`; Python project already appears initialized in: {parent_dir}")
        
        actions.extend(collect_vscode_python_actions(parent_dir, entries))

    stack: List[Path] = []
    for entry in entries:
        while len(stack) >= entry.depth:
            stack.pop()

        name = entry.name.split("#")
        current_parent = parent_dir if not stack else stack[-1]
        target = current_parent / name[0].strip()

        if entry.is_dir:
            if not target.exists():
                actions.append(f"[DRY-RUN] Would create directory: {target}")
            stack.append(target)
            continue

        if target.exists():
            if target.is_dir():
                actions.append(f"[DRY-RUN] ERROR: File path already exists as directory: {target}")
                continue
            if target.stat().st_size > 0:
                actions.append(f"[DRY-RUN] Would leave existing non-empty file unchanged: {target}")
                continue
            if not overwrite_stubs:
                actions.append(f"[DRY-RUN] Would leave existing empty file unchanged: {target}")
                continue

        msg = TODO_TEXT if len(name) == 1 else name[1].strip()
        actions.append(f"[DRY-RUN] Would create stub file: {target} with content: {msg}")

    return actions

def infer_python_source_roots(parent_dir: Path, entries: Iterable[TreeEntry]) -> List[str]:
    """
    Infer project-relative source roots suitable for VS Code Pylance extraPaths.

    Rules:
    - Include common top-level Python roots if they exist in the generated structure
    - Include any top-level directory that contains at least one Python file
    - Return POSIX-style relative paths, sorted and deduplicated
    """
    top_level_dirs: set[str] = set()
    top_level_dirs_with_python_files: set[str] = set()

    stack: List[str] = []

    for entry in entries:
        while len(stack) > entry.depth:
            stack.pop()

        if entry.is_dir:
            if entry.depth == 0:
                top_level_dirs.add(entry.name)
            stack.append(entry.name)
            continue

        if entry.depth == 0:
            # Top-level Python file does not imply an extraPath entry.
            continue

        if Path(entry.name).suffix.lower() == ".py" and stack:
            top_level_dirs_with_python_files.add(stack[0])

    inferred = set()

    for directory in top_level_dirs:
        if directory in PYTHON_SOURCE_ROOT_CANDIDATES:
            inferred.add(directory)

    inferred.update(top_level_dirs_with_python_files)

    # Keep only directories that either already exist or are part of the planned structure.
    normalized = sorted(path.replace("\\", "/") for path in inferred)
    return normalized


def ensure_vscode_settings_for_python(
    parent_dir: Path,
    source_roots: List[str],
    dry_run: bool = False,
) -> Path:
    """
    Create or update .vscode/settings.json with Pylance/Python analysis settings.

    Merges into existing JSON if present.
    """
    vscode_dir = parent_dir / ".vscode"
    settings_path = vscode_dir / "settings.json"

    desired_extra_paths = sorted(dict.fromkeys(source_roots))
    desired_exclude = sorted(dict.fromkeys([
        "**/__pycache__",
        "**/.pytest_cache",
        "**/.mypy_cache",
        "**/.ruff_cache",
        "**/.venv",
        "**/venv",
        "**/dist",
        "**/build",
    ]))

    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ScaffoldError(
                    f"VS Code settings file is not a JSON object: {settings_path}"
                )
        except json.JSONDecodeError as exc:
            raise ScaffoldError(
                f"VS Code settings file contains invalid JSON: {settings_path}"
            ) from exc

    existing_extra_paths = settings.get("python.analysis.extraPaths", [])
    if existing_extra_paths is None:
        existing_extra_paths = []
    if not isinstance(existing_extra_paths, list):
        raise ScaffoldError(
            f"'python.analysis.extraPaths' must be a list in {settings_path}"
        )

    merged_extra_paths = sorted(
        dict.fromkeys(str(path) for path in [*existing_extra_paths, *desired_extra_paths])
    )

    settings["python.analysis.extraPaths"] = merged_extra_paths
    settings["python.analysis.autoSearchPaths"] = True
    settings["python.analysis.useLibraryCodeForTypes"] = True

    existing_exclude = settings.get("files.exclude", {})
    if existing_exclude is None:
        existing_exclude = {}
    if not isinstance(existing_exclude, dict):
        raise ScaffoldError(
            f"'files.exclude' must be an object in {settings_path}"
        )

    for pattern in desired_exclude:
        existing_exclude.setdefault(pattern, True)

    settings["files.exclude"] = existing_exclude

    if dry_run:
        return settings_path

    vscode_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return settings_path


def collect_vscode_python_actions(
    parent_dir: Path,
    entries: Iterable[TreeEntry],
) -> List[str]:
    actions: List[str] = []
    source_roots = infer_python_source_roots(parent_dir, entries)
    settings_path = parent_dir / ".vscode" / "settings.json"

    actions.append(f"[DRY-RUN] Would create/update VS Code settings: {settings_path}")
    if source_roots:
        actions.append(
            "[DRY-RUN] Would set python.analysis.extraPaths to: "
            + ", ".join(source_roots)
        )
    else:
        actions.append(
            "[DRY-RUN] Would create VS Code settings with no inferred extraPaths."
        )

    return actions

def sanitize_tree_name(name: str) -> str:
    """
    Remove tree connector characters and quotes from parsed names.

    Removes:
    - tree characters: ├ └ │ ─ |
    - leading connector prefixes
    - single and double quotes
    - surrounding whitespace
    """

    if not name:
        return name

    # Remove connector characters anywhere in the name
    name = re.sub(r"[├└│─|]", "", name)

    # Remove quotes
    name = name.replace('"', "").replace("'", "")

    # Collapse extra whitespace
    name = re.sub(r"\s+", " ", name)

    return name.strip()

def main() -> int:
    args = parse_args()

    parent_dir = Path(args.parent_dir).expanduser().resolve()
    structure_file = Path(args.structure_file).expanduser().resolve()
    language = normalize_language(args.language)

    try:
        validate_inputs(parent_dir, structure_file)

        repo_root = find_git_repo_root(parent_dir)
        entries = parse_tree_file(structure_file)
        if not entries:
            raise ScaffoldError("No valid directory/file entries were found in the structure file.")

        if args.dry_run:
            actions = collect_planned_actions(
                parent_dir=parent_dir,
                repo_root=repo_root,
                language=language,
                entries=entries,
                overwrite_stubs=args.overwrite_stubs,
            )
            for action in actions:
                print(action)
            print("[DRY-RUN] No changes were made.")
            return 0

        created_branch: Optional[str] = None
        if repo_root is not None:
            created_branch = create_generator_branch(repo_root, dry_run=False)
            ensure_gitignore(repo_root, language, dry_run=False)

        uv_initialized = False
        vscode_settings_path: Optional[Path] = None
        inferred_python_roots: List[str] = []

        if language == "python":
            uv_initialized = run_uv_init(parent_dir, dry_run=False)
            uv_initialized = run_uv_init(parent_dir, dry_run=False)
            inferred_python_roots = infer_python_source_roots(parent_dir, entries)
            vscode_settings_path = ensure_vscode_settings_for_python(
                parent_dir=parent_dir,
                source_roots=inferred_python_roots,
                dry_run=False,
            )
        materialize_structure(
            parent_dir=parent_dir,
            entries=entries,
            overwrite_stubs=args.overwrite_stubs,
            dry_run=False,
        )

        print(f"Scaffold generation complete under: {parent_dir}")
        print(f"Language profile: {language}")
        if created_branch:
            print(f"Created and switched to Git branch: {created_branch}")
            print(f"Updated .gitignore at: {repo_root / '.gitignore'}")
        else:
            print("Parent directory is not inside a Git repository. Skipped branch creation and .gitignore update.")

        if language == "python":
            if uv_initialized:
                print(f"Initialized Python project with: uv init (cwd={parent_dir})")
            else:
                print(f"Skipped uv init because the Python project already appears initialized: {parent_dir}")

            if vscode_settings_path is not None:
                       print(f"Updated VS Code settings at: {vscode_settings_path}")
                       print(
                           "Configured Pylance extraPaths: "
                           + (", ".join(inferred_python_roots) if inferred_python_roots else "(none inferred)")
                           )                     

        return 0

    except ScaffoldError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())