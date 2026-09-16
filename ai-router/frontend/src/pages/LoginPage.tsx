import { useState } from "react";
import { IonPage, IonContent, IonInput, IonIcon } from "@ionic/react";
import {
  mailOutline,
  lockClosedOutline,
  eyeOutline,
  eyeOffOutline,
  checkmarkOutline,
  arrowForwardOutline,
} from "ionicons/icons";
import { ZorahLogo } from "../components/ZorahLogo";

interface LoginPageProps {
  onSubmitPassword: (email: string, password: string, remember: boolean) => Promise<void>;
  onSubmitMagicLink: (email: string) => Promise<void>;
  onGoogle: () => Promise<void>;
}

/** Google's mark, inlined so the button works offline and in the webview. */
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

export function LoginPage({ onSubmitPassword, onSubmitMagicLink, onGoogle }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleLogin() {
    if (busy) return;
    if (!email.trim()) return setError("Enter your email or username.");
    if (!password) return setError("Enter your password.");
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await onSubmitPassword(email.trim(), password, remember);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That email and password didn't match.");
    } finally {
      setBusy(false);
    }
  }

  // Doubles as the "forgot password" path: Supabase emails a one-time link
  // that signs the user straight in.
  async function handleMagicLink() {
    if (!email.trim()) return setError("Enter your email first, then tap this again.");
    setBusy(true);
    setError(null);
    try {
      await onSubmitMagicLink(email.trim());
      setNotice("Sign-in link sent. Check your inbox.");
    } catch {
      setError("Couldn't send the link. Try again in a moment.");
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

          <h1>Welcome back</h1>
          <p className="auth-card__lede">Log in to continue to your Zorah AI account.</p>

          <div className="auth-field">
            <IonIcon icon={mailOutline} />
            <IonInput
              type="email"
              inputmode="email"
              autocomplete="username"
              placeholder="Email or username"
              value={email}
              onIonInput={(e) => setEmail(e.detail.value ?? "")}
              aria-label="Email or username"
            />
          </div>

          <div className="auth-field">
            <IonIcon icon={lockClosedOutline} />
            <IonInput
              type={showPassword ? "text" : "password"}
              autocomplete="current-password"
              placeholder="Password"
              value={password}
              onIonInput={(e) => setPassword(e.detail.value ?? "")}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
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

          <div className="auth-row">
            <label className="auth-check">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              <span className="auth-check__box">
                <IonIcon icon={checkmarkOutline} />
              </span>
              Remember me
            </label>
            <button type="button" className="auth-link" onClick={handleMagicLink}>
              Forgot password?
            </button>
          </div>

          <button type="button" className="auth-submit" disabled={busy} onClick={handleLogin}>
            {busy ? "Logging in…" : "Log in"}
            {!busy && <IonIcon icon={arrowForwardOutline} />}
          </button>

          <div className="auth-or">or</div>

          <button type="button" className="auth-google" disabled={busy} onClick={handleGoogle}>
            <GoogleMark />
            Continue with Google
          </button>

          {error && <p className="auth-note auth-note--error">{error}</p>}
          {notice && <p className="auth-note auth-note--ok">{notice}</p>}

          <p className="auth-foot">
            Don&rsquo;t have an account?{" "}
            <a className="auth-link" href="mailto:admin@zorah.ai">
              Contact admin
            </a>
          </p>
        </div>
      </IonContent>
    </IonPage>
  );
}
