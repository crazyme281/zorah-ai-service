import { createClient } from "@supabase/supabase-js";
import { Capacitor } from "@capacitor/core";
import type { Database } from "./database.types";
import { capacitorStorageAdapter } from "./deviceId";

const url = import.meta.env.VITE_SUPABASE_URL;
// Accept either name: newer Supabase projects call it the "publishable"
// key, older ones (and this project's .env) call it the "anon" key.
const key =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !key) {
  // Don't throw at import time: that kills the whole bundle before React
  // mounts and leaves a blank white screen with no clue why.
  console.error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY / VITE_SUPABASE_ANON_KEY — check your .env file.",
  );
}

// On the website, default storage (localStorage) is fine. Inside the
// Android/iOS app, route the session through Capacitor Preferences instead
// — see deviceId.ts for why.
export const supabase = createClient<Database>(url ?? "http://missing-supabase-url.invalid", key ?? "missing-key", {
  // Native: PKCE so the Google/magic-link redirect back into the app (a
  // custom-scheme deep link, see nativeAuth.ts) carries a one-time code
  // only this install can redeem. detectSessionInUrl is off because
  // nativeAuth.ts handles the callback itself.
  auth: Capacitor.isNativePlatform()
    ? { storage: capacitorStorageAdapter, flowType: "pkce", detectSessionInUrl: false }
    : undefined,
});