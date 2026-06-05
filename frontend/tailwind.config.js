/** @type {import('tailwindcss').Config} */
// Design tokens map to CSS variables defined in src/index.css (Section 6.2).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "var(--color-primary)", light: "var(--color-primary-light)" },
        accent: "var(--color-accent)",
        success: "var(--color-success)",
        danger: "var(--color-danger)",
        warning: "var(--color-warning)",
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        border: "var(--color-border)",
        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
        "text-disabled": "var(--color-text-disabled)",
        "navy-50": "var(--color-navy-50)",
        "amber-50": "var(--color-amber-50)",
        "red-50": "var(--color-red-50)",
        "green-50": "var(--color-green-50)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      fontSize: {
        kpi: ["36px", { lineHeight: "1.1", fontWeight: "700" }],
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "slide-in": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
      },
      animation: {
        shimmer: "shimmer 1.5s infinite",
        "slide-in": "slide-in 200ms ease-in-out",
      },
    },
  },
  plugins: [],
};
