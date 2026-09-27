/**
 * Admin-only APK management — one of the two pages in the admin-only
 * shell (see App.tsx), reachable at /admin/apk on both the website and
 * the mobile app. No nav link anywhere outside the admin shell points
 * here — the real access boundary is server-side (require_admin in
 * api.py, checking profiles.role fresh on every call), which is what
 * actually stops a non-admin from using these endpoints even if they
 * discover the URL.
 */
import { useEffect, useRef, useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner, IonProgressBar } from "@ionic/react";
import { cloudUploadOutline, cloudDownloadOutline, trashOutline, checkmarkCircleOutline } from "ionicons/icons";
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
  const [uploadPercent, setUploadPercent] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justUploaded, setJustUploaded] = useState(false);
  const [downloadState, setDownloadState] = useState<
    "idle" | "downloading" | "done" | "failed"
  >("idle");

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
    setUploadPercent(0);
    setError(null);
    setJustUploaded(false);
    setDownloadState("idle");
    try {
      const headers = await authHeader();
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${BASE}/admin/apk/upload`);
        for (const [key, value] of Object.entries(headers)) xhr.setRequestHeader(key, value);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) setUploadPercent(Math.round((e.loaded / e.total) * 100));
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve();
            return;
          }
          let detail = "Upload failed.";
          try {
            detail = JSON.parse(xhr.responseText)?.detail || detail;
          } catch {
            // Non-JSON error body — fall back to the generic message.
          }
          reject(new Error(detail));
        };
        xhr.onerror = () => reject(new Error("Upload failed — check your connection."));
        const form = new FormData();
        form.append("file", file);
        xhr.send(form);
      });
      await refresh();
      setJustUploaded(true);
      setTimeout(() => setJustUploaded(false), 4000);

      // The upload itself already succeeded (the release row exists) —
      // this is a best-effort convenience on top of it, so a failure
      // here is reported separately and never rolls back or re-throws
      // into the upload's own error state.
      setDownloadState("downloading");
      try {
        await getApp();
        setDownloadState("done");
      } catch {
        setDownloadState("failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      setUploadPercent(0);
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
              {justUploaded && (
                <p className="admin-apk__success">
                  <IonIcon icon={checkmarkCircleOutline} /> APK uploaded — it's now available to
                  users.
                </p>
              )}

              {downloadState === "downloading" && (
                <p className="admin-apk__success admin-apk__success--muted">
                  <IonSpinner name="crescent" /> Downloading the APK to this device…
                </p>
              )}
              {downloadState === "done" && (
                <p className="admin-apk__success">
                  <IonIcon icon={checkmarkCircleOutline} /> Downloaded to this device.
                </p>
              )}
              {downloadState === "failed" && (
                <p className="admin-apk__error">
                  Upload succeeded, but the automatic download to this device failed — use the
                  file below to get it manually.
                </p>
              )}

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
                    Get it on this device
                    <button
                      type="button"
                      onClick={async () => {
                        setDownloadState("downloading");
                        try {
                          await getApp();
                          setDownloadState("done");
                        } catch {
                          setDownloadState("failed");
                        }
                      }}
                      disabled={downloadState === "downloading"}
                    >
                      <IonIcon icon={cloudDownloadOutline} />
                      {downloadState === "downloading" ? "Downloading…" : "Download"}
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
                  <div className="admin-apk__upload">
                    <IonIcon icon={cloudUploadOutline} />
                    <p>No current APK. Upload one to make it available to users.</p>
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? `Uploading… ${uploadPercent}%` : "Upload APK"}
                    </button>
                    {uploading && (
                      <IonProgressBar
                        className="admin-apk__progress"
                        value={uploadPercent / 100}
                      />
                    )}
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