"""
Train, calibrate and test the learned model:  python -m learned.train

Per Q&A entry the five paraphrases are used as: 3 train, 1 validation, 1 test.
Out-of-domain questions (things it must NOT answer itself) have their own
validation and test lists. Writes artifacts/learned_model.json with metrics.
"""
import hashlib, json, os, datetime
from .model import LearnedModel

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content", "topics.json")
OOD = os.path.join(HERE, "content", "eval_ood.json")
ARTIFACT = os.path.join(HERE, "artifacts", "learned_model.json")


def content_hash() -> str:
    h = hashlib.sha256()
    for p in (CONTENT, OOD):
        h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def split():
    qa = json.load(open(CONTENT, encoding="utf-8"))["qa"]
    ood = json.load(open(OOD))
    train, val, test, answers = [], [], [], {}
    for e in qa:
        answers[e["id"]] = e["answer"]
        qs = e["questions"]
        train += [(e["id"], q) for q in qs[:3]]
        val.append((e["id"], qs[3]))
        test.append((e["id"], qs[4]))
    return train, val, test, answers, ood


def train_and_save(path: str = ARTIFACT, chat_entries=None) -> dict:
    train, val, test, answers, ood = split()
    # 1) fit on train only, pick the confidence threshold on validation
    model = LearnedModel().fit(train, answers)
    thr = model.calibrate(val, ood["ood_val"])
    val_report = model.evaluate(val, ood["ood_val"])
    # 2) final model also learns from the validation questions; the threshold is
    #    kept, and the test set is still never used for fitting or calibration
    model = LearnedModel().fit(train + val, answers)
    model.threshold = thr
    baseline_test = model.evaluate(test, ood["ood_test"])

    # 3) optionally add knowledge learned from chat, behind a safety gate
    chat_report = {"offered": len(chat_entries or []), "used": 0, "gate": "not run"}
    used_ids, rejected = set(), {}
    if chat_entries:
        pairs = [(e["id"], q) for e in chat_entries for q in e["questions"]]
        ans2 = {**answers, **{e["id"]: e["answer"] for e in chat_entries}}
        cand = LearnedModel().fit(train + val + pairs, ans2)
        cand.threshold = thr
        # an entry is kept only if the model answers each of its own questions as itself
        for e in chat_entries:
            if all(cand.predict(q)[0] == e["id"] for q in e["questions"]):
                used_ids.add(e["id"])
            else:
                rejected[e["id"]] = "not answered confidently as itself"
        if used_ids:
            kept = [e for e in chat_entries if e["id"] in used_ids]
            pairs = [(e["id"], q) for e in kept for q in e["questions"]]
            cand = LearnedModel().fit(train + val + pairs, {**answers, **{e["id"]: e["answer"] for e in kept}})
            cand.threshold = thr
            after = cand.evaluate(test, ood["ood_test"])
            after_val = cand.evaluate(val, ood["ood_val"])
            ok = (after["answered_wrongly"] == 0 and after["ood_wrongly_answered"] == 0
                  and after_val["ood_wrongly_answered"] == 0
                  and after["answered_correctly"] >= baseline_test["answered_correctly"])
            if ok:
                model = cand
                chat_report.update(used=len(kept), gate="passed")
            else:
                for i in used_ids:
                    rejected[i] = "failed the held-out safety check"
                used_ids = set()
                chat_report["gate"] = "rejected: would have hurt held-out accuracy or safety"
        else:
            chat_report["gate"] = "no entry qualified"
    report = {
        "version": hashlib.sha256(json.dumps(sorted(train)).encode()).hexdigest()[:8],
        "content_hash": content_hash(),
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "tf-idf (uni+bigrams) nearest-neighbour with calibrated confidence threshold",
        "n_train_questions": len(train) + len(val), "n_entries": len(answers), "threshold": thr,
        "validation_before_final_fit": val_report,
        "test": model.evaluate(test, ood["ood_test"]),
        "chat_learning": chat_report,
        "note": "Small hand-written dataset; test metrics are indicative, not a guarantee.",
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"meta": report, "model": model.to_dict()}, open(path, "w"))
    report["_used_ids"], report["_rejected"] = used_ids, rejected  # for the caller, not saved
    return report


if __name__ == "__main__":
    r = train_and_save()
    print(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, indent=2))