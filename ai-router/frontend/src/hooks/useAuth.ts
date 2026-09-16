import { useEffect, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";

const REMEMBER_KEY = "zorah:remember";

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

  /** Magic link — also backs the "Forgot password?" action on the login page. */
  async function signInWithEmail(email: string) {
    const { error } = await supabase.auth.signInWithOtp({ email });
    if (error) throw error;
  }

  async function signInWithGoogle() {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
    if (error) throw error;
  }

  async function signOut() {
    localStorage.removeItem(REMEMBER_KEY);
    await supabase.auth.signOut();
  }

  return {
    user,
    loading,
    signInWithPassword,
    signInWithEmail,
    signInWithGoogle,
    signOut,
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
