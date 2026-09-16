import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  IonPage,
  IonContent,
  IonFooter,
  IonToolbar,
  IonInput,
  IonIcon,
  useIonRouter,
} from "@ionic/react";
import { imageOutline, cameraOutline, micOutline, sendOutline, addOutline } from "ionicons/icons";
import { useConversations } from "../hooks/useConversations";
import { useMessages } from "../hooks/useMessages";
import { useAuth } from "../hooks/useAuth";
import { TopBar } from "../components/TopBar";
import { ZorahLogo } from "../components/ZorahLogo";

export function ChatPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const router = useIonRouter();
  const { user } = useAuth();
  const { conversations, createConversation } = useConversations(user?.id);
  const { messages, sending, sendMessage } = useMessages(conversationId ?? null);
  const [draft, setDraft] = useState("");
  const contentRef = useRef<HTMLIonContentElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  const showWelcome = !conversationId || messages.length === 0;

  useEffect(() => {
    contentRef.current?.scrollToBottom(200);
  }, [messages.length]);

  // Typing on the welcome screen with no chat open creates one first, parks
  // the draft, and replays it once the new chat's route has mounted — so the
  // message never gets dropped on the floor.
  const PENDING_KEY = "zorah:pending-draft";

  useEffect(() => {
    if (!conversationId) return;
    const pending = sessionStorage.getItem(PENDING_KEY);
    if (pending) {
      sessionStorage.removeItem(PENDING_KEY);
      sendMessage(pending);
    }
  }, [conversationId]);

  async function handleSend() {
    if (!draft.trim() || sending) return;
    if (!conversationId) {
      sessionStorage.setItem(PENDING_KEY, draft);
      setDraft("");
      const chat = await createConversation(null);
      if (chat) router.push(`/chat/${chat.id}`, "none", "replace");
      return;
    }
    sendMessage(draft);
    setDraft("");
  }

  return (
    <IonPage>
      <TopBar />

      <IonContent ref={contentRef} className="chat-content" fullscreen>
        <div className="chat-canvas-arcs" aria-hidden="true" />

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
              <button
                type="button"
                className="pill-action"
                onClick={() => fileRef.current?.click()}
              >
                <IonIcon icon={imageOutline} />
                <span>
                  <b>Upload image</b>
                  <small>JPG, PNG, WEBP</small>
                </span>
              </button>

              <div className="welcome__divider" />

              <button
                type="button"
                className="pill-action"
                onClick={() => cameraRef.current?.click()}
              >
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
          messages.map((m) => (
            <div key={m.id} className={`message message--${m.role}`}>
              <div className="message-bubble">{m.content}</div>
            </div>
          ))}

        {sending && (
          <div className="message message--assistant">
            <div className="message-bubble message-bubble--typing" aria-label="Zorah is typing">
              <i />
              <i />
              <i />
            </div>
          </div>
        )}
      </IonContent>

      <IonFooter className="composer-footer ion-no-border">
        <IonToolbar>
          <div className="composer">
            <button
              type="button"
              className="composer__icon composer__icon--outline"
              aria-label="Add attachment"
              onClick={() => fileRef.current?.click()}
            >
              <IonIcon icon={addOutline} />
            </button>

            <IonInput
              className="composer__input"
              placeholder="Type a message…"
              value={draft}
              onIonInput={(e) => setDraft(e.detail.value ?? "")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              disabled={sending}
            />

            <button
              type="button"
              className="composer__icon"
              aria-label="Attach image"
              onClick={() => fileRef.current?.click()}
            >
              <IonIcon icon={imageOutline} />
            </button>
            <button type="button" className="composer__icon" aria-label="Voice input">
              <IonIcon icon={micOutline} />
            </button>

            <button
              type="button"
              className="composer__send"
              aria-label="Send message"
              disabled={sending || !draft.trim()}
              onClick={handleSend}
            >
              <IonIcon icon={sendOutline} />
            </button>
          </div>
        </IonToolbar>
      </IonFooter>

      {/* Hidden pickers driving the upload / camera buttons. `capture` asks
          mobile browsers and the Capacitor webview for the camera directly. */}
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        hidden
        onChange={() => undefined}
      />
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden />
    </IonPage>
  );
}
