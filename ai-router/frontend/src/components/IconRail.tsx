/**
 * The persistent left rail. Hidden below 620px, where the drawer carries the
 * same four destinations instead (see AppMenu).
 */
import { useIonRouter } from "@ionic/react";
import { useLocation } from "react-router-dom";
import { IonIcon } from "@ionic/react";
import {
  chatbubbleEllipsesOutline,
  imagesOutline,
  timeOutline,
  settingsOutline,
  codeSlashOutline,
} from "ionicons/icons";

export const RAIL_ITEMS = [
  { label: "Chat", icon: chatbubbleEllipsesOutline, path: "/" },
  { label: "Images", icon: imagesOutline, path: "/images" },
  { label: "Code", icon: codeSlashOutline, path: "/code" },
  { label: "History", icon: timeOutline, path: "/history" },
  { label: "Settings", icon: settingsOutline, path: "/settings" },
] as const;

/** `/` and `/chat/:id` are both the Chat destination. */
export function isRailActive(path: string, pathname: string) {
  if (path === "/") return pathname === "/" || pathname.startsWith("/chat");
  return pathname.startsWith(path);
}

export function IconRail() {
  const router = useIonRouter();
  const { pathname } = useLocation();

  return (
    <nav className="rail" aria-label="Sections">
      {RAIL_ITEMS.map((item) => {
        const active = isRailActive(item.path, pathname);
        return (
          <button
            key={item.path}
            type="button"
            className={`rail__item ${active ? "rail__item--active" : ""}`}
            aria-current={active ? "page" : undefined}
            onClick={() => router.push(item.path, "none", "replace")}
          >
            <IonIcon icon={item.icon} />
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}