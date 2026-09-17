/**
 * The three non-chat rail destinations. History is real (it reads the same
 * conversations the drawer shows); Images is a stub until the backend
 * returns image attachments; Settings is account plus sign-out.
 */
import type { MouseEvent } from "react";
import { IonPage, IonContent, IonList, IonItem, IonLabel, IonIcon, useIonRouter } from "@ionic/react";
import { imagesOutline, timeOutline, trashOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { useAuth } from "../hooks/useAuth";
import { useConversations } from "../hooks/useConversations";

export function ImagesPage() {
  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="chat-canvas-arcs" aria-hidden="true" />
        <div className="empty-state">
          <IonIcon icon={imagesOutline} />
          <h2>No images yet</h2>
          <p>Images you share in a chat collect here so you can find them again.</p>
        </div>
      </IonContent>
    </IonPage>
  );
}

export function HistoryPage() {
  const router = useIonRouter();
  const { user } = useAuth();
  const { conversations, deleteConversation } = useConversations(user?.id);

  function handleDelete(e: MouseEvent, id: string, title: string) {
    e.stopPropagation();
    if (!window.confirm(`Delete "${title}"? This can't be undone.`)) return;
    deleteConversation(id);
  }

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        {conversations.length === 0 ? (
          <div className="empty-state">
            <IonIcon icon={timeOutline} />
            <h2>Nothing here yet</h2>
            <p>Every chat you start shows up in this list.</p>
          </div>
        ) : (
          <IonList className="ion-padding-top">
            {conversations.map((chat) => (
              <IonItem
                key={chat.id}
                button
                lines="none"
                detail={false}
                onClick={() => router.push(`/chat/${chat.id}`, "none", "replace")}
              >
                <IonLabel className="ion-text-nowrap">{chat.title}</IonLabel>
                <IonIcon
                  icon={trashOutline}
                  slot="end"
                  className="chat-delete-icon"
                  aria-label={`Delete ${chat.title}`}
                  onClick={(e) => handleDelete(e, chat.id, chat.title)}
                />
              </IonItem>
            ))}
          </IonList>
        )}
      </IonContent>
    </IonPage>
  );
}

export function SettingsPage() {
  const { user, signOut } = useAuth();

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="settings-group">
          <h3>Account</h3>
          <div className="settings-card">
            <div className="settings-row">
              Signed in as
              <span>{user?.email}</span>
            </div>
            <div className="settings-row">
              Session
              <button type="button" onClick={signOut}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      </IonContent>
    </IonPage>
  );
}