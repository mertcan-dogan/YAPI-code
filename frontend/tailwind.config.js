/** @type {import('tailwindcss').Config} */
// Design tokens map to CSS variables defined in src/index.css (Section 6.2).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "var(--color-primary)", light: "var(--color-primary-light)" },
        brand: { DEFAULT: "var(--color-brand)", light: "var(--color-brand-light)", "2": "var(--color-brand-2)" },
        accent: "var(--color-accent)",
        success: "var(--color-success)",
        danger: "var(--color-danger)",
        warning: "var(--color-warning)",
        bg: "var(--color-bg)",
        surface: { DEFAULT: "var(--color-surface)", soft: "var(--color-surface-soft)", hover: "var(--color-surface-hover)" },
        border: { DEFAULT: "var(--color-border)", strong: "var(--color-border-strong)" },
        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
        "text-muted": "var(--color-text-muted)",
        "text-faint": "var(--color-text-faint)",
        "text-disabled": "var(--color-text-disabled)",
        // CR-029: full BuildFlow accent set (+ soft tints for icon badges/pills).
        teal: { DEFAULT: "var(--color-teal)", soft: "var(--color-teal-soft)" },
        purple: { DEFAULT: "var(--color-purple)", soft: "var(--color-purple-soft)" },
        orange: { DEFAULT: "var(--color-orange)", soft: "var(--color-orange-soft)" },
        "blue-soft": "var(--color-blue-soft)",
        "blue-border": "var(--color-blue-border)",
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
        // CR-028 type scale (data-dense): page/section titles, body, caption,
        // overline. .tabular handles figure alignment.
        kpi: ["30px", { lineHeight: "1.1", fontWeight: "700" }],
        stat: ["22px", { lineHeight: "1.15", fontWeight: "700" }],
        section: ["15px", { lineHeight: "1.3", fontWeight: "600" }],
        caption: ["12px", { lineHeight: "1.4" }],
        overline: ["11px", { lineHeight: "1.2", letterSpacing: "0.06em", fontWeight: "600" }],
      },
      borderRadius: {
        card: "var(--radius-card)",
        control: "var(--radius)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        lg: "var(--shadow-lg)",
        pop: "var(--shadow-pop)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "slide-in": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        shimmer: "shimmer 1.5s infinite",
        "slide-in": "slide-in 200ms ease-in-out",
        "fade-in": "fade-in 120ms ease-out",
      },
    },
  },
  plugins: [],
};
