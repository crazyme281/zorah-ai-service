/**
 * Shown while the Supabase session is still resolving, and for a short
 * minimum hold after that so the brand doesn't flash past. `exiting` fades
 * it out rather than cutting, which is the one bit of non-user-triggered
 * motion in the app.
 */
import { ZorahLogo } from "./ZorahLogo";

export function SplashScreen({ exiting = false }: { exiting?: boolean }) {
  return (
    <div className={`splash ${exiting ? "splash--exiting" : ""}`} aria-hidden={exiting}>
      <div className="splash__glow" />
      <div className="splash__body">
        <ZorahLogo size={132} variant="full" />
        <p className="splash__tagline">
          Smarter ideas.
          <span>Greater possibilities.</span>
        </p>
      </div>
      <div className="splash__sweep" />
    </div>
  );
}
