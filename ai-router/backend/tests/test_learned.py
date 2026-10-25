import json, os
import pytest
import learned
from learned.model import LearnedModel
from learned.train import split, train_and_save
from router import AIRouter


class FakeProvider:
    def __init__(self, name):
        self.name, self.calls = name, 0

    def chat(self, messages, **kw):
        self.calls += 1
        return f"reply from {self.name}"


def make_router():
    fakes = {n: FakeProvider(n) for n in ["claude", "gemini", "zai", "groq", "cohere"]}
    return AIRouter(providers=fakes), fakes


def total_calls(fakes):
    return sum(f.calls for f in fakes.values())


def test_training_report_is_honest_and_safe(tmp_path):
    report = train_and_save(str(tmp_path / "m.json"))
    assert report["test"]["answered_wrongly"] == 0
    assert report["test"]["ood_wrongly_answered"] == 0
    assert report["test"]["answered_correctly"] >= 8       # it really learned something
    assert report["test"]["fell_back"] > 0                  # and it admits when unsure
    assert 0.2 < report["threshold"] <= 0.98


def test_split_keeps_test_questions_out_of_training():
    train, val, test, answers, ood = split()
    seen = {q for _, q in train} | {q for _, q in val}
    assert not seen & {q for _, q in test}
    assert not seen & set(ood["ood_test"])


def test_confident_question_answered_without_calling_any_provider():
    router, fakes = make_router()
    res = router.chat([{"role": "user", "content": "what is a decision tree"}])
    assert res["provider"] == "learned" and "yes/no" in res["reply"] and res["confidence"] >= 0.6
    assert total_calls(fakes) == 0


@pytest.mark.parametrize("q", [
    "write a poem about the ocean",
    "build a decision tree classifier in sklearn for my csv file",
    "fix my react build error",
])
def test_unsure_questions_fall_back_to_other_models(q):
    router, fakes = make_router()
    res = router.chat([{"role": "user", "content": q}])
    assert res["provider"] != "learned"
    assert total_calls(fakes) == 1


def test_images_and_code_blocks_never_use_learned_answers():
    router, fakes = make_router()
    content = [{"type": "text", "text": "what is a decision tree"},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    assert router.chat([{"role": "user", "content": content}])["provider"] != "learned"
    assert learned.answer_if_confident("what is a decision tree ```x```") is None
    assert learned.answer_if_confident("what is a decision tree " + "x" * 300) is None


def test_stats_are_recorded():
    before = dict(learned.STATS)
    learned.answer_if_confident("what is overfitting")
    learned.answer_if_confident("recommend a laptop")
    assert learned.STATS["asked"] == before["asked"] + 2
    assert learned.STATS["answered_by_learned"] >= before["answered_by_learned"] + 1
    assert learned.STATS["fell_back"] >= before["fell_back"] + 1


def test_artifact_roundtrip(tmp_path):
    train, val, test, answers, ood = split()
    m = LearnedModel().fit(train, answers)
    m.threshold = 0.5
    m2 = LearnedModel.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m.score("what is overfitting") == m2.score("what is overfitting")


def test_identity_still_wins_over_learned():
    router, _ = make_router()
    assert router.chat([{"role": "user", "content": "Which model is this?"}])["provider"] == "identity"