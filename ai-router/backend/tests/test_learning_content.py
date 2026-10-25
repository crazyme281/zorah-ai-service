import json, os

PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learned", "content", "topics.json")
DATA = json.load(open(PATH, encoding="utf-8"))
REQUIRED = {"id", "title", "summary", "image", "terms", "example", "io", "diagram", "exercise", "quiz"}


def test_the_four_required_topics_exist():
    ids = {t["id"] for t in DATA["topics"]}
    assert ids == {"decision-trees", "word-analysis", "picture-analysis", "training-evaluation"}


def test_every_topic_has_every_required_part():
    for t in DATA["topics"]:
        assert REQUIRED <= set(t), t["id"]
        assert t["summary"] and len(t["terms"]) >= 6
        assert t["io"]["input"] and t["io"]["steps"] and t["io"]["output"]
        assert t["exercise"]["prompt"] and t["exercise"]["solution"]
        assert t["diagram"]["kind"] in ("flow", "tree")
        assert len(t["quiz"]) >= 4
        for q in t["quiz"]:
            assert 0 <= q["answer"] < len(q["options"]) and q["why"]


def test_decision_tree_demo_is_labelled_as_hand_made():
    t = next(t for t in DATA["topics"] if t["id"] == "decision-trees")
    assert t["diagram"]["kind"] == "tree" and t["tree"]["q"]
    assert "not trained" in t["diagram"]["title"].lower()
    assert "NOT trained" in t["example"]["note"]


def test_qa_entries_have_five_paraphrases_and_known_topics():
    ids = {t["id"] for t in DATA["topics"]}
    for e in DATA["qa"]:
        assert len(e["questions"]) == 5 and e["answer"] and e["topic"] in ids