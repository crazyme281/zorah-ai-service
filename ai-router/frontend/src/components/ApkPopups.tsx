/**
 * Mounted once, app-wide, in App.tsx. Renders nothing on most renders —
 * useApkUpdate() only flips one of these on when the server-tracked
 * weekly cap actually allows it, so there's no local "have I shown this
 * already" state to duplicate or get out of sync here.
 */
import { IonIcon, IonSpinner } from "@ionic/react";
import { downloadOutline, closeOutline } from "ionicons/icons";
import { useApkUpdate } from "../hooks/useApkUpdate";

export function ApkPopups() {
  const {
    showUpdatePopup,
    showPromoPopup,
    dismissUpdatePopup,
    dismissPromoPopup,
    startUpdate,
    progress,
    error,
  } = useApkUpdate();

  if (!showUpdatePopup && !showPromoPopup) return null;

  const busy = progress !== null;

  return (
    <div className="apk-popup-backdrop" role="dialog" aria-modal="true">
      <div className="apk-popup">
        <button
          type="button"
          className="apk-popup__close"
          aria-label="Dismiss"
          onClick={showUpdatePopup ? dismissUpdatePopup : dismissPromoPopup}
          disabled={busy}
        >
          <IonIcon icon={closeOutline} />
        </button>

        <div className="apk-popup__icon">
          <IonIcon icon={downloadOutline} />
        </div>

        {showUpdatePopup ? (
          <>
            <h3>Please update</h3>
            <p>This app is outdated. Update to get the latest version of Zorah AI.</p>
          </>
        ) : (
          <>
            <h3>Get Zorah AI Mobile</h3>
            <p>Get the Zorah AI mobile app for a faster and better experience.</p>
          </>
        )}

        {progress && (
          <div className="apk-popup__progress">
            {progress.stage === "starting" && "Starting…"}
            {progress.stage === "downloading" &&
              (progress.percent != null ? `Downloading… ${progress.percent}%` : "Downloading…")}
            {progress.stage === "installing" && "Opening installer…"}
          </div>
        )}
        {error && <p className="apk-popup__error">{error}</p>}

        <div className="apk-popup__actions">
          <button
            type="button"
            className="apk-popup__btn apk-popup__btn--ghost"
            onClick={showUpdatePopup ? dismissUpdatePopup : dismissPromoPopup}
            disabled={busy}
          >
            Cancel
          </button>
          <button type="button" className="apk-popup__btn apk-popup__btn--gold" onClick={startUpdate} disabled={busy}>
            {busy ? <IonSpinner name="crescent" /> : showUpdatePopup ? "Update" : "Download"}
          </button>
        </div>
      </div>
    </div>
  );
}