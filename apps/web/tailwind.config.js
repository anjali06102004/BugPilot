/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#09090b",
        panel: "#121316",
        line: "#27272a",
        lime: "#84cc16",
        danger: "#f43f5e",
        muted: "#a1a1aa",
      },
      fontFamily: {
        sans: ["var(--font-geist)", "ui-sans-serif", "system-ui"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};