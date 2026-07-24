import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
      },
      colors: {
        // Cinema-dark neutral scale (2026-07-24): replaces Tailwind's default
        // blue-gray slate with a desaturated near-black scale, matching the
        // ui-ux-pro-max "Modern Dark (Cinema Mobile)" fintech/trading token set.
        // Every existing bg-slate-*/text-slate-*/border-slate-* class across the
        // app resolves through this override — no per-file className edits needed.
        slate: {
          50: "#f7f7f6",
          100: "#efeeec",
          200: "#d9d8d5",
          300: "#b3b1ac",
          400: "#8a8f98",
          500: "#6e7278",
          600: "#55585c",
          700: "#303236",
          800: "#1c1d20",
          900: "#101014",
          950: "#0a0a0c",
        },
        bg: {
          primary: "#0a0e1a",
          secondary: "#0f1628",
          card: "#131929",
          elevated: "#1a2236",
          border: "#1e2d45",
        },
        accent: {
          blue: "#3b82f6",
          cyan: "#06b6d4",
          green: "#10b981",
          red: "#ef4444",
          orange: "#f59e0b",
          purple: "#8b5cf6",
          gold: "#c9a961",
        },
        text: {
          primary: "#e2e8f0",
          secondary: "#94a3b8",
          muted: "#475569",
          inverse: "#0a0e1a",
        },
      },
      boxShadow: {
        card: "0 0 0 1px rgba(30,45,69,0.8), 0 4px 24px rgba(0,0,0,0.4)",
        glow: "0 0 20px rgba(59,130,246,0.15)",
        "glow-green": "0 0 20px rgba(16,185,129,0.15)",
        "glow-red": "0 0 20px rgba(239,68,68,0.15)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};
export default config;
