"""
Versioned model registry with an evaluation gate and rollback.

Every trained model is stored as <root>/<version>.json (version = short hash
of the model itself) next to an index that remembers which version is live,
which was live before it, and what happened to every candidate. A candidate
only goes live if it passes the regression gate; the previous version is
always kept so an operator can roll back in one call. There is no live
self-modification: training produces a candidate, the gate decides, nothing
else can change the model that is answering users.
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field

from control.store import read_json, write_json

KEEP_VERSIONS = 6
COVERAGE_TOLERANCE = float(os.getenv("LEARN_GATE_COVERAGE_TOLERANCE", "0.05"))


@dataclass
class GateVerdict:
    ok: bool
    reasons: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)


def gate(candidate_meta: dict, current_meta: dict | None) -> GateVerdict:
    """Regression + calibration gate. Zero wrong answers and zero out-of-domain
    answers on held-out data, and no meaningful loss of coverage."""
    test = candidate_meta.get("test", {})
    val = candidate_meta.get("validation_before_final_fit", {})
    checks = {
        "no_wrong_answers_on_test": test.get("answered_wrongly", 1) == 0,
        "no_out_of_domain_answers_on_test": test.get("ood_wrongly_answered", 1) == 0,
        "no_out_of_domain_answers_on_validation": val.get("ood_wrongly_answered", 1) == 0,
    }
    reasons = [k for k, v in checks.items() if not v]
    if current_meta:
        cur_cov = current_meta.get("test", {}).get("coverage")
        new_cov = test.get("coverage")
        if cur_cov is not None and new_cov is not None:
            checks["coverage_not_regressed"] = new_cov >= cur_cov - COVERAGE_TOLERANCE
            if not checks["coverage_not_regressed"]:
                reasons.append(f"coverage fell from {cur_cov} to {new_cov}")
    return GateVerdict(ok=not reasons, reasons=reasons, checks=checks)


def model_version(model_dict: dict) -> str:
    return hashlib.sha256(json.dumps(model_dict, sort_keys=True).encode()).hexdigest()[:10]


class ModelRegistry:
    def __init__(self, root: str):
        self.root = root
        self.index_path = os.path.join(root, "index.json")
        self._lock = threading.RLock()

    # -- index ------------------------------------------------------------
    def _index(self) -> dict:
        return read_json(self.index_path, {"current": None, "previous": None, "pinned": False, "history": []})

    def _save(self, idx: dict):
        idx["history"] = idx["history"][-50:]
        write_json(self.index_path, idx)

    def _path(self, version: str) -> str:
        return os.path.join(self.root, f"{version}.json")

    def _log(self, idx, version, event, meta, verdict=None, by=None):
        test = (meta or {}).get("test", {})
        idx["history"].append({
            "version": version, "event": event, "at": int(time.time()), "by": by,
            "trained_at": (meta or {}).get("trained_at"), "content_hash": (meta or {}).get("content_hash"),
            "n_entries": (meta or {}).get("n_entries"),
            "test": {k: test.get(k) for k in ("answered_correctly", "answered_wrongly", "ood_wrongly_answered", "coverage")},
            "gate": None if verdict is None else {"ok": verdict.ok, "reasons": verdict.reasons},
        })

    # -- operations -------------------------------------------------------
    def promote(self, blob: dict, verdict: GateVerdict | None = None, by: str = "sleep") -> str:
        with self._lock:
            version = model_version(blob["model"])
            os.makedirs(self.root, exist_ok=True)
            idx = self._index()
            if idx["current"] == version:  # retrained to the identical model: nothing changed
                return version
            write_json(self._path(version), blob)
            idx["previous"] = idx["current"]
            idx["current"] = version
            self._log(idx, version, "promoted", blob["meta"], verdict, by)
            self._prune(idx)
            self._save(idx)
            return version

    def reject(self, meta: dict, verdict: GateVerdict, by: str = "sleep"):
        with self._lock:
            idx = self._index()
            self._log(idx, None, "rejected", meta, verdict, by)
            self._save(idx)

    def rollback(self, by: str = "admin") -> dict | None:
        """Make the previous version live again and pin it, so neither a
        restart nor a sleep cycle silently re-installs the one that was
        rolled back. Returns the blob, or None if there is nothing to go back to."""
        with self._lock:
            idx = self._index()
            prev = idx.get("previous")
            blob = read_json(self._path(prev), None) if prev else None
            if not blob:
                return None
            idx["previous"], idx["current"], idx["pinned"] = idx["current"], prev, True
            self._log(idx, prev, "rolled_back", blob["meta"], None, by)
            self._save(idx)
            return blob

    def set_pinned(self, pinned: bool, by: str = "admin"):
        with self._lock:
            idx = self._index()
            idx["pinned"] = bool(pinned)
            self._log(idx, idx["current"], "pinned" if pinned else "unpinned", None, None, by)
            self._save(idx)

    def is_pinned(self) -> bool:
        return bool(self._index().get("pinned"))

    def load_current(self) -> dict | None:
        cur = self._index().get("current")
        return read_json(self._path(cur), None) if cur else None

    def _prune(self, idx: dict):
        keep = {idx["current"], idx["previous"]} | {h["version"] for h in idx["history"][-KEEP_VERSIONS:] if h["version"]}
        try:
            for name in os.listdir(self.root):
                if name.endswith(".json") and name != "index.json" and name[:-5] not in keep:
                    os.remove(os.path.join(self.root, name))
        except OSError:
            pass

    def summary(self) -> dict:
        idx = self._index()
        return {"current": idx["current"], "previous": idx["previous"], "pinned": bool(idx.get("pinned")),
                "history": idx["history"][-10:][::-1]}