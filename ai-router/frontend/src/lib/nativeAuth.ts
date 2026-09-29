/**
 * Keeps Google (and magic-link) sign-in inside the Android app instead of
 * bouncing through the website.
 *
 * How it works:
 *   1. The app asks Supabase for the Google sign-in URL but does NOT
 *      navigate the webview to it (skipBrowserRedirect). Google refuses
 *      OAuth inside embedded webviews, so the URL is opened in a Chrome
 *      Custom Tab instead.
 *   2. After Google, Supabase redirects to NATIVE_REDIRECT
 *      (ai.zorah.app://auth/callback). Android's intent-filter in
 *      AndroidManifest.xml routes that link back into this app.
 *   3. The @capacitor/app `appUrlOpen` event fires here, and the one-time
 *      `code` in the link is exchanged for a real session (PKCE).
 *
 * `onAuthStateChange` in useAuth then sees the new session and the app
 * moves past the login screen — no website involved.
 *
 * NATIVE_REDIRECT must be listed under Supabase → Authentication → URL
 * Configuration → Redirect URLs, or Supabase falls back to the Site URL
 * (the website).
 */
import { useEffect } from "react";
import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { supabase } from "./supabase";

export const NATIVE_REDIRECT = "ai.zorah.app://auth/callback";

const ERROR_EVENT = "zorah:auth-error";

// The same link can arrive twice (cold-start launch URL + appUrlOpen).
const handled = new Set<string>();

function emitError(message: string) {
  window.dispatchEvent(new CustomEvent(ERROR_EVENT, { detail: message }));
}

/** Lets a login screen show errors that happen after the browser hands
 * control back (cancelled, denied, expired link, …). */
export function useAuthCallbackError(onError: (message: string) => void) {
  useEffect(() => {
    const handler = (e: Event) => onError(String((e as CustomEvent).detail));
    window.addEventListener(ERROR_EVENT, handler);
    return () => window.removeEventListener(ERROR_EVENT, handler);
  }, [onError]);
}

async function handleAuthCallback(url: string) {
  if (!url.startsWith(NATIVE_REDIRECT) || handled.has(url)) return;
  handled.add(url);

  // Dismiss the Custom Tab if it's still up (no-op / unsupported on some
  // Android versions — the singleTask launch mode usually clears it anyway).
  try {
    await Browser.close();
  } catch {
    /* ignore */
  }

  try {
    const parsed = new URL(url);
    const query = parsed.searchParams;
    const hash = new URLSearchParams(parsed.hash.replace(/^#/, ""));

    const failure = query.get("error_description") ?? hash.get("error_description") ?? query.get("error") ?? hash.get("error");
    if (failure) {
      emitError(failure.replace(/\+/g, " "));
      return;
    }

    const code = query.get("code");
    if (code) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (error) emitError(`Sign-in failed: ${error.message}`);
      return;
    }

    // Fallback for an implicit-flow style link carrying tokens directly.
    const accessToken = hash.get("access_token");
    const refreshToken = hash.get("refresh_token");
    if (accessToken && refreshToken) {
      const { error } = await supabase.auth.setSession({ access_token: accessToken, refresh_token: refreshToken });
      if (error) emitError(`Sign-in failed: ${error.message}`);
      return;
    }

    emitError("Sign-in didn't complete. Please try again.");
  } catch (e) {
    emitError(e instanceof Error ? e.message : "Sign-in didn't complete. Please try again.");
  }
}

let started = false;

/** Call once at startup. No-op on the website. */
export function initNativeAuth() {
  if (started || !Capacitor.isNativePlatform()) return;
  started = true;

  void App.addListener("appUrlOpen", ({ url }) => {
    void handleAuthCallback(url);
  });

  // App was killed while the browser was open and got relaunched by the link.
  App.getLaunchUrl()
    .then((launch) => {
      if (launch?.url) void handleAuthCallback(launch.url);
    })
    .catch(() => {});
}

/** Opens Google sign-in in a Custom Tab and returns as soon as it's up. */
export async function startNativeGoogleSignIn(forceAccountSelection: boolean) {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: NATIVE_REDIRECT,
      skipBrowserRedirect: true,
      ...(forceAccountSelection ? { queryParams: { prompt: "select_account" } } : {}),
    },
  });
  if (error) throw error;
  if (!data?.url) throw new Error("Couldn't start Google sign-in.");
  await Browser.open({ url: data.url });
}
