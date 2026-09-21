"""
Code Fixer pipeline — everything between "a zip landed" and "here's the
corrected zip and a report." Runs as a FastAPI BackgroundTask kicked off
right after upload (see api.py), updating the job's `status` in the DB
at each stage so the frontend can poll real progress.

This module does the trusted work (extraction, reading files, deciding
what to fix, calling the AI, writing fixes to disk) — the untrusted part
(actually running the project's own install/build/test commands) is
delegated entirely to the separate worker service via call_worker(),
which holds none of this process's secrets.
"""

import io
import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from access import codefix_db as jobs
from access.codefix_ai import propose_fixes, CodeFixAIError
from access.db import service_headers
from config import (
    SUPABASE_URL,
    WORKER_URL,
    WORKER_SHARED_SECRET,
    MAX_EXTRACTED_BYTES,
    MAX_UPLOAD_FILE_COUNT,
    MAX_REPAIR_ATTEMPTS,
    CODE_CONTEXT_BUDGET_CHARS,
)

REQUEST_TIMEOUT = 30
WORKER_TIMEOUT = 9 * 60  # a little above the worker's own internal budget

UPLOAD_BUCKET = "code-fixer-uploads"
RESULT_BUCKET = "code-fixer-results"

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "target", ".gradle", ".dart_tool", "vendor",
    ".pytest_cache", ".mypy_cache", "coverage", ".idea", ".vscode",
}

# Extensions we'll actually read as text for AI context. Everything else
# (images, binaries, lockfiles too huge to be useful context) is skipped
# — listed in the file tree, but its content never enters the AI prompt.
TEXT_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".py", ".pyi", ".java", ".kt", ".gradle", ".xml",
    ".php", ".dart", ".rs", ".go", ".rb", ".c", ".h", ".cpp", ".hpp",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example",
    ".html", ".css", ".scss", ".md", ".txt",
}

MANIFEST_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "pom.xml",
    "build.gradle", "build.gradle.kts", "composer.json", "pubspec.yaml",
    "Cargo.toml", "go.mod",
}


class PipelineError(Exception):
    pass


# --------------------------------------------------------------- extract --

def safe_extract(zip_bytes: bytes, dest: Path) -> int:
    """Same protections as the worker's extractor (path traversal, zip
    bomb, file-count cap) — this process extracts the upload too, to
    build context and apply fixes, so it needs the same guarantees."""
    total_bytes = 0
    file_count = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            file_count += 1
            if file_count > MAX_UPLOAD_FILE_COUNT:
                raise PipelineError(f"archive has more than {MAX_UPLOAD_FILE_COUNT} entries")

            name = info.filename
            if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                raise PipelineError(f"unsafe path in archive: {name}")

            target = (dest / name).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise PipelineError(f"path escapes extraction root: {name}")

            total_bytes += info.file_size
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise PipelineError(f"extracted size exceeds {MAX_EXTRACTED_BYTES // (1024*1024)}MB limit")

        zf.extractall(dest)

    return total_bytes


def _walk_relevant(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


# -------------------------------------------------------------- detect --

def detect_project(root: Path) -> tuple[str, list[str]]:
    """Returns (project_type, validation_commands). Commands for Node and
    Python are built from what's actually in the project (checking which
    npm scripts exist, whether a test suite is present) rather than
    assumed — the other ecosystems use the standard commands the spec
    itself names, which is a reasonable default but hasn't been exercised
    against real multi-module Java/Flutter/PHP projects here."""
    names = {p.name for p in root.iterdir()} if root.exists() else set()

    if "package.json" in names:
        return "node", _node_commands(root)
    if "requirements.txt" in names or "pyproject.toml" in names:
        return "python", _python_commands(root)
    if "pom.xml" in names:
        return "java-maven", ["mvn -B -q compile", "mvn -B -q test"]
    if "build.gradle" in names or "build.gradle.kts" in names:
        return "java-gradle", ["./gradlew build -x test --quiet", "./gradlew test --quiet"]
    if "composer.json" in names:
        return "php", ["composer validate --no-check-publish", "composer install --no-interaction", "composer test"]
    if "pubspec.yaml" in names:
        return "flutter", ["flutter pub get", "flutter analyze", "flutter test"]
    if "Cargo.toml" in names:
        return "rust", ["cargo build", "cargo test"]
    if "go.mod" in names:
        return "go", ["go build ./...", "go test ./..."]

    return "unknown", []


def _node_commands(root: Path) -> list[str]:
    cmds = ["npm install --no-audit --no-fund"]
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8", errors="ignore"))
        scripts = pkg.get("scripts", {})
        if "build" in scripts:
            cmds.append("npm run build")
        if "test" in scripts:
            cmds.append("npm test -- --ci")
    except Exception:
        # Malformed package.json is itself exactly the kind of thing this
        # feature should be finding — install alone will already surface it.
        pass
    return cmds


def _python_commands(root: Path) -> list[str]:
    cmds = []
    if (root / "requirements.txt").exists():
        cmds.append("pip install -r requirements.txt")
    elif (root / "pyproject.toml").exists():
        cmds.append("pip install .")
    # A fast, cheap syntax check across every .py file regardless of
    # whether a test suite exists — catches the most common "fixable
    # problem" (a syntax error) even in a project with no tests at all.
    cmds.append("python3 -m compileall -q .")
    if (root / "tests").is_dir() or (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        cmds.append("pytest -q")
    return cmds


# ------------------------------------------------------------- context --

def gather_context(root: Path, budget: int = CODE_CONTEXT_BUDGET_CHARS) -> tuple[str, list[str]]:
    """Manifest/config files go in full, first. Source files fill the
    remaining budget, smallest first, so a size-capped context covers as
    many files as possible rather than exhausting the budget on one huge
    file. Returns (context_text, skipped_file_paths)."""
    manifest_parts = []
    source_candidates = []

    for path in _walk_relevant(root):
        rel = path.relative_to(root).as_posix()
        if path.suffix not in TEXT_EXTENSIONS and path.name not in MANIFEST_FILES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 200_000:  # a single 200KB+ file isn't useful AI context either way
            continue
        if path.name in MANIFEST_FILES:
            manifest_parts.append((rel, size))
        else:
            source_candidates.append((rel, size))

    source_candidates.sort(key=lambda x: x[1])

    chunks = []
    used = 0
    skipped = []

    for rel, _size in manifest_parts + source_candidates:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        block = f"\n--- FILE: {rel} ---\n{text}\n"
        if used + len(block) > budget:
            skipped.append(rel)
            continue
        chunks.append(block)
        used += len(block)

    tree = "\n".join(sorted(p.relative_to(root).as_posix() for p in _walk_relevant(root)))
    header = f"PROJECT FILE TREE:\n{tree}\n\nFILE CONTENTS:\n"
    return header + "".join(chunks), skipped


# --------------------------------------------------------------- apply --

def apply_fixes(root: Path, fixes: list[dict]) -> list[dict]:
    """Writes each fix's new_content to disk. Every path is re-validated
    here — never trust a path just because it came back from the AI
    response, same as any other untrusted input. Returns the list of
    {path, reason, action} actually applied, skipping anything invalid."""
    applied = []
    for fix in fixes:
        rel = fix.get("path", "")
        content = fix.get("new_content")
        reason = fix.get("reason", "")
        if not rel or content is None:
            continue

        target = (root / rel).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            continue  # path escapes the project root — refuse it, no exceptions

        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        applied.append({"path": rel, "reason": reason, "action": "modified" if existed else "created"})

    return applied


def apply_dependency_changes(root: Path, project_type: str, deps: dict) -> dict:
    """Best-effort, and only wired up for the two ecosystems this
    pipeline reasons about in real depth. For anything else, dependency
    edits are still possible — they just have to come through as part of
    a fix's new_content for the manifest file itself, not through this
    helper."""
    added = deps.get("add") or []
    if not added:
        return {"added": [], "note": None}

    if project_type == "node":
        pkg_path = root / "package.json"
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            pkg.setdefault("dependencies", {})
            for name in added:
                pkg["dependencies"].setdefault(name, "latest")
            pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")
            return {"added": added, "note": None}
        except Exception as e:
            return {"added": [], "note": f"couldn't update package.json: {e}"}

    if project_type == "python":
        req_path = root / "requirements.txt"
        try:
            existing = req_path.read_text(encoding="utf-8") if req_path.exists() else ""
            lines = existing.splitlines()
            for name in added:
                if name not in existing:
                    lines.append(name)
            req_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return {"added": added, "note": None}
        except Exception as e:
            return {"added": [], "note": f"couldn't update requirements.txt: {e}"}

    return {"added": [], "note": f"dependency auto-add isn't wired up for '{project_type}' yet"}


# ---------------------------------------------------------------- pack --

def zip_directory(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _walk_relevant(root):
            zf.write(path, path.relative_to(root))
    return buf.getvalue()


# -------------------------------------------------------------- worker --

def call_worker(root: Path, commands: list[str]) -> list[dict]:
    if not WORKER_URL or not WORKER_SHARED_SECRET:
        raise PipelineError("the Code Fixer worker isn't configured (CODE_FIXER_WORKER_URL/WORKER_SHARED_SECRET)")
    if not commands:
        return []

    zip_bytes = zip_directory(root)
    resp = requests.post(
        f"{WORKER_URL}/run",
        headers={"x-worker-secret": WORKER_SHARED_SECRET},
        files={"project": ("project.zip", zip_bytes, "application/zip")},
        data={"commands": "\n".join(commands)},
        timeout=WORKER_TIMEOUT,
    )
    if resp.status_code != 200:
        raise PipelineError(f"worker returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()["results"]


def _validation_passed(results: list[dict]) -> bool:
    return all(r["exit_code"] == 0 for r in results if not r.get("timed_out"))


def _validation_report(project_type: str, commands: list[str], results: list[dict]) -> dict:
    """Maps raw per-command results onto the build/tests/type_check shape
    the report format wants — never claims something passed that didn't
    actually run."""
    report = {}
    for cmd, result in zip(commands, results):
        label = (
            "build" if ("build" in cmd or "compile" in cmd) else
            "tests" if ("test" in cmd) else
            "type_check" if ("tsc" in cmd or "mypy" in cmd) else
            "install"
        )
        passed = result["exit_code"] == 0 and not result.get("timed_out")
        report[label] = {
            "command": cmd,
            "passed": passed,
            "exit_code": result["exit_code"],
            "timed_out": result.get("timed_out", False),
            "output": (result.get("stderr") or result.get("stdout") or "")[-2000:],
        }
    return report


# -------------------------------------------------------------- storage --

def _download_from_storage(bucket: str, path: str) -> bytes:
    resp = requests.get(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content


def _upload_to_storage(bucket: str, path: str, data: bytes, content_type: str) -> None:
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}",
        headers=service_headers({"Content-Type": content_type}),
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


def signed_url(bucket: str, path: str, expires_in: int = 300) -> str:
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{path}",
        headers=service_headers(),
        json={"expiresIn": expires_in},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1{resp.json()['signedURL']}"


# ------------------------------------------------------------ orchestrator --

def run_job(job_id: str, zip_bytes: bytes) -> None:
    """
    The whole pipeline, run as a background task. Every stage updates the
    job row before moving on, so a poller sees real progress. Any
    exception anywhere in here is caught at the bottom and turned into a
    'failed' status with the actual error message — never a silently
    stuck job.
    """
    try:
        with TemporaryDirectory(prefix=f"codefix-{job_id}-") as tmp:
            root = Path(tmp) / "project"
            root.mkdir()

            jobs.update_job(job_id, status="extracting")
            safe_extract(zip_bytes, root)

            jobs.update_job(job_id, status="inspecting")
            project_type, commands = detect_project(root)
            jobs.update_job(job_id, project_type=project_type)

            if project_type == "unknown":
                jobs.update_job(
                    job_id,
                    status="failed",
                    error="Couldn't detect a supported project type (looked for package.json, "
                    "requirements.txt/pyproject.toml, pom.xml, build.gradle, composer.json, "
                    "pubspec.yaml, Cargo.toml, go.mod).",
                    final_status="failed",
                )
                return

            all_problems: list[str] = []
            all_files_changed: list[dict] = []
            deps_changed: dict = {}
            validation_report: dict = {}
            attempt = 0
            extra_instruction = ""

            while attempt < MAX_REPAIR_ATTEMPTS:
                attempt += 1
                jobs.update_job(job_id, status="analyzing", attempts=attempt)

                context, _skipped = gather_context(root)
                try:
                    proposal = propose_fixes(context, extra_instruction)
                except CodeFixAIError as e:
                    jobs.update_job(job_id, status="failed", error=str(e), final_status="failed")
                    return

                all_problems.extend(proposal.get("problems", []))

                jobs.update_job(job_id, status="applying_fixes")
                applied = apply_fixes(root, proposal.get("fixes", []))
                all_files_changed.extend(applied)

                dep_result = apply_dependency_changes(root, project_type, proposal.get("dependencies", {}))
                if dep_result["added"]:
                    deps_changed.setdefault("added", []).extend(dep_result["added"])

                if not commands:
                    # Nothing to validate against for this project type —
                    # one AI pass is all there is to do.
                    break

                jobs.update_job(job_id, status="validating")
                try:
                    results = call_worker(root, commands)
                except PipelineError as e:
                    jobs.update_job(job_id, status="failed", error=str(e), final_status="failed")
                    return

                validation_report = _validation_report(project_type, commands, results)

                if _validation_passed(results):
                    break

                # Feed the actual failure back in for the next pass,
                # rather than starting over from the original problem
                # description — this is what makes it a repair *loop*
                # instead of just retrying the same request.
                failing = "\n\n".join(
                    f"Command failed: {r['command']}\nExit code: {r['exit_code']}\n{(r['stderr'] or r['stdout'])[-3000:]}"
                    for r in results
                    if r["exit_code"] != 0 or r.get("timed_out")
                )
                extra_instruction = (
                    "The previous fix attempt didn't pass validation. Here is the actual "
                    f"build/test output — fix what's causing this:\n\n{failing}"
                )

            unresolved = []
            if validation_report and not all(v["passed"] for v in validation_report.values()):
                unresolved = [
                    f"{label}: {v['command']} still failing after {attempt} attempt(s)"
                    for label, v in validation_report.items()
                    if not v["passed"]
                ]

            jobs.update_job(job_id, status="packaging")
            result_zip = zip_directory(root)
            result_path = f"{job_id}/fixed.zip"
            _upload_to_storage(RESULT_BUCKET, result_path, result_zip, "application/zip")

            final_status = "success" if not unresolved else ("partial" if all_files_changed else "failed")
            jobs.update_job(
                job_id,
                status="complete",
                result_path=result_path,
                problems_found=all_problems,
                files_changed=all_files_changed,
                dependencies_changed=deps_changed,
                validation=validation_report,
                unresolved_issues=unresolved,
                final_status=final_status,
            )

    except Exception as e:
        jobs.update_job(job_id, status="failed", error=f"unexpected error: {e}", final_status="failed")


def store_upload(job_id: str, zip_bytes: bytes) -> str:
    path = f"{job_id}/original.zip"
    _upload_to_storage(UPLOAD_BUCKET, path, zip_bytes, "application/zip")
    return path