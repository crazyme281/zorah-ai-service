/**
 * The actual missing piece behind "admin login doesn't work" — the role
 * check was already correct server-side, there was just nowhere for an
 * admin to land. This is that landing point.
 *
 * Deliberately scoped to what's real right now: an account summary and
 * a link into APK management (the one admin tool that actually exists).
 * Not fabricating usage/queue widgets with no real data behind them —
 * add cards here as each admin capability actually ships.
 */
import { IonPage, IonContent, IonIcon } from "@ionic/react";
import { useIonRouter } from "@ionic/react";
import { shieldCheckmarkOutline, cubeOutline, chevronForwardOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { useAuth } from "../hooks/useAuth";

export function AdminDashboardPage() {
  const router = useIonRouter();
  const { user } = useAuth();

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="admin-dash">
          <div className="admin-dash__header">
            <IonIcon icon={shieldCheckmarkOutline} />
            <div>
              <h2>Admin Dashboard</h2>
              <p>{user?.email}</p>
            </div>
          </div>

          <div className="admin-dash__cards">
            <button
              type="button"
              className="admin-dash__card"
              onClick={() => router.push("/admin/apk", "none", "replace")}
            >
              <IonIcon icon={cubeOutline} className="admin-dash__card-icon" />
              <div className="admin-dash__card-body">
                <b>APK Release</b>
                <span>Upload, delete, and manage the current Android build</span>
              </div>
              <IonIcon icon={chevronForwardOutline} className="admin-dash__card-chevron" />
            </button>
          </div>
        </div>
      </IonContent>
    </IonPage>
  );
}