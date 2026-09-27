import { useEffect, useState } from "react";
import { IonApp, IonRouterOutlet } from "@ionic/react";
import { IonReactRouter } from "@ionic/react-router";
import { Route, Redirect } from "react-router-dom";

import { useAuth } from "./hooks/useAuth";
import { useProjects } from "./hooks/useProjects";
import { useConversations } from "./hooks/useConversations";
import { usePlan } from "./hooks/usePlan";
import { AppMenu } from "./components/AppMenu";
import { IconRail } from "./components/IconRail";
import { SplashScreen } from "./components/SplashScreen";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ImagesPage, HistoryPage, SettingsPage } from "./pages/SectionPages";
import { CodeFixerPage } from "./pages/CodeFixerPage";
import { UpgradePage } from "./pages/UpgradePage";
import { AdminApkPage } from "./pages/AdminApkPage";
import { AdminDashboardPage } from "./pages/AdminDashboardPage";
import { ApkPopups } from "./components/ApkPopups";

/** Minimum time the splash stays up, so the brand doesn't flash past. */
const SPLASH_MS = 1400;

export default function App() {
  const {
    user,
    loading: authLoading,
    signInWithPassword,
    signUpWithPassword,
    signInWithEmail,
    signInWithGoogle,
    signOut,
    linkWithCode,
  } = useAuth();
  const { projects, createProject } = useProjects(user?.id);
  const { conversations, createConversation, deleteConversation } = useConversations(user?.id);
  const { plan, loading: planLoading } = usePlan();
  const isAdmin = plan?.role === "admin";

  const [splashDone, setSplashDone] = useState(false);
  const [splashGone, setSplashGone] = useState(false);
  const [pendingRedirect, setPendingRedirect] = useState<string | null>(null);
  // Pre-login state toggle rather than a route — mirrors how the login
  // screen itself has never had a URL route of its own (see the
  // ready && (!user ? ... ) branch below, which sits outside
  // IonReactRouter entirely).
  const [showRegister, setShowRegister] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSplashDone(true), SPLASH_MS);
    return () => clearTimeout(t);
  }, []);

  // Unmount the splash only after its fade-out has finished.
  useEffect(() => {
    if (splashDone && !authLoading) {
      const t = setTimeout(() => setSplashGone(true), 460);
      return () => clearTimeout(t);
    }
  }, [splashDone, authLoading]);

  useEffect(() => {
    if (pendingRedirect) {
      const t = setTimeout(() => setPendingRedirect(null), 50);
      return () => clearTimeout(t);
    }
  }, [pendingRedirect]);

  const showSplash = !splashGone;
  // Waiting on planLoading too (once there's a user) means the role is
  // always known before either shell below ever renders a single frame —
  // an admin account never flashes the normal chat interface first.
  const ready = splashDone && !authLoading && (!user || !planLoading);

  async function handleNewChat(projectId: string | null) {
    const chat = await createConversation(projectId);
    if (chat) setPendingRedirect(`/chat/${chat.id}`);
  }

  async function handleNewProject() {
    await createProject();
  }

  return (
    <IonApp>
      {showSplash && <SplashScreen exiting={ready} />}

      {ready &&
        (!user ? (
          showRegister ? (
            <RegisterPage
              onRegister={signUpWithPassword}
              onGoogle={() => signInWithGoogle(true)}
              onBackToLogin={() => setShowRegister(false)}
            />
          ) : (
            <LoginPage
              onSubmitPassword={signInWithPassword}
              onSubmitMagicLink={signInWithEmail}
              onGoogle={signInWithGoogle}
              onLinkWithCode={linkWithCode}
              onShowRegister={() => setShowRegister(true)}
            />
          )
        ) : isAdmin ? (
          // Admin accounts land on the Admin Dashboard directly — the
          // normal chat interface is never mounted for them at all, not
          // just redirected away from after a flash. From here they only
          // reach other admin pages (currently just APK management) by
          // navigating within the panel itself (see AdminDashboardPage's
          // own link to /admin/apk) — same components, same design as
          // the rest of the app, just without the chat shell around them.
          <IonReactRouter>
            <div className="app-shell">
              <div className="app-shell__main">
                <IonRouterOutlet id="main-content">
                  <Route exact path="/admin" component={AdminDashboardPage} />
                  <Route exact path="/admin/apk" component={AdminApkPage} />
                  <Route render={() => <Redirect to="/admin" />} />
                </IonRouterOutlet>
              </div>
            </div>
          </IonReactRouter>
        ) : (
          <IonReactRouter>
            <AppMenu
              projects={projects}
              conversations={conversations}
              onNewChat={handleNewChat}
              onNewProject={handleNewProject}
              onDeleteChat={deleteConversation}
              userEmail={user.email ?? null}
              onSignOut={signOut}
            />
            <ApkPopups />
            <div className="app-shell">
              <IconRail />
              <div className="app-shell__main">
                <IonRouterOutlet id="main-content">
                  <Route exact path="/chat/:conversationId" component={ChatPage} />
                  <Route exact path="/images" component={ImagesPage} />
                  <Route exact path="/code" component={CodeFixerPage} />
                  <Route exact path="/history" component={HistoryPage} />
                  <Route exact path="/settings" component={SettingsPage} />
                  <Route exact path="/upgrade" component={UpgradePage} />
                  <Route exact path="/">
                    {pendingRedirect ? <Redirect to={pendingRedirect} /> : <ChatPage />}
                  </Route>
                  <Route render={() => <Redirect to="/" />} />
                </IonRouterOutlet>
              </div>
            </div>
          </IonReactRouter>
        ))}
    </IonApp>
  );
}