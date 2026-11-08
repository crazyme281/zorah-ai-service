"""Code Fixer must find the project even when the zip wraps it in folders."""
import io
import zipfile
from pathlib import Path

import pytest

from access.codefix_pipeline import detect_project, find_project_root, safe_extract, zip_directory


def make(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_manifest_at_the_top_is_unchanged(tmp_path):
    make(tmp_path, {"package.json": "{}", "src/a.js": "x"})
    assert find_project_root(tmp_path) == tmp_path
    assert detect_project(tmp_path)[0] == "node"


def test_github_style_wrapper_folder(tmp_path):
    make(tmp_path, {"my-app-main/package.json": '{"scripts":{"build":"x"}}', "my-app-main/src/a.js": "x"})
    root = find_project_root(tmp_path)
    assert root == tmp_path / "my-app-main"
    assert detect_project(root) == ("node", ["npm install --no-audit --no-fund", "npm run build"])


def test_two_levels_deep_like_the_worker_zip(tmp_path):
    make(tmp_path, {"code-fixer-worker-main/code-fixer-worker/main.py": "print(1)",
                    "code-fixer-worker-main/code-fixer-worker/requirements.txt": "fastapi"})
    root = find_project_root(tmp_path)
    assert root == tmp_path / "code-fixer-worker-main" / "code-fixer-worker"
    assert detect_project(root)[0] == "python"


def test_mac_junk_and_shallowest_manifest_wins(tmp_path):
    make(tmp_path, {"__MACOSX/app/._package.json": "junk", "app/package.json": "{}",
                    "app/packages/lib/package.json": "{}"})
    assert find_project_root(tmp_path) == tmp_path / "app"


def test_node_modules_are_never_searched(tmp_path):
    make(tmp_path, {"app/node_modules/dep/package.json": "{}", "app/src/index.ts": "x"})
    assert find_project_root(tmp_path) != tmp_path / "app" / "node_modules" / "dep"


def test_no_manifest_python_script_still_gets_fixed(tmp_path):
    make(tmp_path, {"proj/main.py": "def f(:\n"})
    root = find_project_root(tmp_path)
    assert root == tmp_path / "proj"                               # stepped into the lone wrapper
    assert detect_project(root) == ("python", ["python3 -m compileall -q ."])


def test_no_manifest_other_source_gets_one_ai_pass(tmp_path):
    make(tmp_path, {"site/index.html": "<h1>", "site/app.js": "let x ="})
    assert detect_project(find_project_root(tmp_path)) == ("source-only", [])


def test_empty_or_docs_only_is_still_unknown(tmp_path):
    make(tmp_path, {"README.md": "hi", "notes.txt": "x"})
    assert detect_project(find_project_root(tmp_path))[0] == "unknown"


def test_result_zip_keeps_the_wrapper_folder_layout(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-app-main/requirements.txt", "flask")
        zf.writestr("my-app-main/app.py", "print(1)")
    ex = tmp_path / "x"
    ex.mkdir()
    safe_extract(buf.getvalue(), ex)
    out = zipfile.ZipFile(io.BytesIO(zip_directory(ex))).namelist()
    assert sorted(out) == ["my-app-main/app.py", "my-app-main/requirements.txt"]