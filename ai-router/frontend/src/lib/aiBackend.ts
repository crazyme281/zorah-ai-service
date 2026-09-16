/**
 * Calls the AI router's HTTP API (backend/api.py — FastAPI wrapper
 * around AIRouter.chat()). Point VITE_AI_BACKEND_URL at wherever
 * that's running: locally (uvicorn api:app --reload) or on Render
 * once deployed.
 *
 * Contract:
 *   POST {VITE_AI_BACKEND_URL}/chat
 *   body: { messages: {role, content}[], session_id: string }
 *   response: { reply: string, model_label: string }
 * model_label is already scrubbed server-side via branding.py — the
 * frontend never receives raw provider names.
 */
export async function callAIBackend(
  messages: { role: string; content: string }[],
  sessionId: string,
): Promise<{ reply: string; model_label: string }> {
  const base = import.meta.env.VITE_AI_BACKEND_URL;

  if (!base) {
    return {
      reply:
        "(AI backend not configured yet — this is a placeholder reply. " +
        "Set VITE_AI_BACKEND_URL once router.py is exposed over HTTP.)",
      model_label: "Lite 1.23",
    };
  }

  const resp = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, session_id: sessionId }),
  });

  if (!resp.ok) {
    throw new Error(`AI backend returned ${resp.status}`);
  }
  return resp.json();
}
