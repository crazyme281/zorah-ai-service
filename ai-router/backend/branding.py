"""
Users never see "Together AI", "Gemini", "Z.ai/GLM", "Groq", or
"Cohere" — they see the product name and version. This means the
provider mix underneath can change (swap models, add a provider,
drop one) without it ever surfacing as a user-visible change.

PUBLIC_NAME / PUBLIC_VERSION are the only two lines that should need
editing when you bump the product version.
"""
PUBLIC_NAME = "Lite"
PUBLIC_VERSION = "1.23"


def public_model_label() -> str:
    return f"{PUBLIC_NAME} {PUBLIC_VERSION}"


def scrub_result_for_user(result: dict) -> dict:
    """
    Takes a router.chat() result and returns a copy safe to show or log
    to the end user — internal provider/intent routing details replaced
    with the public label. Keep the original result for your own
    server-side logs/metrics; only the scrubbed copy goes user-facing.
    """
    scrubbed = dict(result)
    scrubbed["model_label"] = public_model_label()
    scrubbed.pop("provider", None)
    scrubbed.pop("attempts", None)
    scrubbed.pop("intent", None)
    return scrubbed
