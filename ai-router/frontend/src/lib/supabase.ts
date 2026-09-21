import { createClient } from "@supabase/supabase-js";
import { Capacitor } from "@capacitor/core";
import type { Database } from "./database.types";
import { capacitorStorageAdapter } from "./deviceId";

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

if (!url || !key) {
  throw new Error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY — check your .env file.",
  );
}

// On the website, default storage (localStorage) is fine. Inside the
// Android/iOS app, route the session through Capacitor Preferences instead
// — see deviceId.ts for why.
export const supabase = createClient<Database>(url, key, {
  auth: Capacitor.isNativePlatform() ? { storage: capacitorStorageAdapter } : undefined,
});