/**
 * Device identity, for the device-linking flow — and the storage adapter
 * that lets Supabase's session persist through Capacitor Preferences
 * instead of a bare webview localStorage.
 *
 * device_installation_id is generated once per install and never derived
 * from hardware — it's a label the backend uses to tell devices apart,
 * not a credential. Uninstalling and reinstalling the app gets you a new
 * one; that's intentional, since a hardware ID that outlives an uninstall
 * would make revoking a device meaningless.
 */
import { Preferences } from "@capacitor/preferences";
import { Capacitor } from "@capacitor/core";

const DEVICE_ID_KEY = "zorah:device-installation-id";

let cached: string | null = null;

export async function getDeviceInstallationId(): Promise<string> {
  if (cached) return cached;

  const { value } = await Preferences.get({ key: DEVICE_ID_KEY });
  if (value) {
    cached = value;
    return value;
  }

  const id = crypto.randomUUID();
  await Preferences.set({ key: DEVICE_ID_KEY, value: id });
  cached = id;
  return id;
}

export function currentPlatform(): "android" | "ios" | "web" {
  const p = Capacitor.getPlatform();
  return p === "android" || p === "ios" ? p : "web";
}

/**
 * Supabase's default storage is plain localStorage, which is fine on the
 * website but sits in the Android webview's storage on mobile — this
 * adapter routes the same calls through Capacitor Preferences instead,
 * which is the documented approach for Supabase inside a Capacitor app.
 * Only used when running natively; the web build keeps default storage.
 */
export const capacitorStorageAdapter = {
  getItem: async (key: string) => (await Preferences.get({ key })).value,
  setItem: async (key: string, value: string) => {
    await Preferences.set({ key, value });
  },
  removeItem: async (key: string) => {
    await Preferences.remove({ key });
  },
};