"use client";

import { motion, useReducedMotion } from "framer-motion";

export type MascotState =
  | "idle"
  | "waking"
  | "flying"
  | "exploring"
  | "inspecting"
  | "suspicious"
  | "verifying"
  | "bug_found"
  | "success"
  | "error"
  | "paused";

const ACCENT = "#84cc16";
const SHELL = "#1c1f24";
const SHELL_LIGHT = "#2b3038";

const stateConfig: Record<
  MascotState,
  { label: string; glow: number; beam: boolean; wings: number; tilt: number }
> = {
  idle: { label: "Idle", glow: 0.35, beam: false, wings: 0.35, tilt: -4 },
  waking: { label: "Waking up", glow: 0.6, beam: false, wings: 0.6, tilt: 0 },
  flying: { label: "Flying", glow: 0.5, beam: false, wings: 1, tilt: -10 },
  exploring: { label: "Exploring", glow: 0.7, beam: false, wings: 0.8, tilt: 6 },
  inspecting: { label: "Inspecting", glow: 1, beam: true, wings: 0.45, tilt: 0 },
  suspicious: { label: "Suspicious", glow: 0.9, beam: true, wings: 0.6, tilt: -8 },
  verifying: { label: "Verifying", glow: 1, beam: false, wings: 0.3, tilt: 4 },
  bug_found: { label: "Bug found", glow: 1.3, beam: true, wings: 1, tilt: -14 },
  success: { label: "Complete", glow: 1.1, beam: false, wings: 1, tilt: 0 },
  error: { label: "Failed", glow: 0.6, beam: false, wings: 0.2, tilt: 12 },
  paused: { label: "Paused", glow: 0.25, beam: false, wings: 0.15, tilt: 0 },
};

export function Mascot({
  state = "idle",
  size = 96,
  showLabel = false,
  className = "",
}: {
  state?: MascotState | string;
  size?: number;
  showLabel?: boolean;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const key = (state in stateConfig ? state : "idle") as MascotState;
  const cfg = stateConfig[key];

  return (
    <div className={`flex flex-col items-center gap-2 ${className}`}>
      <motion.div
        style={{ width: size, height: size }}
        aria-hidden="true"
        animate={
          reduce
            ? { rotate: 0, y: 0 }
            : {
                rotate: cfg.tilt,
                y: [0, -4, 0],
              }
        }
        transition={
          reduce
            ? { duration: 0 }
            : { rotate: { duration: 0.5 }, y: { duration: 2.4, repeat: Infinity, ease: "easeInOut" } }
        }
      >
        <svg viewBox="0 0 120 120" width="100%" height="100%" role="img" aria-label={`BugPilot ${cfg.label}`}>
          <defs>
            <radialGradient id="bp-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={ACCENT} stopOpacity={cfg.glow} />
              <stop offset="70%" stopColor={ACCENT} stopOpacity={0.08} />
              <stop offset="100%" stopColor={ACCENT} stopOpacity="0" />
            </radialGradient>
            <linearGradient id="bp-shell" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={SHELL_LIGHT} />
              <stop offset="100%" stopColor={SHELL} />
            </linearGradient>
            <linearGradient id="bp-visor" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#eaffb0" />
              <stop offset="100%" stopColor={ACCENT} />
            </linearGradient>
          </defs>

          <circle cx="60" cy="62" r="52" fill="url(#bp-glow)" />

          {/* scan beam */}
          <motion.path
            d="M60 66 L20 112 L100 112 Z"
            fill={ACCENT}
            initial={false}
            animate={cfg.beam ? { opacity: [0.05, 0.22, 0.05] } : { opacity: 0 }}
            transition={cfg.beam ? { duration: 1.8, repeat: Infinity } : { duration: 0.2 }}
          />

          {/* wings */}
          <motion.g
            style={{ originX: "60px", originY: "56px" }}
            initial={{ opacity: 0.35 + cfg.wings * 0.4 }}
            animate={reduce ? { scaleY: 1, opacity: 0.35 + cfg.wings * 0.4 } : { scaleY: [0.75, 1, 0.75], opacity: 0.35 + cfg.wings * 0.4 }}
            transition={reduce ? { duration: 0 } : { duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
          >
            <ellipse cx="33" cy="48" rx="20" ry="13" transform="rotate(-28 33 48)" fill="#d7f5a7" opacity="0.22" />
            <ellipse cx="87" cy="48" rx="20" ry="13" transform="rotate(28 87 48)" fill="#d7f5a7" opacity="0.22" />
          </motion.g>

          {/* legs */}
          <g stroke={SHELL_LIGHT} strokeWidth="3" strokeLinecap="round">
            <path d="M40 78 L24 88" />
            <path d="M44 88 L30 100" />
            <path d="M80 78 L96 88" />
            <path d="M76 88 L90 100" />
            <path d="M52 96 L46 110" />
            <path d="M68 96 L74 110" />
          </g>

          {/* shell */}
          <ellipse cx="60" cy="72" rx="30" ry="26" fill="url(#bp-shell)" stroke="#3f4650" strokeWidth="2" />
          <path d="M60 47 V98" stroke="#3f4650" strokeWidth="2" opacity="0.7" />
          <ellipse cx="60" cy="72" rx="30" ry="26" fill="none" stroke={ACCENT} strokeWidth="1.5" opacity="0.35" />

          {/* head */}
          <circle cx="60" cy="42" r="19" fill="url(#bp-shell)" stroke="#3f4650" strokeWidth="2" />

          {/* visor / eyes */}
          <rect x="47" y="35" width="26" height="13" rx="6.5" fill="#0b0c0e" stroke="#3f4650" strokeWidth="1.5" />
          <motion.g
            animate={
              reduce
                ? {}
                : key === "verifying"
                  ? { opacity: [1, 0.5, 1] }
                  : key === "bug_found"
                    ? { scale: [1, 1.15, 1] }
                    : { opacity: 1 }
            }
            transition={{ duration: 1.2, repeat: Infinity }}
          >
            <circle cx="55" cy="41.5" r="3.4" fill="url(#bp-visor)" />
            <circle cx="65" cy="41.5" r="3.4" fill="url(#bp-visor)" />
          </motion.g>

          {/* antennae */}
          <g stroke={SHELL_LIGHT} strokeWidth="2.5" strokeLinecap="round" fill="none">
            <path d="M52 26 Q46 16 40 13" />
            <path d="M68 26 Q74 16 80 13" />
          </g>
          <motion.g
            animate={reduce ? {} : { opacity: [0.5, 1, 0.5] }}
            transition={{ duration: 1.6, repeat: Infinity }}
          >
            <circle cx="40" cy="12" r="3.4" fill={ACCENT} />
            <circle cx="80" cy="12" r="3.4" fill={ACCENT} />
          </motion.g>

          {/* magnifier during verification */}
          {key === "verifying" && (
            <g>
              <circle cx="92" cy="86" r="10" fill="none" stroke={ACCENT} strokeWidth="3" />
              <path d="M99 93 L108 102" stroke={ACCENT} strokeWidth="3.5" strokeLinecap="round" />
            </g>
          )}

          {/* spark on discovery */}
          {key === "bug_found" && (
            <motion.g
              animate={reduce ? {} : { scale: [0.8, 1.15, 0.8], opacity: [0.6, 1, 0.6] }}
              transition={{ duration: 1.1, repeat: Infinity }}
            >
              <path d="M18 30 l4 8 8 4 -8 4 -4 8 -4 -8 -8 -4 8 -4 z" fill={ACCENT} />
            </motion.g>
          )}
        </svg>
      </motion.div>
      {showLabel && (
        <span className="text-[11px] uppercase tracking-[0.16em] text-muted">{cfg.label}</span>
      )}
    </div>
  );
}