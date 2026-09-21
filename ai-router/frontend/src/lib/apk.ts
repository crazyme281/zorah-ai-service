/**
 * Backend calls for the APK release system, plus the one piece of actual
 * platform branching: getApp() downloads-and-installs natively, and just
 * opens the signed URL as a normal browser download on the website.
 */
import { Capacitor } from "@capacitor/core";
import { supabase } from "./supabase";
import ApkInstaller from "./apkInstaller";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

export interface ApkInfo {
  version: string;
  version_code: number;
  file_name: string;
  file_size: number;
  uploaded_at: string;
}

export interface ApkDownload extends Pick<ApkInfo, "version" | "version_code" | "file_name" | "file_size"> {
  url: string;
  expires_in: number;
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Null when no release has been uploaded yet — not an error state. */
export async function getCurrentApk(): Promise<ApkInfo | null> {
  const resp = await fetch(`${BASE}/apk/current`, { headers: await authHeader() });
  if (!resp.ok) return null;
  return resp.json();
}

async function getDownloadInfo(): Promise<ApkDownload> {
  const resp = await fetch(`${BASE}/apk/download`, { headers: await authHeader() });
  if (!resp.ok) throw new Error("No app download is available right now.");
  return resp.json();
}

export async function shouldShowPopup(type: "promo" | "outdated"): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE}/apk/popup/should-show?popup_type=${type}`, {
      headers: await authHeader(),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    return !!data.show;
  } catch {
    return false;
  }
}

export async function markPopupShown(type: "promo" | "outdated"): Promise<void> {
  try {
    await fetch(`${BASE}/apk/popup/mark-shown`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeader()) },
      body: JSON.stringify({ popup_type: type }),
    });
  } catch {
    // Best-effort — worst case the cap resets a little late.
  }
}

export type GetAppProgress = { stage: "starting" | "downloading" | "installing"; percent?: number };

/**
 * The actual "Get App" / "Update" action. On the website this is just a
 * normal file download the browser handles on its own — clicking a
 * signed URL to an .apk file triggers Android's or the browser's own
 * save/open handling with no code needed on our side. On the native app
 * it downloads to cache and explicitly opens the system installer, since
 * there's no "click a link" affordance inside a Capacitor webview that
 * would trigger the same thing.
 */
export async function getApp(onProgress?: (p: GetAppProgress) => void): Promise<void> {
  onProgress?.({ stage: "starting" });
  const info = await getDownloadInfo();

  if (!Capacitor.isNativePlatform()) {
    // Let the browser's own download UI take over entirely.
    window.open(info.url, "_blank");
    return;
  }

  let progressListener: { remove: () => void } | null = null;
  try {
    progressListener = await ApkInstaller.addListener("downloadProgress", (data) => {
      onProgress?.({ stage: "downloading", percent: data.percent });
    });

    onProgress?.({ stage: "downloading", percent: 0 });
    const { path } = await ApkInstaller.download({ url: info.url, fileName: info.file_name });

    onProgress?.({ stage: "installing" });
    await ApkInstaller.install({ path });
  } finally {
    progressListener?.remove();
  }
}