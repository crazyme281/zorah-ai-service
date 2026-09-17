import {
  IonMenu,
  IonContent,
  IonList,
  IonItem,
  IonLabel,
  IonIcon,
  IonAccordionGroup,
  IonAccordion,
  IonFooter,
  useIonRouter,
} from "@ionic/react";
import { menuController } from "@ionic/core";
import type { MouseEvent } from "react";
import { useLocation } from "react-router-dom";
import {
  addOutline,
  folderOutline,
  addCircleOutline,
  logOutOutline,
  trashOutline,
} from "ionicons/icons";
import type { Tables } from "../lib/database.types";
import { ZorahLogo } from "./ZorahLogo";
import { RAIL_ITEMS, isRailActive } from "./IconRail";

type Project = Tables<"projects">;
type Conversation = Tables<"conversations">;

interface AppMenuProps {
  projects: Project[];
  conversations: Conversation[];
  onNewChat: (projectId: string | null) => void;
  onNewProject: () => void;
  onDeleteChat: (id: string) => void;
  userEmail: string | null;
  onSignOut: () => void;
}

export function AppMenu({
  projects,
  conversations,
  onNewChat,
  onNewProject,
  onDeleteChat,
  userEmail,
  onSignOut,
}: AppMenuProps) {
  const router = useIonRouter();
  const { pathname } = useLocation();
  const unfiledChats = conversations.filter((c) => !c.project_id);

  async function go(path: string) {
    await menuController.close("app-menu");
    router.push(path, "none", "replace");
  }

  // Deleting the chat you're currently viewing bounces you back to the
  // welcome screen instead of leaving you parked on a chat that's gone.
  function handleDelete(e: MouseEvent, chatId: string) {
    e.stopPropagation();
    if (!window.confirm("Delete this chat? This can't be undone.")) return;
    onDeleteChat(chatId);
    if (pathname === `/chat/${chatId}`) router.push("/", "none", "replace");
  }

  return (
    <IonMenu contentId="main-content" menuId="app-menu" type="overlay" className="app-menu">
      <div className="menu-head">
        <ZorahLogo size={34} />
        <span className="menu-head__name">Zorah</span>
      </div>

      <IonContent>
        <div className="menu-actions">
          <button type="button" className="menu-btn menu-btn--gold" onClick={() => onNewChat(null)}>
            <IonIcon icon={addOutline} />
            New chat
          </button>
          <button type="button" className="menu-btn menu-btn--ghost" onClick={onNewProject}>
            <IonIcon icon={folderOutline} />
            New project
          </button>
        </div>

        {/* On phones the rail is hidden, so the drawer carries the sections. */}
        <div className="menu-nav-mobile">
          <span className="menu-section">Go to</span>
          <IonList>
            {RAIL_ITEMS.map((item) => (
              <IonItem
                key={item.path}
                button
                lines="none"
                detail={false}
                className={isRailActive(item.path, pathname) ? "chat-item--active" : ""}
                onClick={() => go(item.path)}
              >
                <IonIcon icon={item.icon} slot="start" />
                <IonLabel>{item.label}</IonLabel>
              </IonItem>
            ))}
          </IonList>
        </div>

        {projects.length > 0 && (
          <>
            <span className="menu-section">Projects</span>
            <IonAccordionGroup multiple>
              {projects.map((project) => {
                const projectChats = conversations.filter((c) => c.project_id === project.id);
                return (
                  <IonAccordion key={project.id} value={project.id}>
                    <IonItem slot="header" lines="none">
                      <IonLabel>{project.name}</IonLabel>
                      <IonIcon
                        icon={addCircleOutline}
                        slot="end"
                        className="project-add-icon"
                        aria-label={`New chat in ${project.name}`}
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
                            <IonLabel>No chats in here yet</IonLabel>
                          </IonItem>
                        )}
                        {projectChats.map((chat) => (
                          <IonItem
                            key={chat.id}
                            button
                            lines="none"
                            detail={false}
                            className={pathname === `/chat/${chat.id}` ? "chat-item--active" : ""}
                            onClick={() => go(`/chat/${chat.id}`)}
                          >
                            <IonLabel className="ion-text-nowrap">{chat.title}</IonLabel>
                            <IonIcon
                              icon={trashOutline}
                              slot="end"
                              className="chat-delete-icon"
                              aria-label={`Delete ${chat.title}`}
                              onClick={(e) => handleDelete(e, chat.id)}
                            />
                          </IonItem>
                        ))}
                      </IonList>
                    </div>
                  </IonAccordion>
                );
              })}
            </IonAccordionGroup>
          </>
        )}

        <span className="menu-section">Chats</span>
        <IonList>
          {unfiledChats.length === 0 && (
            <IonItem lines="none" className="chat-list-empty">
              <IonLabel>Start a chat and it shows up here</IonLabel>
            </IonItem>
          )}
          {unfiledChats.map((chat) => (
            <IonItem
              key={chat.id}
              button
              lines="none"
              detail={false}
              className={pathname === `/chat/${chat.id}` ? "chat-item--active" : ""}
              onClick={() => go(`/chat/${chat.id}`)}
            >
              <IonLabel className="ion-text-nowrap">{chat.title}</IonLabel>
              <IonIcon
                icon={trashOutline}
                slot="end"
                className="chat-delete-icon"
                aria-label={`Delete ${chat.title}`}
                onClick={(e) => handleDelete(e, chat.id)}
              />
            </IonItem>
          ))}
        </IonList>
      </IonContent>

      <IonFooter className="menu-footer">
        <IonItem lines="none" className="menu-footer-item">
          <IonLabel className="ion-text-nowrap">{userEmail}</IonLabel>
          <IonIcon
            icon={logOutOutline}
            slot="end"
            className="signout-icon"
            aria-label="Sign out"
            onClick={onSignOut}
          />
        </IonItem>
      </IonFooter>
    </IonMenu>
  );
}