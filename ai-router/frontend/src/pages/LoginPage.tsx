import { useState } from "react";
import { IonPage, IonContent, IonInput, IonButton, IonText } from "@ionic/react";

interface LoginPageProps {
  onSubmitEmail: (email: string) => Promise<void>;
}

export function LoginPage({ onSubmitEmail }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function handleSubmit() {
    if (!email.trim()) return;
    setStatus("sending");
    try {
      await onSubmitEmail(email);
      setStatus("sent");
    } catch {
      setStatus("error");
    }
  }

  return (
    <IonPage>
      <IonContent className="auth-content ion-padding">
        <div className="auth-card">
          <div className="auth-brand">Lite</div>
          {status === "sent" ? (
            <IonText color="medium">
              <p>Check your email for a sign-in link.</p>
            </IonText>
          ) : (
            <>
              <IonInput
                type="email"
                label="Email"
                labelPlacement="stacked"
                placeholder="you@example.com"
                value={email}
                onIonInput={(e) => setEmail(e.detail.value ?? "")}
                className="auth-input"
              />
              <IonButton
                expand="block"
                color="primary"
                className="ion-margin-top"
                disabled={status === "sending"}
                onClick={handleSubmit}
              >
                {status === "sending" ? "Sending…" : "Send sign-in link"}
              </IonButton>
              {status === "error" && (
                <IonText color="danger">
                  <p>Something went wrong. Try again.</p>
                </IonText>
              )}
            </>
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}
