import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  IonPage,
  IonHeader,
  IonToolbar,
  IonTitle,
  IonButtons,
  IonMenuButton,
  IonContent,
  IonFooter,
  IonInput,
  IonButton,
  IonIcon,
} from "@ionic/react";
import { sendOutline } from "ionicons/icons";
import { useConversations } from "../hooks/useConversations";
import { useMessages } from "../hooks/useMessages";
import { useAuth } from "../hooks/useAuth";

export function ChatPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const { user } = useAuth();
  const { conversations } = useConversations(user?.id);
  const { messages, sending, sendMessage } = useMessages(conversationId ?? null);
  const [draft, setDraft] = useState("");
  const contentRef = useRef<HTMLIonContentElement>(null);

  const conversation = conversations.find((c) => c.id === conversationId);

  useEffect(() => {
    contentRef.current?.scrollToBottom(200);
  }, [messages.length]);

  function handleSend() {
    if (!draft.trim() || sending) return;
    sendMessage(draft);
    setDraft("");
  }

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar>
          <IonButtons slot="start">
            <IonMenuButton />
          </IonButtons>
          <IonTitle>{conversation?.title ?? "Lite"}</IonTitle>
        </IonToolbar>
      </IonHeader>

      <IonContent ref={contentRef} className="chat-content">
        {!conversationId && (
          <div className="empty-state">
            <h1>Start somewhere.</h1>
            <p>Pick a chat from the menu, or start a new one.</p>
          </div>
        )}

        {conversationId && messages.length === 0 && (
          <div className="empty-state empty-state--inline">
            <h2>Nothing here yet.</h2>
            <p>Say something to get started.</p>
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
            <div className="message-bubble message-bubble--typing">···</div>
          </div>
        )}
      </IonContent>

      {conversationId && (
        <IonFooter className="ion-no-border">
          <IonToolbar className="composer-toolbar">
            <IonInput
              className="composer-input"
              placeholder="Message Lite…"
              value={draft}
              onIonInput={(e) => setDraft(e.detail.value ?? "")}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSend();
              }}
              disabled={sending}
            />
            <IonButton
              slot="end"
              fill="solid"
              color="primary"
              disabled={sending || !draft.trim()}
              onClick={handleSend}
            >
              <IonIcon icon={sendOutline} />
            </IonButton>
          </IonToolbar>
        </IonFooter>
      )}
    </IonPage>
  );
}
