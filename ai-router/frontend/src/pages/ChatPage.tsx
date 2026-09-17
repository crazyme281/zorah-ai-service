import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  IonPage,
  IonContent,
  IonFooter,
  IonToolbar,
  IonTextarea,
  IonIcon,
  IonSpinner,
  useIonRouter,
} from "@ionic/react";
import {
  imageOutline,
  cameraOutline,
  micOutline,
  sendOutline,
  addOutline,
  closeOutline,
  stopOutline,
  arrowDownOutline,
  copyOutline,
  checkmarkOutline,
  shareSocialOutline,
} from "ionicons/icons";
import { useConversations } from "../hooks/useConversations";
import { useMessages } from "../hooks/useMessages";
import { useAuth } from "../hooks/useAuth";
import { useVoiceInput } from "../hooks/useVoiceInput";
import { prepareImage, type Attachment } from "../lib/attachments";
import { TopBar } from "../components/TopBar";
import { ZorahLogo } from "../components/ZorahLogo";

/** Treat "within this many px of the bottom" as the user following along. */
const STICK_THRESHOLD = 120;
const PENDING_KEY = "zorah:pending-draft";

export function ChatPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const router = useIonRouter();
  const { user } = useAuth();
  const { createConversation } = useConversations(user?.id);
  const { messages, sending, error, setError, sendMessage, stopGenerating } =
    useMessages(conversationId ?? null);

  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [preparing, setPreparing] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const contentRef = useRef<HTMLIonContentElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const stickRef = useRef(true);

  const voice = useVoiceInput((text) => {
    setDraft((d) => (d ? `${d} ${text}` : text));
  });

  const showWelcome = !conversationId || messages.length === 0;

  /**
   * Auto-scroll only while the user is already at the bottom. Yanking them
   * down mid-scroll is what made long replies impossible to read back.
   */
  const scrollToBottom = useCallback((duration = 220) => {
    contentRef.current?.scrollToBottom(duration);
  }, []);

  useEffect(() => {
    if (stickRef.current) scrollToBottom(messages.length <= 1 ? 0 : 220);
  }, [messages, scrollToBottom]);

  async function handleScroll() {
    const el = contentRef.current;
    if (!el) return;
    const sc = await el.getScrollElement();
    const distance = sc.scrollHeight - sc.scrollTop - sc.clientHeight;
    const near = distance < STICK_THRESHOLD;
    stickRef.current = near;
    setAtBottom(near);
  }

  // Replay a draft parked on the welcome screen once the new chat mounts.
  useEffect(() => {
    if (!conversationId) return;
    const pending = sessionStorage.getItem(PENDING_KEY);
    if (!pending) return;
    sessionStorage.removeItem(PENDING_KEY);
    try {
      const parsed = JSON.parse(pending) as { text: string; attachments: Attachment[] };
      sendMessage(parsed.text, parsed.attachments);
    } catch {
      sendMessage(pending);
    }
    // Intentionally keyed on the conversation only — this must fire once.
     
  }, [conversationId]);

  async function addFiles(files: FileList | null) {
    if (!files?.length || !user) return;
    setPreparing(true);
    setError(null);
    try {
      const prepared: Attachment[] = [];
      for (const file of Array.from(files).slice(0, 4)) {
        if (!file.type.startsWith("image/")) continue;
        prepared.push(await prepareImage(file, user.id));
      }
      setAttachments((prev) => [...prev, ...prepared].slice(0, 4));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't attach that image.");
    } finally {
      setPreparing(false);
    }
  }

  async function handleSend() {
    const text = draft.trim();
    if ((!text && attachments.length === 0) || sending || preparing) return;

    if (!conversationId) {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify({ text, attachments }));
      setDraft("");
      setAttachments([]);
      const chat = await createConversation(null);
      if (chat) router.push(`/chat/${chat.id}`, "none", "replace");
      return;
    }

    stickRef.current = true;
    sendMessage(text, attachments);
    setDraft("");
    setAttachments([]);
  }

  /** Suggestion chips send immediately rather than filling the composer —
   * they only ever appear once a chat already exists, so there's no
   * welcome-screen "create first" branch to handle here. */
  function handleSuggestionClick(text: string) {
    if (!conversationId || sending) return;
    stickRef.current = true;
    sendMessage(text, []);
  }

  async function handleCopy(id: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1800);
    } catch {
      // Clipboard permission denied or unavailable — nothing useful to do
      // beyond leaving the button in its normal state.
    }
  }

  async function handleShare(text: string) {
    if (navigator.share) {
      try {
        await navigator.share({ text, title: "Zorah AI" });
      } catch {
        // AbortError when the user cancels the share sheet — not an error.
      }
    } else {
      handleCopy("share-fallback", text);
    }
  }

  const recording = voice.status === "recording";
  const busy = sending || preparing || voice.status === "transcribing";

  return (
    <IonPage>
      <TopBar />

      {/* Decoration lives outside the scroll container so it stays put
          instead of scrolling away with the messages. */}
      <div className="chat-canvas-arcs" aria-hidden="true" />

      <IonContent
        ref={contentRef}
        className="chat-content"
        scrollEvents
        onIonScroll={handleScroll}
      >
        <div className="chat-thread">
          {showWelcome && (
            <div className="welcome">
              <ZorahLogo size={124} variant="full" />
              <h2 className="welcome__greeting">
                Hello, I&rsquo;m Zorah <span className="spark">&#10022;</span>
              </h2>
              <p className="welcome__sub">
                Ask me anything, or share an image. I&rsquo;m here to help.
              </p>

              <div className="welcome__actions">
                <button type="button" className="pill-action" onClick={() => fileRef.current?.click()}>
                  <IonIcon icon={imageOutline} />
                  <span>
                    <b>Upload image</b>
                    <small>JPG, PNG, WEBP</small>
                  </span>
                </button>
                <div className="welcome__divider" />
                <button type="button" className="pill-action" onClick={() => cameraRef.current?.click()}>
                  <IonIcon icon={cameraOutline} />
                  <span>
                    <b>Take photo</b>
                    <small>Use your camera</small>
                  </span>
                </button>
              </div>
            </div>
          )}

          {conversationId &&
            messages.map((m, idx) => {
              const isLast = idx === messages.length - 1;
              const done = !m.streaming && !m.pending;
              return (
                <div key={m.id} className={`message message--${m.role}`}>
                  <div className={`message-bubble ${m.failed ? "message-bubble--failed" : ""}`}>
                    {m.attachments.length > 0 && (
                      <div className="message-shots">
                        {m.attachments.map((att, i) => (
                          <img
                            key={i}
                            src={att.url || att.dataUrl}
                            alt={att.name || "Attached image"}
                            loading="lazy"
                          />
                        ))}
                      </div>
                    )}

                    {m.content && (
                      <div className="message-text markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                    )}

                    {m.streaming && !m.content && (
                      <div className="typing" aria-label="Zorah is thinking">
                        <i />
                        <i />
                        <i />
                        <span>Thinking…</span>
                      </div>
                    )}

                    {m.streaming && m.content && <span className="caret" aria-hidden="true" />}

                    {done && m.content && !m.failed && (
                      <div className="message-actions">
                        <button
                          type="button"
                          className="message-actions__btn"
                          aria-label="Copy message"
                          onClick={() => handleCopy(m.id, m.content)}
                        >
                          <IonIcon icon={copiedId === m.id ? checkmarkOutline : copyOutline} />
                          {copiedId === m.id ? "Copied" : "Copy"}
                        </button>
                        <button
                          type="button"
                          className="message-actions__btn"
                          aria-label="Share message"
                          onClick={() => handleShare(m.content)}
                        >
                          <IonIcon icon={shareSocialOutline} />
                          Share
                        </button>
                      </div>
                    )}
                  </div>

                  {isLast &&
                    m.role === "assistant" &&
                    done &&
                    !sending &&
                    !!m.suggestions?.length && (
                      <div className="suggestions">
                        {m.suggestions.map((s, i) => (
                          <button
                            key={i}
                            type="button"
                            className="suggestions__chip"
                            onClick={() => handleSuggestionClick(s)}
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                </div>
              );
            })}

          {error && <div className="thread-error">{error}</div>}
        </div>
      </IonContent>

      {/* Appears only when the user has scrolled up, so they can get back. */}
      {!atBottom && conversationId && messages.length > 0 && (
        <button
          type="button"
          className="jump-bottom"
          aria-label="Jump to latest message"
          onClick={() => {
            stickRef.current = true;
            setAtBottom(true);
            scrollToBottom();
          }}
        >
          <IonIcon icon={arrowDownOutline} />
        </button>
      )}

      <IonFooter className="composer-footer ion-no-border">
        <IonToolbar>
          {attachments.length > 0 && (
            <div className="tray">
              {attachments.map((att, i) => (
                <div className="tray__item" key={i}>
                  <img src={att.dataUrl || att.url} alt={att.name} />
                  <button
                    type="button"
                    aria-label={`Remove ${att.name}`}
                    onClick={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <IonIcon icon={closeOutline} />
                  </button>
                </div>
              ))}
              {preparing && (
                <div className="tray__item tray__item--busy">
                  <IonSpinner name="crescent" />
                </div>
              )}
            </div>
          )}

          {recording && (
            <div className="rec-bar">
              <span className="rec-bar__dot" />
              Listening · {String(Math.floor(voice.seconds / 60)).padStart(2, "0")}:
              {String(voice.seconds % 60).padStart(2, "0")}
              {voice.interim && <em>{voice.interim}</em>}
              <button type="button" onClick={voice.cancel}>
                Cancel
              </button>
            </div>
          )}

          {voice.error && <div className="rec-error">{voice.error}</div>}

          <div className={`composer ${recording ? "composer--recording" : ""}`}>
            <button
              type="button"
              className="composer__icon composer__icon--outline"
              aria-label="Attach an image"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              <IonIcon icon={addOutline} />
            </button>

            <IonTextarea
              className="composer__input"
              placeholder={recording ? "Listening…" : "Type a message…"}
              value={draft}
              autoGrow
              rows={1}
              onIonInput={(e) => setDraft(e.detail.value ?? "")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />

            <button
              type="button"
              className="composer__icon"
              aria-label="Attach an image"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              <IonIcon icon={imageOutline} />
            </button>

            {voice.supported && (
              <button
                type="button"
                className={`composer__icon ${recording ? "composer__icon--live" : ""}`}
                aria-label={recording ? "Stop recording" : "Record a voice message"}
                aria-pressed={recording}
                onClick={() => (recording ? voice.stop() : voice.start())}
                disabled={sending || preparing}
              >
                {voice.status === "transcribing" ? (
                  <IonSpinner name="crescent" />
                ) : (
                  <IonIcon icon={recording ? stopOutline : micOutline} />
                )}
              </button>
            )}

            {sending ? (
              <button
                type="button"
                className="composer__send composer__send--stop"
                aria-label="Stop generating"
                onClick={stopGenerating}
              >
                <IonIcon icon={stopOutline} />
              </button>
            ) : (
              <button
                type="button"
                className="composer__send"
                aria-label="Send message"
                disabled={preparing || (!draft.trim() && attachments.length === 0)}
                onClick={handleSend}
              >
                <IonIcon icon={sendOutline} />
              </button>
            )}
          </div>
        </IonToolbar>
      </IonFooter>

      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        hidden
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </IonPage>
  );
}