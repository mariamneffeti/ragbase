import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg:        "var(--bg)",
        surface:   "var(--surface)",
        "surface-2": "var(--surface-2)",
        border:    "var(--border)",
        text:      "var(--text)",
        "text-2":  "var(--text-2)",
        accent:    "var(--accent)",
        "accent-2":"var(--accent-2)",
        danger:    "var(--danger)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["DM Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;