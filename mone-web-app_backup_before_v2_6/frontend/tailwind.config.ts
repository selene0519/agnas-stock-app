import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07111f",
        panel: "#0b1220",
        card: "#101b2d",
        line: "rgba(148, 163, 184, 0.18)",
        muted: "#94a3b8",
        text: "#e5e7eb",
        accent: "#38bdf8",
        good: "#22c55e",
        warn: "#f59e0b",
        danger: "#ef4444"
      },
      boxShadow: {
        soft: "0 18px 50px rgba(0,0,0,0.22)"
      }
    }
  },
  plugins: []
};

export default config;
