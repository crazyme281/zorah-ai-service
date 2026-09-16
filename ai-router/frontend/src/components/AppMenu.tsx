import {
  IonMenu,
  IonHeader,
  IonToolbar,
  IonTitle,
  IonContent,
  IonList,
  IonItem,
  IonLabel,
  IonButton,
  IonIcon,
  IonAccordionGroup,
  IonAccordion,
  IonFooter,
  IonText,
  useIonRouter,
} from "@ionic/react";
import { addOutline, folderOutline, addCircleOutline, logOutOutline } from "ionicons/icons";
import type { Tables } from "../lib/database.types";

type Project = Tables<"projects">;
type Conversation = Tables<"conversations">;

interface AppMenuProps {
  projects: Project[];
  conversations: Conversation[];
  onNewChat: (projectId: string | null) => void;
  onNewProject: () => void;
  userEmail: string | null;
  onSignOut: () => void;
}

export function AppMenu({
  projects,
  conversations,
  onNewChat,
  onNewProject,
  userEmail,
  onSignOut,
}: AppMenuProps) {
  const router = useIonRouter();
  const unfiledChats = conversations.filter((c) => !c.project_id);

  function goToChat(id: string) {
    router.push(`/chat/${id}`, "forward", "push");
  }

  return (
    <IonMenu contentId="main-content" type="overlay" className="app-menu">
      <IonHeader>
        <IonToolbar>
          <IonTitle className="brand-title">Lite</IonTitle>
        </IonToolbar>
      </IonHeader>

      <IonContent className="ion-padding-top">
        <div className="menu-actions">
          <IonButton expand="block" fill="clear" color="primary" onClick={() => onNewChat(null)}>
            <IonIcon icon={addOutline} slot="start" />
            New chat
          </IonButton>
          <IonButton expand="block" fill="clear" color="secondary" onClick={onNewProject}>
            <IonIcon icon={folderOutline} slot="start" />
            New project
          </IonButton>
        </div>

        <IonAccordionGroup multiple>
          {projects.map((project) => {
            const projectChats = conversations.filter((c) => c.project_id === project.id);
            return (
              <IonAccordion key={project.id} value={project.id}>
                <IonItem slot="header" lines="none" className="project-header-item">
                  <IonLabel>{project.name}</IonLabel>
                  <IonIcon
                    icon={addCircleOutline}
                    slot="end"
                    className="project-add-icon"
                    onClick={(e) => {
                      e.stopPropagation();
                      onNewChat(project.id);
                    }}
                  />
                </IonItem>
                <div className="ion-padding-start" slot="content">
                  <IonList>
                    {projectChats.length === 0 && (
                      <IonItem lines="none" className="chat-list-empty">
                        <IonLabel color="medium">No chats yet</IonLabel>
                      </IonItem>
                    )}
                    {projectChats.map((chat) => (
                      <IonItem
                        key={chat.id}
                        button
                        lines="none"
                        detail={false}
                        onClick={() => goToChat(chat.id)}
                      >
                        <IonLabel className="ion-text-nowrap">{chat.title}</IonLabel>
                      </IonItem>
                    ))}
                  </IonList>
                </div>
              </IonAccordion>
            );
          })}
        </IonAccordionGroup>

        <IonText className="chats-heading">
          <p>Chats</p>
        </IonText>
        <IonList>
          {unfiledChats.length === 0 && (
            <IonItem lines="none" className="chat-list-empty">
              <IonLabel color="medium">No chats yet</IonLabel>
            </IonItem>
          )}
          {unfiledChats.map((chat) => (
            <IonItem
              key={chat.id}
              button
              lines="none"
              detail={false}
              onClick={() => goToChat(chat.id)}
            >
              <IonLabel className="ion-text-nowrap">{chat.title}</IonLabel>
            </IonItem>
          ))}
        </IonList>
      </IonContent>

      <IonFooter className="menu-footer">
        <IonItem lines="none" className="menu-footer-item">
          <IonLabel className="ion-text-nowrap" color="medium">
            {userEmail}
          </IonLabel>
          <IonIcon icon={logOutOutline} slot="end" onClick={onSignOut} className="signout-icon" />
        </IonItem>
      </IonFooter>
    </IonMenu>
  );
}
