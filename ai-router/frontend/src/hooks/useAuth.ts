import { useEffect, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { Capacitor } from "@capacitor/core";
import { supabase } from "../lib/supabase";
import { getDeviceInstallationId, currentPlatform } from "../lib/deviceId";

const REMEMBER_KEY = "zorah:remember";
const BASE = import.meta.env.VITE_AI_BACKEND_URL;

export interface LinkedDevice {
  id: string;
  device_installation_id: string;
  platform: string;
  linked_at: string;
  last_seen: string;
  revoked_at: string | null;
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setUser(data.session?.user ?? null);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  // Every successful sign-in on the native app registers this install in
  // user_devices — not just the pairing-code path, so Google/password
  // logins done directly on the phone show up in Settings too. Best-effort
  // only: a failure here should never block the user from actually being
  // signed in.
  useEffect(() => {
    if (!user || !Capacitor.isNativePlatform() || !BASE) return;
    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        if (!token) return;
        const deviceId = await getDeviceInstallationId();
        await fetch(`${BASE}/devices/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ device_installation_id: deviceId, platform: currentPlatform() }),
        });
      } catch {
        // Non-fatal — the device just won't show in Settings until the
        // next successful sign-in.
      }
    })();
  }, [user]);

  /**
   * "Remember me" off means the session shouldn't outlive the tab. Supabase
   * always persists to storage, so we record the preference and drop the
   * local session on unload when it's switched off.
   */
  async function signInWithPassword(email: string, password: string, remember = true) {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    localStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
  }

  /**
   * New-account registration. Supabase's own signUp call is what
   * prevents duplicate accounts — it errors on an email that already
   * exists rather than silently creating a second one, so there's
   * nothing extra to check here for that.
   *
   * The new user's profiles row (tier=FREE, role=user) isn't created
   * here — it doesn't need to be. access/tiers.py's get_profile()
   * lazily creates that row with exactly those defaults the first time
   * anything checks this user's tier/role, which happens automatically
   * once they're in the app. New users are never granted admin — role
   * only ever becomes 'admin' via a direct database update, never
   * through any signup path.
   */
  async function signUpWithPassword(email: string, password: string): Promise<{ needsConfirmation: boolean }> {
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) throw error;
    // If this Supabase project requires email confirmation, signUp
    // returns a user but no session yet — session stays null until they
    // click the link in their inbox.
    return { needsConfirmation: data.session === null };
  }

  /** Magic link — also backs the "Forgot password?" action on the login page. */
  async function signInWithEmail(email: string) {
    const { error } = await supabase.auth.signInWithOtp({ email });
    if (error) throw error;
  }

  /**
   * forceAccountSelection is passed as true from the registration
   * screen — Google otherwise silently reuses whatever account last
   * signed in on this device, which is the wrong default when someone
   * is deliberately trying to register with a different account. Plain
   * login keeps calling this with no argument, unchanged.
   */
  async function signInWithGoogle(forceAccountSelection = false) {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: window.location.origin,
        ...(forceAccountSelection ? { queryParams: { prompt: "select_account" } } : {}),
      },
    });
    if (error) throw error;
  }

  async function signOut() {
    localStorage.removeItem(REMEMBER_KEY);
    await supabase.auth.signOut();
  }

  /** Website side: request a fresh pairing code for the current session. */
  async function startDeviceLink(): Promise<{ code: string; expires_in: number }> {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) throw new Error("Not signed in.");
    const resp = await fetch(`${BASE}/devices/link/start`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error("Couldn't generate a code. Try again.");
    return resp.json();
  }

  /**
   * Mobile side: exchange a code (typed in by the user) for a real
   * session. setSession() hands the returned tokens to supabase-js exactly
   * as if the user had just logged in normally — onAuthStateChange fires
   * and `user` above updates on its own.
   */
  async function linkWithCode(code: string) {
    if (!BASE) throw new Error("AI backend isn't configured.");
    const deviceId = await getDeviceInstallationId();
    const resp = await fetch(`${BASE}/devices/link/consume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: code.trim(),
        device_installation_id: deviceId,
        platform: currentPlatform(),
      }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      throw new Error(body?.detail || "That code didn't work.");
    }
    const session = await resp.json();
    const { error } = await supabase.auth.setSession({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
    });
    if (error) throw error;
  }

  async function listDevices(): Promise<LinkedDevice[]> {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return [];
    const resp = await fetch(`${BASE}/devices`, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) return [];
    return resp.json();
  }

  async function revokeDevice(deviceId: string) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    await fetch(`${BASE}/devices/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ device_id: deviceId }),
    });
  }

  return {
    user,
    loading,
    signInWithPassword,
    signUpWithPassword,
    signInWithEmail,
    signInWithGoogle,
    signOut,
    startDeviceLink,
    linkWithCode,
    listDevices,
    revokeDevice,
  };
}

// Registered once at module load rather than per hook instance.
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    if (localStorage.getItem(REMEMBER_KEY) === "0") {
      void supabase.auth.signOut({ scope: "local" });
    }
  });
}

// A revoked device should notice on its own the next time the app comes
// to the foreground, since Supabase has no per-device token revocation —
// see access/devices.py's revoke_device() docstring for why this is a
// check-in model. Native-only: the website has no concept of a "device"
// to revoke itself against.
if (typeof document !== "undefined" && Capacitor.isNativePlatform()) {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !BASE) return;
    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        if (!token) return;
        const deviceId = await getDeviceInstallationId();
        const resp = await fetch(
          `${BASE}/devices/self?device_installation_id=${encodeURIComponent(deviceId)}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (!resp.ok) return;
        const status = await resp.json();
        if (status.revoked) await supabase.auth.signOut();
      } catch {
        // Best-effort — a failed check just means we try again next
        // foreground rather than forcing a sign-out on a network blip.
      }
    })();
  });
}