import { useEffect, useState } from "react";

// CR-029-C §6: the AI briefing hero's animated wave — five layered paths drifting
// in alternating directions for a seamless loop (paths/durations replicated from
// BuildFlow-Dashboard-Mockup.html). Respects prefers-reduced-motion (pauses).
const LAYERS = [
  { fill: "#DBEAFE", opacity: 0.55, d: "M-300,72 C-225,52 -75,52 0,72 C75,52 225,52 300,72 C375,52 525,52 600,72 C675,52 825,52 900,72 C975,52 1125,52 1200,72 L1200,200 L-300,200 Z", from: "0 0", to: "-300 0", dur: "24s" },
  { fill: "#93C5FD", opacity: 0.5, d: "M-300,96 C-225,72 -75,72 0,96 C75,72 225,72 300,96 C375,72 525,72 600,96 C675,72 825,72 900,96 C975,72 1125,72 1200,96 L1200,200 L-300,200 Z", from: "-300 0", to: "0 0", dur: "19s" },
  { fill: "#5EEAD4", opacity: 0.34, d: "M-300,120 C-225,98 -75,98 0,120 C75,98 225,98 300,120 C375,98 525,98 600,120 C675,98 825,98 900,120 C975,98 1125,98 1200,120 L1200,200 L-300,200 Z", from: "0 0", to: "-300 0", dur: "29s" },
  { fill: "#3B82F6", opacity: 0.4, d: "M-300,142 C-225,120 -75,120 0,142 C75,120 225,120 300,142 C375,120 525,120 600,142 C675,120 825,120 900,142 C975,120 1125,120 1200,142 L1200,200 L-300,200 Z", from: "-300 0", to: "0 0", dur: "17s" },
  { fill: "#2563EB", opacity: 0.4, d: "M-300,166 C-225,146 -75,146 0,166 C75,146 225,146 300,166 C375,146 525,146 600,166 C675,146 825,146 900,166 C975,146 1125,146 1200,166 L1200,200 L-300,200 Z", from: "0 0", to: "-300 0", dur: "21s" },
];

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

export function WaveBackground({ className }: { className?: string }) {
  const reduced = usePrefersReducedMotion();
  return (
    <svg className={className} viewBox="0 0 600 200" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="yapi-wave-fade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#FBFDFF" stopOpacity="0.92" />
          <stop offset="0.45" stopColor="#FBFDFF" stopOpacity="0" />
        </linearGradient>
      </defs>
      {LAYERS.map((l, i) => (
        <path key={i} fill={l.fill} opacity={l.opacity} d={l.d}>
          {!reduced && (
            <animateTransform
              attributeName="transform"
              type="translate"
              from={l.from}
              to={l.to}
              dur={l.dur}
              repeatCount="indefinite"
            />
          )}
        </path>
      ))}
      <rect x="0" y="0" width="600" height="200" fill="url(#yapi-wave-fade)" />
    </svg>
  );
}
