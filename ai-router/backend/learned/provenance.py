"""
Provenance register: where every piece of the learned model's data came from.

For each dataset: what it is, who/what wrote it, its licence status, a content
hash, how many items, and how it was cleaned. Chat-learned entries are text
written by third-party AI models, so they are labelled as such - that matters
for the independence policy (LEARN_AI_DATA_POLICY): "allow" uses them,
"quarantine" keeps them on file but out of training, "exclude" never stores them.
"""
import hashlib
import json
import os
from collections import Counter

from . import chat_learning
from .train import CONTENT, OOD


def _sha(path: str) -> str | None:
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
    except OSError:
        return None


def register() -> dict:
    try:
        n_qa = len(json.load(open(CONTENT, encoding="utf-8"))["qa"])
    except (OSError, ValueError, KeyError):
        n_qa = None
    chat = chat_learning.provenance_counts()
    return {
        "ai_data_policy": chat_learning.AI_DATA_POLICY,
        "datasets": [
            {"id": "curated_topics", "kind": "human_written", "origin": "written by the project (learned/content/topics.json)",
             "licence": "project-owned", "sha256_16": _sha(CONTENT), "items": n_qa,
             "cleaning": "hand-written; 3 train / 1 validation / 1 test question per entry"},
            {"id": "out_of_domain_eval", "kind": "human_written", "origin": "learned/content/eval_ood.json",
             "licence": "project-owned", "sha256_16": _sha(OOD),
             "cleaning": "questions the model must NOT answer itself; split into validation and test"},
            {"id": "chat_learned", "kind": "ai_generated",
             "origin": "answers written by third-party AI providers to standalone chat questions",
             "licence": "terms of the generating provider apply - review before any use beyond this cache",
             "items": chat["total"], "by_status": chat["by_status"], "by_provider": chat["by_provider"],
             "cleaning": "standalone factual questions only; no personal, time-sensitive or task-like text; "
                         "answers filtered; asked in >= LEARN_MIN_ASKS sessions; sessions stored as hashes"},
        ],
    }