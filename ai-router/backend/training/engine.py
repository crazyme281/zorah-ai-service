"""
Generation logic for the Training page.

Every function here asks a model for ONE JSON object, then normalizes it
into a fixed shape so the frontend never has to guess what a missing or
oddly-typed field means. Models drift (extra prose, code fences, trailing
commas, wrong types), so nothing from a model reaches the client without
going through a normalizer first.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from utils.errors import ProviderUnavailableError, RateLimitError

logger = logging.getLogger("training")

# Fast, JSON-capable providers first. Providers with no API key configured
# raise ProviderUnavailableError on their own, which just moves us to the
# next one — same behaviour as the main chat router's fallback chain.
PROVIDER_ORDER = ["groq", "gemini", "claude", "zai"]

STAGES = ["basic", "intermediate", "advanced", "pro"]

# Languages the in-app console can actually execute (see frontend
# lib/sandbox.ts). Everything else is reviewed by the AI instead.
RUNNABLE = {"javascript": "javascript", "js": "javascript", "node": "javascript",
            "nodejs": "javascript", "python": "python", "py": "python"}


class TrainingGenerationError(Exception):
    """No provider produced usable output."""


# --------------------------------------------------------------------------
# JSON handling
# --------------------------------------------------------------------------
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.M)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def extract_json(text: str) -> dict:
    """Pull one JSON object out of a model reply, tolerating fences,
    leading/trailing prose and trailing commas."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty reply")
    cleaned = _FENCE.sub("", text.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    body = cleaned[start : end + 1]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = json.loads(_TRAILING_COMMA.sub(r"\1", body))
    if not isinstance(parsed, dict):
        raise ValueError("JSON root is not an object")
    return parsed


def complete_json(
    providers: dict,
    system: str,
    user: str,
    *,
    max_tokens: int = 3500,
    temperature: float = 0.4,
    order: list[str] | None = None,
) -> dict:
    """Try each provider until one returns parseable JSON."""
    errors: list[str] = []
    for name in order or PROVIDER_ORDER:
        provider = providers.get(name)
        if provider is None:
            continue
        for attempt in (1, 2):
            sys_prompt = system if attempt == 1 else (
                system + "\n\nYour previous reply was not valid JSON. Reply with ONE valid JSON "
                "object only — no code fences, no commentary."
            )
            try:
                raw = provider.chat(
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except (RateLimitError, ProviderUnavailableError) as e:
                errors.append(f"{name}: {e}")
                break  # next provider — retrying a down/limited one is pointless
            except Exception as e:  # provider bug — don't let it kill the request
                errors.append(f"{name}: {type(e).__name__}: {e}")
                break
            try:
                return extract_json(raw)
            except (ValueError, json.JSONDecodeError) as e:
                errors.append(f"{name} attempt {attempt}: bad JSON ({e})")
    logger.warning("training generation failed: %s", "; ".join(errors))
    raise TrainingGenerationError("The tutor couldn't generate that right now. Please try again.")


# --------------------------------------------------------------------------
# Small coercion helpers
# --------------------------------------------------------------------------
def _s(v: Any, default: str = "", limit: int = 6000) -> str:
    if v is None:
        return default
    return str(v).strip()[:limit] if not isinstance(v, (dict, list)) else default


def _list(v: Any) -> list:
    return v if isinstance(v, list) else []


def normalize_language(language: str | None) -> tuple[str | None, str]:
    """-> (display name or None, execution mode: javascript|python|none)"""
    if not language:
        return None, "none"
    lang = language.strip()
    return lang, RUNNABLE.get(lang.lower(), "none")


def clean_svg(svg: Any) -> str | None:
    """Keep a model-drawn diagram only if it's a plain, script-free SVG.
    The client also renders it via <img>, which never runs scripts — this
    is the second layer."""
    if not isinstance(svg, str):
        return None
    svg = svg.strip()
    if not svg.lower().startswith("<svg") or len(svg) > 24000:
        return None
    lowered = svg.lower()
    if any(bad in lowered for bad in ("<script", "<foreignobject", "javascript:", "<iframe", "<image", "<use", "xlink:href", "href=\"http", "@import", "url(http")):
        return None
    if re.search(r"\son[a-z]+\s*=", lowered):
        return None
    if "xmlns" not in lowered[:200]:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


# --------------------------------------------------------------------------
# Normalizers
# --------------------------------------------------------------------------
def normalize_curriculum(data: dict, *, is_coding: bool, stage: str) -> dict:
    modules = []
    n = 0
    for m in _list(data.get("modules")):
        if not isinstance(m, dict):
            continue
        lessons = []
        for l in _list(m.get("lessons")):
            if isinstance(l, str):
                l = {"title": l}
            if not isinstance(l, dict) or not _s(l.get("title")):
                continue
            n += 1
            lessons.append({"id": f"l{n}", "title": _s(l.get("title"), limit=140),
                            "summary": _s(l.get("summary"), limit=300)})
        if lessons:
            modules.append({"title": _s(m.get("title"), f"Module {len(modules) + 1}", 140), "lessons": lessons})
    if not modules:
        raise TrainingGenerationError("The tutor returned an empty learning path. Please try again.")

    out: dict[str, Any] = {
        "title": _s(data.get("title"), "Your learning path", 120),
        "overview": _s(data.get("overview"), limit=500),
        "modules": modules,
    }
    if is_coding:
        roadmap = []
        seen = set()
        for r in _list(data.get("roadmap")):
            if isinstance(r, dict) and _s(r.get("stage")).lower() in STAGES and _s(r.get("stage")).lower() not in seen:
                st = _s(r.get("stage")).lower()
                seen.add(st)
                roadmap.append({"stage": st, "focus": _s(r.get("focus"), limit=200)})
        for st in STAGES:  # always give the full Basic -> Pro path
            if st not in seen:
                roadmap.append({"stage": st, "focus": ""})
        roadmap.sort(key=lambda r: STAGES.index(r["stage"]))
        out["roadmap"] = roadmap
    return out


def normalize_lesson(data: dict, *, is_coding: bool) -> dict:
    explanation = _s(data.get("explanation_md") or data.get("explanation"), limit=9000)
    if not explanation:
        raise TrainingGenerationError("The tutor returned an empty lesson. Please try again.")

    examples = []
    for e in _list(data.get("examples"))[:3]:
        if isinstance(e, dict) and _s(e.get("body_md") or e.get("body")):
            examples.append({"title": _s(e.get("title"), "Example", 100),
                             "body_md": _s(e.get("body_md") or e.get("body"), limit=4000)})

    questions = []
    for q in _list(data.get("questions")):
        if not isinstance(q, dict) or not _s(q.get("prompt")):
            continue
        qid = f"q{len(questions) + 1}"
        opts = [_s(o, limit=300) for o in _list(q.get("options")) if _s(o)]
        idx = q.get("correct_index")
        if len(opts) >= 2 and isinstance(idx, int) and 0 <= idx < len(opts):
            questions.append({"id": qid, "type": "choice", "prompt": _s(q.get("prompt"), limit=500),
                              "options": opts[:5], "correct_index": idx,
                              "explanation": _s(q.get("explanation"), limit=700),
                              "hint": _s(q.get("hint"), limit=300)})
        else:
            questions.append({"id": qid, "type": "short", "prompt": _s(q.get("prompt"), limit=500),
                              "reference": _s(q.get("model_answer") or q.get("reference"), limit=700),
                              "hint": _s(q.get("hint"), limit=300)})
    if not questions:
        raise TrainingGenerationError("The tutor returned a lesson with no questions. Please try again.")

    return {
        "title": _s(data.get("title"), limit=140),
        "objectives": [_s(o, limit=200) for o in _list(data.get("objectives")) if _s(o)][:5],
        "explanation_md": explanation,
        "examples": examples,
        "diagram_svg": clean_svg(data.get("diagram_svg")),
        "diagram_caption": _s(data.get("diagram_caption"), limit=200),
        "questions": questions[:4],
    }


def normalize_task(data: dict, *, is_coding: bool, language: str | None, execution: str) -> dict:
    instructions = _s(data.get("instructions_md") or data.get("instructions"), limit=5000)
    if not instructions:
        raise TrainingGenerationError("The tutor returned an empty task. Please try again.")
    kind = "code" if is_coding else "written"

    tests = []
    for t in _list(data.get("tests")):
        if not isinstance(t, dict) or not _s(t.get("name")):
            continue
        ttype = _s(t.get("type"), "behavior").lower()
        expected = t.get("expected")
        expected_s = json.dumps(expected) if isinstance(expected, (list, dict, bool)) or expected is None else _s(expected, limit=600)
        if execution != "none" and ttype == "call" and _s(t.get("expr")):
            tests.append({"name": _s(t.get("name"), limit=120), "type": "call",
                          "expr": _s(t.get("expr"), limit=300), "expected": expected_s})
        elif execution != "none" and ttype == "stdout":
            tests.append({"name": _s(t.get("name"), limit=120), "type": "stdout", "expected": expected_s})
        else:
            tests.append({"name": _s(t.get("name"), limit=120), "type": "behavior", "expected": expected_s})

    # A "runnable" coding task with no executable tests can't be checked
    # by the console — the frontend falls back to AI review in that case.
    return {
        "title": _s(data.get("title"), "Practice task", 140),
        "instructions_md": instructions,
        "kind": kind,
        "language": language if is_coding else None,
        "execution": execution if is_coding else "none",
        "starter_code": _s(data.get("starter_code"), limit=4000) if is_coding else "",
        "tests": tests[:8],
        "rubric": [_s(r, limit=200) for r in _list(data.get("rubric")) if _s(r)][:6],
        "hints": [_s(h, limit=300) for h in _list(data.get("hints")) if _s(h)][:3],
        "solution": _s(data.get("solution"), limit=5000) or None,
    }


def normalize_quiz(data: dict) -> dict:
    questions = []
    for q in _list(data.get("questions")):
        if not isinstance(q, dict) or not _s(q.get("prompt")):
            continue
        opts = [_s(o, limit=300) for o in _list(q.get("options")) if _s(o)]
        idx = q.get("correct_index")
        if len(opts) < 2 or not isinstance(idx, int) or not 0 <= idx < len(opts):
            continue
        wrong = _list(q.get("wrong_explanations"))
        why = []
        for i in range(len(opts)):
            w = wrong[i] if i < len(wrong) else None
            why.append(None if i == idx else (_s(w, limit=400) or None))
        questions.append({"id": f"q{len(questions) + 1}", "prompt": _s(q.get("prompt"), limit=500),
                          "options": opts[:5], "correct_index": idx,
                          "explanation": _s(q.get("explanation"), limit=600), "why_wrong": why[:5]})
    if len(questions) < 2:
        raise TrainingGenerationError("The tutor returned an incomplete quiz. Please try again.")
    return {"questions": questions[:8]}


def normalize_respond(data: dict) -> dict:
    follow = data.get("follow_up")
    follow_up = None
    if isinstance(follow, dict) and _s(follow.get("prompt")):
        follow_up = {"prompt": _s(follow.get("prompt"), limit=400),
                     "hint": _s(follow.get("hint"), limit=300),
                     "reference": _s(follow.get("model_answer") or follow.get("reference"), limit=500)}
    return {"correct": bool(data.get("correct")),
            "feedback_md": _s(data.get("feedback_md") or data.get("feedback"), limit=1500),
            "follow_up": follow_up}


def normalize_review(data: dict) -> dict:
    try:
        score = int(round(float(data.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    return {"passed": bool(data.get("passed")) if "passed" in data else score >= 70,
            "score": score,
            "feedback_md": _s(data.get("feedback_md") or data.get("feedback"), limit=2000),
            "next_steps": [_s(n, limit=200) for n in _list(data.get("next_steps")) if _s(n)][:3]}


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
BASE_RULES = (
    "You are Zorah Tutor, a patient, encouraging teacher. Explain simply, with concrete examples, "
    "and never talk down to the learner. Reply with ONE valid JSON object and nothing else: no "
    "markdown fences around it, no commentary. Inside JSON strings use \\n for newlines and escape quotes."
)

STAGE_GUIDE = {
    "basic": "Basic: syntax, variables and types, conditions, loops, functions, simple collections, reading error messages.",
    "intermediate": "Intermediate: data structures in depth, objects/classes and modules, error handling, file and JSON handling, testing basics, core algorithms.",
    "advanced": "Advanced: design patterns, async/concurrency, performance, architecture, APIs and databases, testing strategy.",
    "pro": "Pro: system design, scalability, security, production practices, optimisation, advanced idioms, a realistic capstone project.",
}


def _course_line(subject: str, is_coding: bool, language: str | None, stage: str, level: str | None) -> str:
    if is_coding:
        return f"Subject: programming in {language or subject}. Stage: {stage} ({STAGE_GUIDE.get(stage, '')})"
    return f"Subject: {subject}. Learner level: {level or 'beginner'}."


def generate_curriculum(providers, *, subject, is_coding, language, level, stage, focus=None) -> dict:
    schema = (
        '{"title": str, "overview": str, "modules": [{"title": str, "lessons": [{"title": str, "summary": str}]}]'
        + (', "roadmap": [{"stage": "basic|intermediate|advanced|pro", "focus": str}]' if is_coding else "")
        + "}"
    )
    system = (
        f"{BASE_RULES}\n\nDesign a structured learning path. Schema: {schema}\n"
        "Rules: 3-5 modules of 2-3 lessons each (6-12 lessons total), ordered so each lesson builds on the "
        "previous one. Lesson titles are specific (not 'Introduction'). Start exactly at the learner's level."
        + (" Cover ONLY the current stage in modules; the roadmap lists all four stages "
           "(basic, intermediate, advanced, pro) with a one-line focus each." if is_coding else "")
    )
    user = _course_line(subject, is_coding, language, stage, level) + (f"\nLearner's goal/notes: {focus}" if focus else "")
    return normalize_curriculum(complete_json(providers, system, user, max_tokens=2200), is_coding=is_coding, stage=stage)


def generate_lesson(providers, *, subject, is_coding, language, level, stage, course_title,
                    lesson, outline, mastery) -> dict:
    schema = (
        '{"title": str, "objectives": [str], "explanation_md": str, "examples": [{"title": str, "body_md": str}], '
        '"diagram_svg": str|null, "diagram_caption": str, '
        '"questions": [{"prompt": str, "options": [str x4], "correct_index": int, "explanation": str, "hint": str} x2, '
        '{"prompt": str, "model_answer": str, "hint": str} x1]}'
    )
    system = (
        f"{BASE_RULES}\n\nTeach ONE lesson. Schema: {schema}\n"
        "Rules: explanation_md is 250-450 words of markdown (short paragraphs, a heading or two, bullet lists "
        "where they help). Start from the intuition, then the details. "
        + ("Put every code sample in a fenced block with its language tag; keep the explanation text OUTSIDE the "
           "code blocks. " if is_coding else "Use everyday analogies. ")
        + "Give 1-3 worked examples. Then exactly 3 questions: two multiple-choice (4 options, one correct, "
        "explanation says why) and one short-answer that checks real understanding. "
        "diagram_svg: include ONLY when a picture genuinely helps (a process, structure, timeline, labelled "
        "diagram, geometry); otherwise null. If included: one self-contained <svg viewBox=\"0 0 640 360\"> for a "
        "DARK background — transparent background, strokes/text in #f2cb6b and #f4efe3, text at least 14px, "
        "under 60 elements, no scripts, no external images or fonts."
        " If the learner is struggling (see mastery), slow down, use simpler words and add an extra example."
    )
    user = (
        f"Course: {course_title}\n{_course_line(subject, is_coding, language, stage, level)}\n"
        f"Lesson to teach: {lesson.get('title')} — {lesson.get('summary')}\n"
        f"Full outline: {'; '.join(outline)[:900]}\n"
        f"Learner mastery so far: {json.dumps(mastery)[:500]}"
    )
    return normalize_lesson(complete_json(providers, system, user, max_tokens=3600, temperature=0.5), is_coding=is_coding)


def respond_to_answer(providers, *, subject, lesson_title, question, user_answer, reference, was_correct, options=None) -> dict:
    system = (
        f"{BASE_RULES}\n\nYou are marking a learner's answer. Schema: "
        '{"correct": bool, "feedback_md": str, "follow_up": {"prompt": str, "hint": str, "model_answer": str}|null}\n'
        "Rules: be kind and specific. If correct, confirm and add one insight. If wrong or partly wrong, explain "
        "exactly what is off and why the right answer is right — do not just say 'wrong'. When wrong, include a "
        "short, easier follow_up question that targets the misunderstanding; otherwise follow_up is null. "
        "Keep feedback_md under 120 words."
    )
    known = f"Marked correct by the app: {was_correct}\n" if was_correct is not None else ""
    user = (
        f"Subject: {subject}. Lesson: {lesson_title}\nQuestion: {question}\n"
        + (f"Options: {json.dumps(options)}\n" if options else "")
        + f"Reference answer: {reference}\nLearner's answer: {user_answer}\n{known}"
    )
    result = normalize_respond(complete_json(providers, system, user, max_tokens=700, temperature=0.3))
    if was_correct is not None:  # the app knows a multiple-choice answer for sure
        result["correct"] = bool(was_correct)
    return result


def generate_task(providers, *, subject, is_coding, language, level, stage, course_title, lesson, performance) -> dict:
    lang_name, execution = normalize_language(language) if is_coding else (None, "none")
    if is_coding:
        schema = (
            '{"title": str, "instructions_md": str, "starter_code": str, "tests": [test], "hints": [str], "solution": str}\n'
            'test = {"name": str, "type": "call", "expr": str, "expected": json-literal-as-string} '
            'or {"name": str, "type": "stdout", "expected": str}'
            + (' or {"name": str, "type": "behavior", "expected": str}' if execution == "none" else "")
        )
        if execution == "none":
            test_rules = ("The learner's code cannot be executed here, so every test must have type \"behavior\": a "
                          "plain-English description of what a correct solution must do for a given input.")
        else:
            test_rules = (
                f"The learner's code WILL be executed in {lang_name} ({execution}). Design the task so it is solved by "
                "writing named functions (or a short program that prints), and tests are: "
                "type \"call\" -> expr is one expression calling the learner's function, e.g. \"add(2, 3)\", and expected "
                "is its result as a JSON literal string, e.g. \"5\" or \"[1,2,3]\" or \"true\"; "
                "type \"stdout\" -> the exact text the program must print. Provide 3-5 tests including an edge case. "
                "starter_code contains the function stubs with comments (no solution). solution is a complete working answer."
            )
        system = f"{BASE_RULES}\n\nWrite ONE practical coding task for this lesson. Schema: {schema}\n{test_rules}\n" \
                 "instructions_md states the goal, the exact function name/signature, inputs/outputs and one example. " \
                 "hints: 2-3 progressive hints that never give the answer away. Match the difficulty to the learner's performance."
    else:
        system = (
            f"{BASE_RULES}\n\nWrite ONE practical task for this lesson (something the learner does or writes, e.g. "
            "solve a problem, explain, analyse a case, plan, draft). Schema: "
            '{"title": str, "instructions_md": str, "rubric": [str], "hints": [str], "solution": str}\n'
            "rubric: 3-5 criteria a good answer meets. solution: a strong model answer. Match difficulty to the learner's performance."
        )
    user = (
        f"Course: {course_title}\n{_course_line(subject, is_coding, lang_name or language, stage, level)}\n"
        f"Lesson: {lesson.get('title')} — {lesson.get('summary')}\nLearner performance on this lesson's questions: {json.dumps(performance)}"
    )
    data = complete_json(providers, system, user, max_tokens=2600, temperature=0.5)
    return normalize_task(data, is_coding=is_coding, language=lang_name, execution=execution)


def review_task(providers, *, subject, language, task, submission, mode, run_result, all_tests_passed) -> dict:
    system = (
        f"{BASE_RULES}\n\nGive feedback on a learner's task submission. Schema: "
        '{"passed": bool, "score": int 0-100, "feedback_md": str, "next_steps": [str]}\n'
        "Rules: encouraging and specific; explain what works, what doesn't and how to fix it WITHOUT writing the full "
        "solution. Under 150 words. "
        + ("The app already ran the tests; treat their results as ground truth and explain them (do not contradict them)."
           if mode == "tests" else
           "Judge the submission against the task's tests/rubric by reading it carefully; passed is true only if it "
           "would satisfy them (score >= 70).")
    )
    user = (
        f"Subject: {subject}{f' ({language})' if language else ''}\nTask: {task.get('title')}\n{task.get('instructions_md', '')[:2500]}\n"
        f"Tests/rubric: {json.dumps(task.get('tests') or task.get('rubric') or [])[:1500]}\n"
        f"--- Submission ---\n{submission[:9000]}\n"
        + (f"--- Test run ---\n{json.dumps(run_result)[:2500]}\n" if run_result else "")
    )
    result = normalize_review(complete_json(providers, system, user, max_tokens=800, temperature=0.3))
    if mode == "tests":
        result["passed"] = bool(all_tests_passed)
        if all_tests_passed:
            result["score"] = max(result["score"], 90)
    return result


def generate_quiz(providers, *, subject, is_coding, language, level, stage, course_title, lesson, performance, count=5) -> dict:
    system = (
        f"{BASE_RULES}\n\nWrite a {count}-question multiple-choice quiz for the lesson. Schema: "
        '{"questions": [{"prompt": str, "options": [str x4], "correct_index": int, "explanation": str, '
        '"wrong_explanations": [str|null x4]}]}\n'
        "Rules: test understanding, not memorised wording; one clearly-correct option; plausible distractors based on "
        "real misconceptions. explanation says why the correct option is right. wrong_explanations has one entry per "
        "option: null for the correct option, otherwise a one-sentence explanation of exactly why THAT option is wrong "
        "(the learner sees it if they pick it). Vary correct_index. "
        + ("Include short code snippets in questions where natural (use backticks). " if is_coding else "")
        + "Calibrate difficulty to the learner's performance."
    )
    user = (
        f"Course: {course_title}\n{_course_line(subject, is_coding, language, stage, level)}\n"
        f"Lesson: {lesson.get('title')} — {lesson.get('summary')}\nLearner performance so far: {json.dumps(performance)}"
    )
    return normalize_quiz(complete_json(providers, system, user, max_tokens=3000, temperature=0.5))
