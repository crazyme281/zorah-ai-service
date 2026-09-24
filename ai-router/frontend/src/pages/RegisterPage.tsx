import { useState } from "react";
import { IonPage, IonContent, IonInput, IonIcon } from "@ionic/react";
import {
  mailOutline,
  lockClosedOutline,
  eyeOutline,
  eyeOffOutline,
  arrowForwardOutline,
} from "ionicons/icons";
import { ZorahLogo } from "../components/ZorahLogo";

interface RegisterPageProps {
  onRegister: (email: string, password: string) => Promise<{ needsConfirmation: boolean }>;
  onGoogle: () => Promise<void>;
  onBackToLogin: () => void;
}

/** Same mark used on the login page — kept identical rather than
 * duplicated with drift, since it's the same Google account chooser
 * either way, just invoked with account selection forced. */
function GoogleMark() {
  return (
    <svg width="19" height="19" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M45.1 24.5c0-1.6-.1-2.8-.4-4H24v7.3h12.1c-.2 2-1.6 5-4.5 7l6.9 5.4c4.1-3.8 6.6-9.4 6.6-15.7z"
      />
      <path
        fill="#34A853"
        d="M24 46c6 0 11-2 14.5-5.4l-6.9-5.4c-1.9 1.3-4.4 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9.1l-7.1 5.5C7.9 41 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.5 28.3c-.5-1.4-.8-2.8-.8-4.3s.3-3 .7-4.3l-7.1-5.5C2.9 17.1 2 20.4 2 24s.9 6.9 2.4 9.8l7.1-5.5z"
      />
      <path
        fill="#EA4335"
        d="M24 10.2c4.1 0 6.9 1.8 8.5 3.3l6.2-6C34.9 4 30 2 24 2 15.4 2 7.9 7 4.4 14.2l7.1 5.5c1.8-5.3 6.7-9.5 12.5-9.5z"
      />
    </svg>
  );
}

export function RegisterPage({ onRegister, onGoogle, onBackToLogin }: RegisterPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set only when Supabase requires email confirmation before a session
  // exists — until then this screen stays up rather than bouncing the
  // user back to login on its own.
  const [confirmSent, setConfirmSent] = useState(false);

  async function handleRegister() {
    if (busy) return;
    if (!email.trim()) return setError("Enter your email.");
    if (password.length < 6) return setError("Password must be at least 6 characters.");
    if (password !== confirmPassword) return setError("Passwords don't match.");

    setBusy(true);
    setError(null);
    try {
      const { needsConfirmation } = await onRegister(email.trim(), password);
      if (needsConfirmation) {
        setConfirmSent(true);
      }
      // If no confirmation is needed, Supabase already has a live
      // session at this point — the app's own auth-state listener picks
      // it up and moves to the dashboard on its own, same as every
      // other sign-in path. Nothing to do here.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create that account.");
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogle() {
    setBusy(true);
    setError(null);
    try {
      await onGoogle();
    } catch {
      setError("Google sign-in isn't available right now.");
      setBusy(false);
    }
  }

  return (
    <IonPage>
      <IonContent className="auth-content" scrollY>
        <div className="auth-card">
          <div className="auth-card__mark">
            <ZorahLogo size={78} variant="full" />
          </div>

          {confirmSent ? (
            <>
              <h1>Check your inbox</h1>
              <p className="auth-card__lede">
                We sent a confirmation link to {email}. Click it to finish creating your account.
              </p>
              <button type="button" className="auth-submit" onClick={onBackToLogin}>
                Back to Sign In
              </button>
            </>
          ) : (
            <>
              <h1>Create your account</h1>
              <p className="auth-card__lede">Join Zorah AI — it&rsquo;s free to get started.</p>

              <div className="auth-field">
                <IonIcon icon={mailOutline} />
                <IonInput
                  type="email"
                  inputmode="email"
                  autocomplete="email"
                  placeholder="Email"
                  value={email}
                  onIonInput={(e) => setEmail(e.detail.value ?? "")}
                  aria-label="Email"
                />
              </div>

              <div className="auth-field">
                <IonIcon icon={lockClosedOutline} />
                <IonInput
                  type={showPassword ? "text" : "password"}
                  autocomplete="new-password"
                  placeholder="Password"
                  value={password}
                  onIonInput={(e) => setPassword(e.detail.value ?? "")}
                  aria-label="Password"
                />
                <button
                  type="button"
                  className="auth-field__toggle"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  <IonIcon icon={showPassword ? eyeOffOutline : eyeOutline} />
                </button>
              </div>

              <div className="auth-field">
                <IonIcon icon={lockClosedOutline} />
                <IonInput
                  type={showPassword ? "text" : "password"}
                  autocomplete="new-password"
                  placeholder="Confirm password"
                  value={confirmPassword}
                  onIonInput={(e) => setConfirmPassword(e.detail.value ?? "")}
                  onKeyDown={(e) => e.key === "Enter" && handleRegister()}
                  aria-label="Confirm password"
                />
              </div>

              <button type="button" className="auth-submit" disabled={busy} onClick={handleRegister}>
                {busy ? "Creating account…" : "Create Account"}
                {!busy && <IonIcon icon={arrowForwardOutline} />}
              </button>

              <div className="auth-or">or</div>

              <button type="button" className="auth-google" disabled={busy} onClick={handleGoogle}>
                <GoogleMark />
                Sign up with Google
              </button>

              {error && <p className="auth-note auth-note--error">{error}</p>}

              <p className="auth-foot">
                Already have an account?{" "}
                <button type="button" className="auth-link" onClick={onBackToLogin}>
                  Sign in
                </button>
              </p>
            </>
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}