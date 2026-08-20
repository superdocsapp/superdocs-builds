"use client";

// BackgroundScene.tsx -- the animated castle/petals/stars scene, rendered
// once in layout.tsx so it shows behind EVERY route, not just the
// homepage. Previously this lived inline in app/page.tsx, which is why it
// only ever appeared on "/" -- every other page (campaigns/[id],
// documents/[id]) rendered straight into .shell with no scene behind it
// at all.
//
// Fixed positions/timings (not Math.random()) so server and client render
// identical markup -- randomizing per-render would mismatch on hydration.

const PETALS: { left: number; size: number; delay: number; duration: number; color: "gold" | "blossom" }[] = [
  { left: 3, size: 6, delay: 0, duration: 11.5, color: "blossom" },
  { left: 10, size: 4, delay: 1.8, duration: 9.2, color: "gold" },
  { left: 18, size: 7, delay: 4.1, duration: 12.8, color: "blossom" },
  { left: 26, size: 5, delay: 0.8, duration: 10.4, color: "gold" },
  { left: 34, size: 4, delay: 3.0, duration: 11.1, color: "blossom" },
  { left: 42, size: 6, delay: 5.6, duration: 9.6, color: "gold" },
  { left: 50, size: 5, delay: 1.4, duration: 13.2, color: "blossom" },
  { left: 58, size: 7, delay: 4.7, duration: 10.8, color: "gold" },
  { left: 66, size: 4, delay: 0.3, duration: 11.9, color: "blossom" },
  { left: 74, size: 5, delay: 3.6, duration: 9.9, color: "gold" },
  { left: 82, size: 6, delay: 6.2, duration: 12.3, color: "blossom" },
  { left: 90, size: 4, delay: 2.1, duration: 10.6, color: "gold" },
  { left: 96, size: 5, delay: 5.0, duration: 11.4, color: "blossom" },
  { left: 55, size: 4, delay: 7.3, duration: 9.4, color: "gold" },
];

const BIRDS = [
  { y: 34, delay: 0, duration: 16 },
  { y: 52, delay: 5.5, duration: 19 },
  { y: 22, delay: 11, duration: 17.5 },
];

const STARS = [
  { x: 40, y: 24, r: 1.4, delay: 0.4 },
  { x: 90, y: 40, r: 1, delay: 2.1 },
  { x: 150, y: 20, r: 1.6, delay: 1.2 },
  { x: 220, y: 55, r: 1, delay: 3.4 },
  { x: 270, y: 30, r: 1.3, delay: 0.9 },
  { x: 330, y: 60, r: 1, delay: 2.8 },
  { x: 380, y: 18, r: 1.5, delay: 1.7 },
  { x: 460, y: 45, r: 1, delay: 4.1 },
  { x: 60, y: 70, r: 1, delay: 3.0 },
  { x: 200, y: 85, r: 0.9, delay: 1.5 },
];

export default function BackgroundScene() {
  return (
    <>
      {/* Fixed to the viewport (not any single page's hero box) so it
          covers the whole window on every route as you scroll -- the
          sticky header sits at a higher z-index with its own opaque
          background, so it naturally covers this rather than needing any
          special-case exclusion. */}
      <svg className="page-scene" viewBox="0 0 800 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="riverGlow" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.12" />
            <stop offset="50%" stopColor="var(--gold)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.12" />
          </linearGradient>
        </defs>

        {STARS.map((s, i) => (
          <circle key={i} className="star" cx={s.x} cy={s.y} r={s.r} style={{ animationDelay: `${s.delay}s` }} />
        ))}

        {/* back mountain range */}
        <polygon
          className="mountain-back"
          points="0,190 40,150 90,175 140,120 190,160 240,110 300,150 360,100 420,140 480,105 540,145 600,110 660,160 720,130 800,170 800,300 0,300"
        />
        {/* front mountain range */}
        <polygon
          className="mountain-front"
          points="0,225 60,175 120,205 170,155 230,195 290,160 350,200 410,165 470,205 540,170 600,210 660,180 720,215 800,195 800,300 0,300"
        />

        {/* distant castle silhouette */}
        <g className="castle">
          <rect x="528" y="222" width="176" height="56" />
          <rect x="518" y="162" width="30" height="80" />
          <polygon points="518,162 533,132 548,162" />
          <rect x="593" y="122" width="34" height="118" />
          <polygon points="593,122 610,86 627,122" />
          <rect x="654" y="172" width="28" height="68" />
          <polygon points="654,172 668,142 682,172" />
          <circle className="castle-window" cx="533" cy="195" r="2.1" style={{ animationDelay: "0.3s" }} />
          <circle className="castle-window" cx="610" cy="150" r="2.3" style={{ animationDelay: "1.6s" }} />
          <circle className="castle-window" cx="610" cy="185" r="2.1" style={{ animationDelay: "2.7s" }} />
          <circle className="castle-window" cx="668" cy="195" r="2" style={{ animationDelay: "0.9s" }} />
        </g>

        {/* river with a slow shimmering highlight */}
        <path className="river" d="M230,300 C280,250 340,260 400,280 C460,300 520,255 580,300 Z" fill="url(#riverGlow)" />
        <ellipse className="water-shimmer" cx="400" cy="280" rx="60" ry="8" />

        {BIRDS.map((b, i) => (
          <g key={i} transform={`translate(0, ${b.y})`}>
            <g className="bird" style={{ animationDelay: `${b.delay}s`, animationDuration: `${b.duration}s` }}>
              <path d="M0,4 Q6,-5 12,4 Q6,0.5 0,4 M12,4 Q18,-5 24,4 Q18,0.5 12,4" />
            </g>
          </g>
        ))}
      </svg>

      <div className="page-petals" aria-hidden="true">
        {PETALS.map((petal, i) => (
          <span
            key={i}
            className={`petal petal-${petal.color}`}
            style={{
              left: `${petal.left}%`,
              width: petal.size,
              height: petal.size,
              animationDelay: `${petal.delay}s`,
              animationDuration: `${petal.duration}s`,
            }}
          />
        ))}
      </div>
    </>
  );
}
