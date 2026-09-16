"""
Educational answers get a stricter pipeline than normal chat:

    question -> primary model answer -> independent second-model check
             -> compare -> agree: return answer
                         -> disagree: re-derive from a reference source
                           where one is configured, otherwise surface
                           the disagreement rather than silently picking one

And separately: when a user pushes back on a previous answer, the
router must re-verify rather than either (a) blindly agreeing to end
the friction, or (b) blindly refusing to reconsider. Two independent
models making the same mistake is a real failure mode, so agreement
between them is a weak signal on its own — a `reference_check`
callback (a calculator, a search, a lookup against a trusted source)
is the strong signal when one is available, and callers should supply
one for domains where correctness matters.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from router import AIRouter


@dataclass
class VerificationResult:
    answer: str
    primary_provider: str
    check_provider: str
    agreed: bool
    reference_used: bool
    note: str


def _second_opinion_provider(route, exclude: str) -> str:
    """Pick a provider from the fallback chain that isn't the primary, to
    act as the independent check. Falls back to the first fallback listed."""
    for name in route.fallbacks:
        if name != exclude:
            return name
    return route.fallbacks[0] if route.fallbacks else route.primary


def verify_educational_answer(
    question: str,
    router: AIRouter,
    reference_check: Optional[Callable[[str, str], Optional[str]]] = None,
) -> VerificationResult:
    """
    reference_check(question, candidate_answer) -> a corrected answer
    string if the candidate is wrong, or None if it can't determine
    anything (e.g. no lookup available for this question). This is
    where you'd plug in a calculator, a search+fetch, or a textbook/
    docs lookup — it's the tie-breaker, not either model's say-so.
    """
    route = router.routes["education"]

    primary_result = router.chat([{"role": "user", "content": question}], intent="education")
    primary_answer = primary_result["reply"]

    check_provider_name = _second_opinion_provider(route, exclude=primary_result["provider"])
    check_provider = router.providers[check_provider_name]
    check_prompt = [
        {
            "role": "system",
            "content": "Answer independently and concisely. Don't assume any other answer is correct.",
        },
        {"role": "user", "content": question},
    ]
    check_answer = check_provider.chat(check_prompt)

    agreed = _answers_roughly_agree(primary_answer, check_answer)

    if agreed:
        return VerificationResult(
            answer=primary_answer,
            primary_provider=primary_result["provider"],
            check_provider=check_provider_name,
            agreed=True,
            reference_used=False,
            note="primary and independent check agreed",
        )

    # Disagreement: two models agreeing would still just be "two guesses
    # matching," so a real reference is what should break the tie when
    # one is configured.
    if reference_check is not None:
        corrected = reference_check(question, primary_answer)
        if corrected is not None:
            return VerificationResult(
                answer=corrected,
                primary_provider=primary_result["provider"],
                check_provider=check_provider_name,
                agreed=False,
                reference_used=True,
                note="models disagreed; reference source resolved it",
            )

    # No reference available to resolve it — be honest about the
    # disagreement rather than silently picking one side.
    return VerificationResult(
        answer=(
            f"{primary_answer}\n\n(Note: a second, independent check gave a "
            "different answer, and I don't have a reliable source configured "
            "to resolve which is right. Treat this with some caution.)"
        ),
        primary_provider=primary_result["provider"],
        check_provider=check_provider_name,
        agreed=False,
        reference_used=False,
        note="models disagreed; no reference available to resolve it",
    )


def reconsider_after_objection(
    question: str,
    original_answer: str,
    user_objection: str,
    router: AIRouter,
    reference_check: Optional[Callable[[str, str], Optional[str]]] = None,
) -> VerificationResult:
    """
    Called when the user pushes back on a prior answer. This does NOT
    just ask the model "are you sure?" and take whatever it says next —
    that's the exact failure mode (flipping to avoid friction). It
    re-derives the answer from the original question plus the specific
    objection, runs it through the same dual-check, and only changes
    the answer if that re-derivation actually supports the user.
    """
    reconsideration_prompt = (
        f"Original question: {question}\n"
        f"Your original answer: {original_answer}\n"
        f"The user objects and says: {user_objection}\n\n"
        "Do not simply defer to the user. Recalculate or re-derive the "
        "answer from first principles. State your reasoning, then give "
        "your answer. If your original answer was correct, say so and "
        "explain why the objection is mistaken."
    )
    return verify_educational_answer(reconsideration_prompt, router, reference_check=reference_check)


def _answers_roughly_agree(a: str, b: str) -> bool:
    """
    Placeholder agreement check: normalizes and looks for shared core
    tokens. Fine for short factual answers; for anything higher-stakes,
    replace with a real semantic-similarity or numeric-answer-extraction
    check rather than relying on this heuristic.
    """
    def normalize(s: str) -> set:
        return set(w.strip(".,!?").lower() for w in s.split() if len(w) > 2)

    tokens_a, tokens_b = normalize(a), normalize(b)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    return overlap > 0.35
