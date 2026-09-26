/**
 * Admin-only APK management. Reachable at /admin/apk — no nav link
 * anywhere in the app links here, on purpose; an admin navigates to it
 * directly. That's obscurity, not security: the real boundary is
 * server-side (require_admin in api.py, checking profiles.role fresh on
 * every call), which is what actually stops a non-admin from using these
 * endpoints even if they discover the URL.
 *
 * Redirects away entirely on the native app — "admin exists only on the
 * web" is enforced here at the route level, on top of there being no
 * link to it anywhere a mobile user would find it.
 */
import { useEffect, useRef, useState } from "react";
import { useIonRouter, IonPage, IonContent, IonIcon, IonSpinner } from "@ionic/react";
import { Capacitor } from "@capacitor/core";
import { cloudUploadOutline, trashOutline, checkmarkCircleOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { supabase } from "../lib/supabase";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

interface AdminApkRelease {
  id: string;
  version: string;
  version_code: number;
  package_name: string;
  file_name: string;
  storage_path: string;
  file_size: number;
  uploaded_at: string;
  uploaded_by: string;
  is_current: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function AdminApkPage() {
  const router = useIonRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [status, setStatus] = useState<"loading" | "forbidden" | "ready">("loading");
  const [release, setRelease] = useState<AdminApkRelease | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      router.push("/", "none", "replace");
    }
  }, [router]);

  async function refresh() {
    try {
      const resp = await fetch(`${BASE}/admin/apk`, { headers: await authHeader() });
      if (resp.status === 403) {
        setStatus("forbidden");
        return;
      }
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setRelease(data.exists ? data.release : null);
      setStatus("ready");
    } catch {
      setStatus("forbidden");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".apk")) {
      setError("Only .apk files are accepted.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(`${BASE}/admin/apk/upload`, {
        method: "POST",
        headers: await authHeader(),
        body: form,
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || "Upload failed.");
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Delete the current APK? This can't be undone.")) return;
    setDeleting(true);
    setError(null);
    try {
      const resp = await fetch(`${BASE}/admin/apk`, {
        method: "DELETE",
        headers: await authHeader(),
      });
      if (!resp.ok) throw new Error("Delete failed.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <IonPage>
      <TopBar admin />
      <IonContent className="panel-page">
        <div className="settings-group admin-apk">
          <h3>APK Release</h3>

          {status === "loading" && (
            <div className="admin-apk__loading">
              <IonSpinner name="crescent" />
            </div>
          )}

          {status === "forbidden" && (
            <div className="settings-card">
              <div className="settings-row">Access denied — this account isn't an admin.</div>
            </div>
          )}

          {status === "ready" && (
            <>
              {release ? (
                <div className="settings-card">
                  <div className="settings-row">
                    Status
                    <span className="admin-apk__status">
                      <IonIcon icon={checkmarkCircleOutline} /> Current
                    </span>
                  </div>
                  <div className="settings-row">
                    Version
                    <span>
                      {release.version} (code {release.version_code})
                    </span>
                  </div>
                  <div className="settings-row">
                    File
                    <span>{release.file_name}</span>
                  </div>
                  <div className="settings-row">
                    Size
                    <span>{formatSize(release.file_size)}</span>
                  </div>
                  <div className="settings-row">
                    Uploaded
                    <span>{new Date(release.uploaded_at).toLocaleString()}</span>
                  </div>
                  <div className="settings-row">
                    Delete before uploading a new version
                    <button type="button" onClick={handleDelete} disabled={deleting}>
                      <IonIcon icon={trashOutline} />
                      {deleting ? "Deleting…" : "Delete Old APK"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="settings-card">
                  <div className="admin-apk__upload">
                    <IonIcon icon={cloudUploadOutline} />
                    <p>No current APK. Upload one to make it available to users.</p>
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? <IonSpinner name="crescent" /> : "Upload APK"}
                    </button>
                  </div>
                </div>
              )}

              {error && <p className="admin-apk__error">{error}</p>}
            </>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".apk"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleUpload(file);
            e.target.value = "";
          }}
        />
      </IonContent>
    </IonPage>
  );
}