"""Tiny text normaliser shared by training and inference."""
import re

STOP = {
    "a", "an", "the", "is", "are", "was", "were", "of", "to", "do", "does", "did", "i", "me", "my",
    "you", "your", "yourself", "can", "could", "would", "please", "tell", "what", "whats", "how", "why",
    "when", "explain", "define", "mean", "means", "in", "on", "for", "and", "or", "it", "its", "about",
    "give", "show", "with", "that", "this", "be", "have", "has", "if", "so", "there",
}


def _stem(w: str) -> str:
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _trunc(w: str) -> str:
    return w[:7]  # crude but effective: tokeniz(ation|ing), classif(ier|ication|y)


def tokens(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("'", "")).split()
    return [_trunc(_stem(w)) for w in words if w not in STOP]


def features(text: str) -> list[str]:
    t = tokens(text)
    return t + [f"{a}_{b}" for a, b in zip(t, t[1:])]