"""
Tiny, dependency-free persistence helpers for operational state.

Everything here is best-effort: a full disk or a read-only filesystem must
never take chat down, so failures are logged and swallowed. Writes are atomic
(write to a temp file, then rename) so a crash cannot leave half a file.
"""
import json
import logging
import os
import threading

logger = logging.getLogger("ai_router.control")

_write_lock = threading.Lock()


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        logger.warning("could not read %s; using defaults", path)
        return default


def write_json(path: str, data) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with _write_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        return True
    except OSError:
        logger.warning("could not write %s", path, exc_info=True)
        return False


def append_jsonl(path: str, obj: dict, max_bytes: int = 5 * 1024 * 1024) -> bool:
    """Append one JSON line; when the file passes max_bytes it is rotated to
    <path>.1 (one generation kept) so logs cannot fill the disk."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with _write_lock:
            if os.path.exists(path) and os.path.getsize(path) > max_bytes:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except OSError:
        logger.warning("could not append to %s", path, exc_info=True)
        return False