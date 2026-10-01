"use client";

import { motion, useReducedMotion } from "framer-motion";

const positions: Record<string, { x: string; y: string }> = {
  idle: { x: "8%", y: "12%" },
  flying: { x: "62%", y: "18%" },
  exploring: { x: "48%", y: "42%" },
  inspecting: { x: "22%", y: "58%" },
  suspicious: { x: "70%", y: "50%" },
  verifying: { x: "40%", y: "28%" },
  bug_found: { x: "55%", y: "36%" },
  success: { x: "12%", y: "20%" },
  error: { x: "80%", y: "16%" },
};

export function BugMascot({ state, hidden = false }: { state: string; hidden?: boolean }) {
  const reduce = useReducedMotion();
  if (hidden) return null;
  const pos = positions[state] || positions.idle;
  return (
    <motion.div
      aria-hidden="true"
      className="pointer-events-none absolute z-10 select-none text-2xl drop-shadow"
      animate={reduce ? { x: pos.x, y: pos.y } : { x: pos.x, y: pos.y, rotate: [0, 8, -6, 0] }}
      transition={reduce ? { duration: 0 } : { duration: 1.4, repeat: Infinity, repeatType: "reverse" }}
    >
      {state === "bug_found" ? "🐞⚠" : "🐞"}
    </motion.div>
  );
}
