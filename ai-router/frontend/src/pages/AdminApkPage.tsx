/**
 * Admin-only APK management. Reachable at /admin/apk — no nav link
 * anywhere in the app links here, on purpose; an admin navigates to it
 * directly. That's obscurity, not security: the real boundary is
 * server-side (require_admin in api.py, checking profiles.role fresh on
 * every call), which is what actually stops a non-admin from using these
 * endpoints even if they discover the URL.
 *
 * Works on both web and the native app — admin access isn't
 * web-only. There's still no nav link to this page anywhere; an admin
 * reaches it by navigating here directly, same as before.
 */
import { useEffect, useRef, useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner } from "@ionic/react";
import { cloudUploadOutline, trashOutline, checkmarkCircleOutline, downloadOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { supabase } from "../lib/supabase";
import { getApp } from "../lib/apk";

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
  const fileRef = useRef<HTMLInputElement>(null);

  const [status, setStatus] = useState<"loading" | "forbidden" | "ready">("loading");
  const [release, setRelease] = useState<AdminApkRelease | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadingName, setUploadingName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    setUploadingName(file.name);
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

      // Auto-download a copy to the uploading admin's own device. A
      // failure here is deliberately non-fatal and shown separately —
      // the upload itself already succeeded (confirmed by the backend
      // response above), so this shouldn't read as "the upload failed."
      try {
        await getApp();
      } catch (e) {
        setError(
          `Uploaded successfully, but couldn't auto-download a copy: ${
            e instanceof Error ? e.message : "unknown error"
          }. Use the Download button below to get it manually.`,
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      setUploadingName(null);
    }
  }

  async function handleDownloadToDevice() {
    setDownloading(true);
    setError(null);
    try {
      await getApp();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the download.");
    } finally {
      setDownloading(false);
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
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || "Delete failed.");
      }
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
                    Download a copy to this device
                    <button type="button" onClick={handleDownloadToDevice} disabled={downloading}>
                      <IonIcon icon={downloadOutline} />
                      {downloading ? "Starting…" : "Download"}
                    </button>
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
                  {/* preventDefault on BOTH dragover and drop is what stops
                      the browser from just opening/downloading the dropped
                      file itself — without it, dropping never reaches
                      handleUpload at all. */}
                  <div
                    className={`admin-apk__upload ${dragOver ? "admin-apk__upload--active" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (!uploading) setDragOver(true);
                    }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragOver(false);
                      const file = e.dataTransfer.files?.[0];
                      if (file && !uploading) handleUpload(file);
                    }}
                  >
                    <IonIcon icon={cloudUploadOutline} />
                    <p>
                      {uploading
                        ? `Uploading ${uploadingName ?? "APK"}… this can take a minute for large files.`
                        : "No current APK. Drag an .apk file here, or choose one to upload."}
                    </p>
                    <button
                      type="button"
                      className="admin-apk__upload-btn"
                      onClick={() => fileRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? <IonSpinner name="crescent" /> : "Choose APK"}
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