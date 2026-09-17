/**
 * Calls the AI router's HTTP API (backend/api.py — FastAPI wrapper around
 * AIRouter.chat()). Point VITE_AI_BACKEND_URL at wherever that's running.
 *
 * Three endpoints, all under VITE_AI_BACKEND_URL:
 *
 *   POST /chat          -> { reply, model_label }            (blocking)
 *   POST /chat/stream   -> text/event-stream of token deltas (preferred)
 *   POST /transcribe    -> { text }                          (voice fallback)
 *
 * Message content is now a list of blocks rather than a bare string, so
 * images travel in the same shape as text:
 *
 *   { role, content: [ {type:"text", text}, {type:"image_url", image_url:{url}} ] }
 *
 * Servers that predate multimodal get flattened strings instead — see
 * flattenForLegacy, which is what we retry with on a 4xx.
 *
 * model_label is scrubbed server-side via branding.py; the frontend never
 * receives raw provider names.
 */

export interface ContentBlock {
  type: "text" | "image_url";
  text?: string;
  image_url?: { url: string };
}

export interface OutboundMessage {
  role: string;
  content: ContentBlock[];
}

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

/** Requests otherwise hang forever; 90s is generous for a long answer. */
const TIMEOUT_MS = 90_000;

function placeholder(): { reply: string; model_label: string } {
  return {
    reply:
      "(AI backend not configured yet — this is a placeholder reply. " +
      "Set VITE_AI_BACKEND_URL once the router is exposed over HTTP.)",
    model_label: "Zorah 1.0",
  };
}

/** Collapse blocks back to a string for servers that predate multimodal. */
function flattenForLegacy(messages: OutboundMessage[]) {
  return messages.map((m) => ({
    role: m.role,
    content: m.content
      .map((b) => (b.type === "text" ? (b.text ?? "") : "[image attached]"))
      .join("\n")
      .trim(),
  }));
}

/**
 * Streamed chat. onDelta fires per chunk; the resolved value is the complete
 * reply. Falls back to the blocking endpoint automatically when the server
 * has no /chat/stream, so this is safe to call unconditionally.
 */
export async function streamAIBackend(
  messages: OutboundMessage[],
  sessionId: string,
  onDelta: (chunk: string) => void,
  signal?: AbortSignal,
): Promise<{ reply: string; model_label: string }> {
  if (!BASE) {
    const p = placeholder();
    onDelta(p.reply);
    return p;
  }

  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), TIMEOUT_MS);
  signal?.addEventListener("abort", () => timeout.abort(), { once: true });

  try {
    const resp = await fetch(`${BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, session_id: sessionId, stream: true }),
      signal: timeout.signal,
    });

    if (!resp.ok || !resp.body) throw new Error(`stream unavailable (${resp.status})`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let reply = "";
    let modelLabel = "Zorah 1.0";

    // SSE frames are separated by a blank line and can split across reads,
    // so buffer and only consume complete frames.
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const evt = JSON.parse(payload);
          if (evt.model_label) modelLabel = evt.model_label;
          const delta: string = evt.delta ?? evt.content ?? "";
          if (delta) {
            reply += delta;
            onDelta(delta);
          }
        } catch {
          // Server sent raw text rather than JSON — treat it as a delta.
          reply += payload;
          onDelta(payload);
        }
      }
    }

    if (!reply) throw new Error("empty stream");
    return { reply, model_label: modelLabel };
  } catch (err) {
    // A genuine user cancellation should propagate, not silently retry.
    if (signal?.aborted) throw err;
    const result = await callAIBackend(messages, sessionId, signal);
    onDelta(result.reply);
    return result;
  } finally {
    clearTimeout(timer);
  }
}

/** Blocking chat. Retries once with flattened string content on a 4xx. */
export async function callAIBackend(
  messages: OutboundMessage[],
  sessionId: string,
  signal?: AbortSignal,
): Promise<{ reply: string; model_label: string }> {
  if (!BASE) return placeholder();

  const post = (body: unknown) =>
    fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });

  let resp = await post({ messages, session_id: sessionId });

  if (resp.status >= 400 && resp.status < 500) {
    resp = await post({ messages: flattenForLegacy(messages), session_id: sessionId });
  }

  if (!resp.ok) throw new Error(`AI backend returned ${resp.status}`);
  return resp.json();
}

/**
 * Server-side speech-to-text, used when the browser has no SpeechRecognition
 * (Firefox, and Safari inside some webviews). Returns null when unavailable
 * so the caller can say so rather than dropping the recording silently.
 */
export async function transcribeAudio(blob: Blob): Promise<string | null> {
  if (!BASE) return null;
  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  try {
    const resp = await fetch(`${BASE}/transcribe`, { method: "POST", body: form });
    if (!resp.ok) return null;
    const data = await resp.json();
    return typeof data.text === "string" ? data.text : null;
  } catch {
    return null;
  }
}

/**
 * Follow-up suggestions for the message that just finished streaming.
 * Best-effort only — any failure (network, backend down, malformed JSON
 * server-side) returns an empty list rather than throwing, since a missing
 * suggestion row should never look like a chat error to the user.
 */
export async function fetchSuggestions(
  userMessage: string,
  assistantReply: string,
): Promise<string[]> {
  if (!BASE) return [];
  try {
    const resp = await fetch(`${BASE}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_message: userMessage, assistant_reply: assistantReply }),
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data.suggestions) ? data.suggestions.filter((s: unknown) => typeof s === "string") : [];
  } catch {
    return [];
  }
}