import { useEffect, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { Capacitor } from "@capacitor/core";
import { supabase } from "../lib/supabase";
import { getDeviceInstallationId, currentPlatform } from "../lib/deviceId";
import { NATIVE_REDIRECT, startNativeGoogleSignIn } from "../lib/nativeAuth";

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
    supabase.auth
      .getSession()
      .then(({ data }) => {
        setUser(data.session?.user ?? null);
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
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
    // In the app the link must open the app, not the website — with the
    // native client on PKCE, a link that lands on the website has no way
    // to redeem its code.
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: Capacitor.isNativePlatform() ? { emailRedirectTo: NATIVE_REDIRECT } : undefined,
    });
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
    // In the app: Custom Tab + deep link back, never the website.
    if (Capacitor.isNativePlatform()) {
      await startNativeGoogleSignIn(forceAccountSelection);
      return;
    }
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
  async function linkWithCode(rawCode: string) {
    if (!BASE) throw new Error("AI backend isn't configured.");
    // Codes are typed or pasted by hand: drop spaces/dashes and fix case
    // so "abcd-efgh " still works.
    const code = rawCode.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (code.length !== 8) throw new Error("Enter the 8-character code from the website.");

    const deviceId = await getDeviceInstallationId();

    // The backend is on a free Render plan and can take ~50s to wake up,
    // so give it a long timeout and say so, instead of a bare
    // "Failed to fetch" that looks like the code was wrong.
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 70000);
    let resp: Response;
    try {
      resp = await fetch(`${BASE}/devices/link/consume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          device_installation_id: deviceId,
          platform: currentPlatform(),
        }),
        signal: ctrl.signal,
      });
    } catch (e) {
      throw new Error(
        e instanceof DOMException && e.name === "AbortError"
          ? "The server took too long to respond. It may be waking up — generate a new code and try again."
          : "Couldn't reach the server. Check your connection and try again.",
      );
    } finally {
      clearTimeout(timer);
    }

    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      const detail = typeof body?.detail === "string" ? body.detail : null;
      throw new Error(
        detail ??
          (resp.status >= 500
            ? "The server hit an error. Generate a new code and try again."
            : "That code didn't work."),
      );
    }

    const session = await resp.json();
    const { error } = await supabase.auth.setSession({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
    });
    if (error) {
      // Tokens were issued but this app's Supabase client rejected them —
      // almost always means the app and the backend are pointed at
      // different Supabase projects.
      throw new Error(`Linked, but sign-in failed: ${error.message}`);
    }
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