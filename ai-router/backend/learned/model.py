"""
A small, real, from-scratch learner: TF-IDF + nearest-neighbour matching.

What "learning" means here (be honest about it):
  * fit(): learns a vocabulary and IDF weights from the training questions and
    stores their vectors;
  * calibrate(): picks the confidence threshold from held-out validation
    questions so that the model prefers falling back over answering wrongly;
  * evaluate(): scores on a separate test set it never saw.
It is NOT a language model and it only knows the topics in content/topics.json.
"""
import math
from collections import Counter
from .text import features


def _norm(vec: dict) -> dict:
    n = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / n for k, v in vec.items()}


class LearnedModel:
    def __init__(self):
        self.idf: dict[str, float] = {}
        self.idf_max = 1.0
        self.examples: list[tuple[str, dict]] = []  # (entry_id, normalised vector)
        self.bags: dict[str, set] = {}  # entry_id -> vocabulary from its questions + answer
        self.answers: dict[str, str] = {}
        self.threshold = 1.01  # until calibrated, never confident
        self.chat_margin = 0.1  # entries learned from chat must be extra sure

    # ---- training -------------------------------------------------------
    def fit(self, train: list[tuple[str, str]], answers: dict[str, str]):
        docs = [(eid, features(q)) for eid, q in train]
        # the answer text is learned too, as extra vocabulary for its entry
        extra = [(eid, features(a)) for eid, a in answers.items()]
        n = len(docs)
        df = Counter(f for _, fs in docs + extra for f in set(fs))
        self.idf = {f: math.log((1 + n) / (1 + c)) + 1.0 for f, c in df.items()}
        self.idf_max = math.log(1 + n) + 1.0
        self.answers = dict(answers)
        self.bags = {}
        for eid, fs in docs + extra:
            self.bags.setdefault(eid, set()).update(f for f in fs if "_" not in f)
        self.examples = [(eid, self._vec(" ".join(fs), from_features=fs)) for eid, fs in docs]
        return self

    def _vec(self, text: str, from_features=None) -> dict:
        fs = from_features if from_features is not None else features(text)
        tf = Counter(fs)
        vec, unknown = {}, 0.0
        for f, c in tf.items():
            if f in self.idf:
                vec[f] = c * self.idf[f]
            else:
                unknown += (c * self.idf_max) ** 2  # unmatched words dilute the score
        n = math.sqrt(sum(v * v for v in vec.values()) + unknown) or 1.0
        return {k: v / n for k, v in vec.items()}

    # ---- inference ------------------------------------------------------
    def score(self, text: str):
        """Returns (best_entry_id, confidence, runner_up_score)."""
        q = self._vec(text)
        if not q:
            return None, 0.0, 0.0
        best: dict[str, float] = {}
        for eid, v in self.examples:
            s = sum(w * v.get(f, 0.0) for f, w in q.items())
            if s > best.get(eid, 0.0):
                best[eid] = s
        # coverage: share of the query's weight that the entry's vocabulary explains
        uni = [f for f in features(text) if "_" not in f]
        total = sum(self.idf.get(f, self.idf_max) for f in uni) or 1.0
        score = {}
        for eid, bag in self.bags.items():
            cov = sum(self.idf.get(f, 0.0) for f in uni if f in bag) / total
            score[eid] = 0.5 * best.get(eid, 0.0) + 0.5 * cov
        ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked or ranked[0][1] <= 0:
            return None, 0.0, 0.0
        top_id, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        conf = top * min(1.0, 0.6 + 4.0 * (top - second))  # ambiguous -> less sure
        return top_id, round(conf, 4), second

    def predict(self, text: str):
        eid, conf, _ = self.score(text)
        need = self.threshold + (self.chat_margin if str(eid).startswith("chat_") else 0.0)
        if eid is not None and conf >= need:
            return eid, conf
        return None, conf

    # ---- calibration & evaluation --------------------------------------
    def evaluate(self, in_domain: list[tuple[str, str]], ood: list[str], threshold=None):
        t = self.threshold if threshold is None else threshold
        correct = wrong = fallback = 0
        for eid, q in in_domain:
            pid, conf, _ = self.score(q)
            if pid is not None and conf >= t:
                correct += pid == eid
                wrong += pid != eid
            else:
                fallback += 1
        ood_answered = sum(1 for q in ood if self.score(q)[1] >= t and self.score(q)[0] is not None)
        return {
            "in_domain": len(in_domain), "answered_correctly": correct, "answered_wrongly": wrong,
            "fell_back": fallback, "ood": len(ood), "ood_wrongly_answered": ood_answered,
            "coverage": round(correct / max(1, len(in_domain)), 3),
        }

    def calibrate(self, val_in: list[tuple[str, str]], val_ood: list[str], margin: float = 0.03):
        """Lowest threshold with zero errors on validation, plus a safety margin."""
        chosen = 0.95
        for i in range(20, 96):
            t = i / 100
            r = self.evaluate(val_in, val_ood, threshold=t)
            if r["answered_wrongly"] == 0 and r["ood_wrongly_answered"] == 0:
                chosen = t
                break
        self.threshold = round(min(0.98, chosen + margin), 2)
        return self.threshold

    # ---- persistence ----------------------------------------------------
    def to_dict(self) -> dict:
        return {"idf": self.idf, "idf_max": self.idf_max, "threshold": self.threshold,
                "answers": self.answers, "bags": {k: sorted(v) for k, v in self.bags.items()},
                "examples": [[eid, v] for eid, v in self.examples]}

    @classmethod
    def from_dict(cls, d: dict):
        m = cls()
        m.idf, m.idf_max, m.threshold, m.answers = d["idf"], d["idf_max"], d["threshold"], d["answers"]
        m.bags = {k: set(v) for k, v in d["bags"].items()}
        m.examples = [(e, v) for e, v in d["examples"]]
        return m