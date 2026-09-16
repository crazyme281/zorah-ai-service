import { useEffect, useState } from "react";
import { IonApp, IonPage, IonRouterOutlet, IonSpinner, IonSplitPane } from "@ionic/react";
import { IonReactRouter } from "@ionic/react-router";
import { Route, Redirect } from "react-router-dom";

import { useAuth } from "./hooks/useAuth";
import { useProjects } from "./hooks/useProjects";
import { useConversations } from "./hooks/useConversations";
import { AppMenu } from "./components/AppMenu";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";

export default function App() {
  const { user, loading: authLoading, signInWithEmail, signOut } = useAuth();
  const { projects, createProject } = useProjects(user?.id);
  const { conversations, createConversation } = useConversations(user?.id);
  const [pendingRedirect, setPendingRedirect] = useState<string | null>(null);

  // After creating a chat from the menu, hand off a one-shot redirect
  // target to whichever route renders next.
  useEffect(() => {
    if (pendingRedirect) {
      const t = setTimeout(() => setPendingRedirect(null), 50);
      return () => clearTimeout(t);
    }
  }, [pendingRedirect]);

  if (authLoading) {
    return (
      <IonApp>
        <IonPage className="ion-justify-content-center ion-align-items-center loading-page">
          <IonSpinner name="dots" />
        </IonPage>
      </IonApp>
    );
  }

  if (!user) {
    return (
      <IonApp>
        <LoginPage onSubmitEmail={signInWithEmail} />
      </IonApp>
    );
  }

  async function handleNewChat(projectId: string | null) {
    const chat = await createConversation(projectId);
    if (chat) setPendingRedirect(`/chat/${chat.id}`);
  }

  async function handleNewProject() {
    await createProject();
  }

  return (
    <IonApp>
      <IonReactRouter>
        <IonSplitPane contentId="main-content" when="md">
          <AppMenu
            projects={projects}
            conversations={conversations}
            onNewChat={handleNewChat}
            onNewProject={handleNewProject}
            userEmail={user.email ?? null}
            onSignOut={signOut}
          />
          <IonRouterOutlet id="main-content">
            <Route exact path="/chat/:conversationId" component={ChatPage} />
            <Route exact path="/">
              {pendingRedirect ? (
                <Redirect to={pendingRedirect} />
              ) : conversations.length > 0 ? (
                <Redirect to={`/chat/${conversations[0].id}`} />
              ) : (
                <ChatPage />
              )}
            </Route>
          </IonRouterOutlet>
        </IonSplitPane>
      </IonReactRouter>
    </IonApp>
  );
}
