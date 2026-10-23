"""
Users never see "Together AI", "Gemini", "Z.ai/GLM", "Groq", or
"Cohere" — they see the product name and version. This means the
provider mix underneath can change (swap models, add a provider,
drop one) without it ever surfacing as a user-visible change.

The public name comes from identity.py (DISPLAY_NAME).
"""
from identity import DISPLAY_NAME

# The user-facing identity is "lite1.2" (see identity.py). Change it there
# (or via ASSISTANT_DISPLAY_NAME); provider/model ids live in config.py.
PUBLIC_NAME = DISPLAY_NAME


def public_model_label() -> str:
    return PUBLIC_NAME


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