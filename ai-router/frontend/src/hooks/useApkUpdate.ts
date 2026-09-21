/**
 * Ties together: what version is installed (native only, via
 * @capacitor/app), what version the backend says is current, and
 * whether either popup (promo / outdated) is allowed to show right now
 * per the server-tracked weekly caps in lib/apk.ts.
 *
 * Deliberately does NOT decide "am I outdated" from anything cached
 * locally — every render's outdated flag comes from a fresh
 * getCurrentApk() call, matching "don't trust the client" from the spec.
 */
import { useCallback, useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { App } from "@capacitor/app";
import { useAuth } from "./useAuth";
import {
  getCurrentApk,
  getApp,
  shouldShowPopup,
  markPopupShown,
  type ApkInfo,
  type GetAppProgress,
} from "../lib/apk";

export function useApkUpdate() {
  const { user, listDevices } = useAuth();
  const isNative = Capacitor.isNativePlatform();

  const [current, setCurrent] = useState<ApkInfo | null>(null);
  const [installedVersionCode, setInstalledVersionCode] = useState<number | null>(null);
  const [installedVersion, setInstalledVersion] = useState<string | null>(null);
  const [showUpdatePopup, setShowUpdatePopup] = useState(false);
  const [showPromoPopup, setShowPromoPopup] = useState(false);
  const [progress, setProgress] = useState<GetAppProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const outdated =
    isNative &&
    current !== null &&
    installedVersionCode !== null &&
    installedVersionCode < current.version_code;

  // Fetch current release + installed version once per session/user.
  useEffect(() => {
    if (!user) return;
    (async () => {
      setCurrent(await getCurrentApk());
      if (isNative) {
        try {
          const info = await App.getInfo();
          // Android's "build" field is versionCode as a string — the
          // one that actually matters for the comparison, per the spec's
          // explicit instruction not to compare version strings alone.
          const code = parseInt(info.build, 10);
          setInstalledVersionCode(Number.isFinite(code) ? code : null);
          setInstalledVersion(info.version);
        } catch {
          // App.getInfo() can fail in a plain mobile browser preview —
          // outdated just stays false rather than guessing.
        }
      }
    })();
  }, [user, isNative]);

  // Decide whether to actually show a popup, once we know both sides.
  useEffect(() => {
    if (!user || current === null) return;

    (async () => {
      if (isNative) {
        if (installedVersionCode !== null && installedVersionCode < current.version_code) {
          if (await shouldShowPopup("outdated")) {
            setShowUpdatePopup(true);
            markPopupShown("outdated");
          }
        }
      } else {
        // Website: only pitch the app to accounts with no active
        // android/ios device already linked — someone who's already
        // installed it doesn't need the popup, regardless of which
        // browser/tab they're currently in.
        const devices = await listDevices();
        const hasMobile = devices.some(
          (d) => (d.platform === "android" || d.platform === "ios") && !d.revoked_at,
        );
        if (!hasMobile && (await shouldShowPopup("promo"))) {
          setShowPromoPopup(true);
          markPopupShown("promo");
        }
      }
    })();
    // installedVersionCode and current are the only real dependencies —
    // listDevices is stable enough per render not to need chasing here.
     
  }, [user, current, installedVersionCode, isNative]);

  const startUpdate = useCallback(async () => {
    setError(null);
    setProgress(null);
    try {
      await getApp(setProgress);
      setShowUpdatePopup(false);
      setShowPromoPopup(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't get the app right now.");
    } finally {
      setProgress(null);
    }
  }, []);

  return {
    current,
    installedVersion,
    installedVersionCode,
    outdated,
    showUpdatePopup,
    showPromoPopup,
    dismissUpdatePopup: () => setShowUpdatePopup(false),
    dismissPromoPopup: () => setShowPromoPopup(false),
    startUpdate,
    progress,
    error,
  };
}