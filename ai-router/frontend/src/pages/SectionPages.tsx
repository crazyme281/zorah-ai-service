/**
 * The three non-chat rail destinations. History is real (it reads the same
 * conversations the drawer shows); Images is a stub until the backend
 * returns image attachments; Settings is account plus sign-out.
 */
import { useEffect, useState } from "react";
import type { MouseEvent } from "react";
import { IonPage, IonContent, IonList, IonItem, IonLabel, IonIcon, useIonRouter } from "@ionic/react";
import { Capacitor } from "@capacitor/core";
import {
  imagesOutline,
  timeOutline,
  trashOutline,
  phonePortraitOutline,
  desktopOutline,
  logoApple,
  copyOutline,
  checkmarkOutline,
  downloadOutline,
} from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { useAuth, type LinkedDevice } from "../hooks/useAuth";
import { useApkUpdate } from "../hooks/useApkUpdate";
import { getApp } from "../lib/apk";
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

function platformIcon(platform: string) {
  if (platform === "android") return phonePortraitOutline;
  if (platform === "ios") return logoApple;
  return desktopOutline;
}

function DeviceLinkPanel() {
  const { startDeviceLink } = useAuth();
  const [code, setCode] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const t = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [secondsLeft]);

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const result = await startDeviceLink();
      setCode(result.code);
      setSecondsLeft(result.expires_in);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't generate a code.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard unavailable — the code is already on screen to read.
    }
  }

  const expired = code !== null && secondsLeft <= 0;

  return (
    <div className="settings-card devicelink-card">
      <div className="settings-row">
        Get the mobile app
        <span>Install once, then link it here</span>
      </div>
      <div className="devicelink-body">
        {code && !expired ? (
          <>
            <div className="devicelink-code">
              {code}
              <button type="button" onClick={handleCopy} aria-label="Copy code">
                <IonIcon icon={copied ? checkmarkOutline : copyOutline} />
              </button>
            </div>
            <p className="devicelink-hint">
              Open the Zorah AI app, tap &ldquo;Have a code?&rdquo; on the login screen, and enter
              this within {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}.
            </p>
          </>
        ) : (
          <button type="button" onClick={handleGenerate} disabled={busy}>
            {busy ? "Generating…" : expired ? "Generate a new code" : "Link mobile app"}
          </button>
        )}
        {error && <p className="devicelink-error">{error}</p>}
      </div>
    </div>
  );
}

function DevicesList() {
  const { listDevices, revokeDevice } = useAuth();
  const [devices, setDevices] = useState<LinkedDevice[] | null>(null);

  async function refresh() {
    setDevices(await listDevices());
  }

  useEffect(() => {
    refresh();
    // Runs once per Settings visit — the list doesn't need to poll live.
     
  }, []);

  async function handleRevoke(id: string) {
    if (!window.confirm("Revoke this device? It'll be signed out next time it's opened.")) return;
    await revokeDevice(id);
    refresh();
  }

  const active = (devices ?? []).filter((d) => !d.revoked_at);
  if (devices !== null && active.length === 0) return null;

  return (
    <div className="settings-card">
      <div className="settings-row">
        Linked devices
        <span>{active.length}</span>
      </div>
      {active.map((d) => (
        <div className="settings-row devicelink-row" key={d.id}>
          <span className="devicelink-row__label">
            <IonIcon icon={platformIcon(d.platform)} />
            {d.platform === "android" ? "Android" : d.platform === "ios" ? "iOS" : "Web"}
          </span>
          <button type="button" onClick={() => handleRevoke(d.id)}>
            Revoke
          </button>
        </div>
      ))}
    </div>
  );
}

function GetAppRow() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGetApp() {
    setBusy(true);
    setError(null);
    try {
      await getApp();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the download.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-card">
      <div className="settings-row">
        Get the mobile app
        <button type="button" onClick={handleGetApp} disabled={busy}>
          <IonIcon icon={downloadOutline} />
          {busy ? "Starting…" : "Get App"}
        </button>
      </div>
      {error && <p className="admin-apk__error">{error}</p>}
    </div>
  );
}

function AppVersionRow() {
  const { installedVersion, outdated, startUpdate, progress } = useApkUpdate();

  return (
    <div className="settings-card">
      <div className="settings-row">
        App Version {installedVersion ?? ""}
        {outdated ? (
          <button type="button" className="version-indicator version-indicator--update" onClick={startUpdate} disabled={progress !== null}>
            <span className="version-indicator__dot" />
            {progress ? "Updating…" : "Update"}
          </button>
        ) : (
          <span className="version-indicator version-indicator--current">
            <span className="version-indicator__dot" />
            Up to date
          </span>
        )}
      </div>
    </div>
  );
}

export function SettingsPage() {
  const { user, signOut } = useAuth();
  const isNative = Capacitor.isNativePlatform();

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

        <div className="settings-group">
          <h3>App</h3>
          {isNative ? <AppVersionRow /> : <GetAppRow />}
        </div>

        <div className="settings-group">
          <h3>Devices</h3>
          {/* Generating a pairing code only makes sense from a session
              that's already authenticated somewhere you'd type a code
              into a DIFFERENT device — i.e. the website, not the app
              you'd be linking. */}
          {!isNative && <DeviceLinkPanel />}
          <DevicesList />
        </div>
      </IonContent>
    </IonPage>
  );
}