/**
 * The Zorah mark, rebuilt as inline SVG so it stays crisp at any size and
 * can inherit the gold gradient from a single place. `variant` controls
 * whether the wordmark rides along under the glyph.
 *
 * The gradient is defined per-instance with a unique id — multiple logos on
 * one page (rail + hero) would otherwise collide on `url(#zorah-gold)`.
 */
import { useId } from "react";

interface ZorahLogoProps {
  size?: number;
  variant?: "mark" | "full";
  className?: string;
  /** Renders the mark in a flat colour instead of gold — used in the rail. */
  flat?: string;
}

export function ZorahLogo({ size = 96, variant = "mark", className, flat }: ZorahLogoProps) {
  const uid = useId().replace(/:/g, "");
  const gold = `zorah-gold-${uid}`;
  const goldSoft = `zorah-gold-soft-${uid}`;
  const fill = flat ?? `url(#${gold})`;

  return (
    <div className={`zorah-logo zorah-logo--${variant} ${className ?? ""}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 200 200"
        role="img"
        aria-label="Zorah AI"
        className="zorah-logo__glyph"
      >
        <defs>
          <linearGradient id={gold} x1="12%" y1="0%" x2="88%" y2="100%">
            <stop offset="0%" stopColor="#FFF0BC" />
            <stop offset="18%" stopColor="#F2CB6B" />
            <stop offset="42%" stopColor="#D69C2E" />
            <stop offset="62%" stopColor="#A86E13" />
            <stop offset="82%" stopColor="#EFC85E" />
            <stop offset="100%" stopColor="#B07C1B" />
          </linearGradient>
          <linearGradient id={goldSoft} x1="0%" y1="10%" x2="100%" y2="90%">
            <stop offset="0%" stopColor="#F7DC92" />
            <stop offset="45%" stopColor="#C68E22" />
            <stop offset="100%" stopColor="#8A5A10" />
          </linearGradient>
        </defs>

        {/* Orbit swoosh, drawn behind the Z. The dash gap opens on the
            lower-right so the ring reads as passing behind the letter. */}
        <g transform="rotate(-21 100 106)">
          <ellipse
            cx="100"
            cy="106"
            rx="92"
            ry="41"
            fill="none"
            stroke={flat ?? `url(#${goldSoft})`}
            strokeWidth="13"
            strokeLinecap="round"
            strokeDasharray="300 148"
            strokeDashoffset="74"
          />
        </g>

        {/* The Z itself, slightly raked forward for motion. */}
        <g transform="skewX(-7) translate(11 0)">
          <polygon
            points="40,24 166,24 166,56 96,140 166,140 166,174 32,174 32,142 102,58 40,58"
            fill={fill}
          />
        </g>

        {/* Four-point sparkle at the shoulder of the Z. */}
        <path
          d="M171 18 C173.5 34 178 38.5 194 41 C178 43.5 173.5 48 171 64 C168.5 48 164 43.5 148 41 C164 38.5 168.5 34 171 18 Z"
          fill={fill}
        />
      </svg>

      {variant === "full" && (
        <div className="zorah-logo__word">
          <span className="zorah-logo__name">Zorah</span>
          <span className="zorah-logo__rule">
            <i />
            AI
            <i />
          </span>
        </div>
      )}
    </div>
  );
}
