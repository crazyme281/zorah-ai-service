/**
 * The Admin Dashboard — the landing page of the admin-only shell (see
 * App.tsx): an admin account opens straight here, on both the website
 * and the mobile app, with no normal-user interface shown first. From
 * here, other admin pages (currently just APK management) are reached
 * by navigating within the panel itself, via the card below.
 *
 * Deliberately scoped to what's real right now: an account summary and
 * a link into APK management (the one admin tool that actually exists).
 * Not fabricating usage/queue widgets with no real data behind them —
 * add cards here as each admin capability actually ships.
 */
import { useEffect, useState } from "react";
import { IonPage, IonContent, IonIcon } from "@ionic/react";
import { useIonRouter } from "@ionic/react";
import { shieldCheckmarkOutline, cubeOutline, chevronForwardOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { useAuth } from "../hooks/useAuth";
import { supabase } from "../lib/supabase";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

interface AdminApkRelease {
  version: string;
  version_code: number;
  file_name: string;
  file_size: number;
  uploaded_at: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AdminDashboardPage() {
  const router = useIonRouter();
  const { user } = useAuth();
  const [release, setRelease] = useState<AdminApkRelease | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        const resp = await fetch(`${BASE}/admin/apk`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!resp.ok) return;
        const body = await resp.json();
        setRelease(body.exists ? body.release : null);
      } catch {
        // The APK card below just falls back to "no release yet" wording.
      }
    })();
  }, []);

  return (
    <IonPage>
      <TopBar admin />
      <IonContent className="panel-page">
        <div className="admin-dash">
          <div className="admin-dash__header">
            <IonIcon icon={shieldCheckmarkOutline} />
            <div>
              <h2>Admin Dashboard</h2>
              <p>{user?.email}</p>
            </div>
          </div>

          <div className="admin-dash__cards">
            <button
              type="button"
              className="admin-dash__card"
              onClick={() => router.push("/admin/apk", "none", "push")}
            >
              <IonIcon icon={cubeOutline} className="admin-dash__card-icon" />
              <div className="admin-dash__card-body">
                <b>APK Release</b>
                <span>
                  {release
                    ? `Current: v${release.version} (code ${release.version_code}) — ${formatSize(
                        release.file_size,
                      )}, uploaded ${new Date(release.uploaded_at).toLocaleDateString()}`
                    : "No APK uploaded yet — upload one to make it available to users"}
                </span>
              </div>
              <IonIcon icon={chevronForwardOutline} className="admin-dash__card-chevron" />
            </button>
          </div>
        </div>
      </IonContent>
    </IonPage>
  );
}