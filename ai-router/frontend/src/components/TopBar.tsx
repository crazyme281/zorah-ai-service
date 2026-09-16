/**
 * Shared header across every section so the brand and status sit in the same
 * place regardless of where you are.
 */
import {
  IonHeader,
  IonToolbar,
  IonButtons,
  IonMenuButton,
  IonIcon,
  useIonRouter,
} from "@ionic/react";
import { personOutline } from "ionicons/icons";
import { ZorahLogo } from "./ZorahLogo";

export function TopBar({ online = true }: { online?: boolean }) {
  const router = useIonRouter();

  return (
    <IonHeader className="ion-no-border">
      <IonToolbar className="zr-toolbar">
        <IonButtons slot="start">
          <IonMenuButton menu="app-menu" />
        </IonButtons>

        <div className="topbar-brand">
          <ZorahLogo size={28} />
          <span className="topbar-brand__name">Zorah</span>
        </div>

        <IonButtons slot="end">
          <span className="status-pill">
            <i className="status-pill__dot" />
            {online ? "Online" : "Offline"}
          </span>
          <button
            type="button"
            className="avatar-btn"
            aria-label="Account settings"
            onClick={() => router.push("/settings", "none", "replace")}
          >
            <IonIcon icon={personOutline} />
          </button>
        </IonButtons>
      </IonToolbar>
    </IonHeader>
  );
}
