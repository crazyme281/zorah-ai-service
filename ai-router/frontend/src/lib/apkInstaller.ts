/**
 * Thin typed wrapper around the native ApkInstaller plugin (see
 * android/app/src/main/java/ai/zorah/app/ApkInstallerPlugin.java).
 * Native-only — every caller of this module must already be behind a
 * Capacitor.isNativePlatform() check (see lib/apk.ts), since there's no
 * web implementation to fall back to.
 */
import { registerPlugin, type PluginListenerHandle } from "@capacitor/core";

export interface ApkInstallerPlugin {
  /** Streams the file at `url` into the app's cache dir, returns the
   * local path once complete. Emits 'downloadProgress' events while it
   * runs if the server sent a Content-Length. */
  download(options: { url: string; fileName?: string }): Promise<{ path: string }>;
  /** Opens Android's package installer for a file previously returned by
   * download(). Resolves once the installer intent was launched — NOT
   * once the user finishes installing; Android gives no such callback. */
  install(options: { path: string }): Promise<void>;
  addListener(
    eventName: "downloadProgress",
    listenerFunc: (data: { percent: number }) => void,
  ): Promise<PluginListenerHandle>;
}

const ApkInstaller = registerPlugin<ApkInstallerPlugin>("ApkInstaller");

export default ApkInstaller;