/**
 * Shared header across every section so the brand and status sit in the
 * same place regardless of where you are.
 */
import {
  IonHeader,
  IonToolbar,
  IonButtons,
  IonMenuButton,
  IonIcon,
  useIonRouter,
} from "@ionic/react";
import { personOutline, sparklesOutline, logOutOutline } from "ionicons/icons";
import { ZorahLogo } from "./ZorahLogo";
import { usePlan } from "../hooks/usePlan";
import { useAuth } from "../hooks/useAuth";

/**
 * `admin` renders the header for the admin-only shell: no hamburger
 * (there's no chat drawer to open there), no upgrade pill (admins
 * aren't on a paid-tier ladder), and the avatar button signs out
 * directly instead of linking to /settings, which doesn't exist for
 * admins — see App.tsx's admin branch for the routes this pairs with.
 */
export function TopBar({ online = true, admin = false }: { online?: boolean; admin?: boolean }) {
  const router = useIonRouter();
  const { plan } = usePlan();
  const { signOut } = useAuth();

  // FREE -> "Get Go", GO -> "Get Pro", PRO -> no button at all, matching
  // the reference design exactly (each tier's header only ever offers
  // the next step up, never skips one, never shows once there's nowhere
  // higher to go).
  const upgradeLabel =
    admin ? null : plan?.tier === "GO" ? "Get Pro" : plan?.tier === "PRO" ? null : "Get Go";

  return (
    <IonHeader className="ion-no-border">
      <IonToolbar className="zr-toolbar">
        <IonButtons slot="start">{!admin && <IonMenuButton menu="app-menu" />}</IonButtons>

        <div className="topbar-brand">
          <ZorahLogo size={28} />
          <span className="topbar-brand__name">Zorah</span>
        </div>

        <IonButtons slot="end">
          <span className="status-pill">
            <i className="status-pill__dot" />
            {online ? "Online" : "Offline"}
          </span>
          {upgradeLabel && (
            <button
              type="button"
              className="upgrade-pill"
              onClick={() => router.push("/upgrade", "none", "replace")}
            >
              <IonIcon icon={sparklesOutline} />
              {upgradeLabel}
            </button>
          )}
          <button
            type="button"
            className="avatar-btn"
            aria-label={admin ? "Sign out" : "Account settings"}
            onClick={() => (admin ? signOut() : router.push("/settings", "none", "replace"))}
          >
            <IonIcon icon={admin ? logOutOutline : personOutline} />
          </button>
        </IonButtons>
      </IonToolbar>
    </IonHeader>
  );
}