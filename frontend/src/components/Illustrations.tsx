// Иллюстрации платформы: рисунки в коде, цвета — токены. Украшение: смысл всегда дублирует текст рядом.

const svg = { "aria-hidden": true, focusable: false } as const;

/** Обложка «Обзора»: понятия и связи между ними, в центре — результат, который мы проверяем. */
export function HeroArt() {
  const lines = [
    [210, 150, 92, 70], [210, 150, 332, 66], [210, 150, 356, 226], [210, 150, 78, 232], [210, 150, 214, 286],
    [92, 70, 164, 30], [332, 66, 268, 26], [356, 226, 396, 150], [78, 232, 26, 156], [214, 286, 306, 296],
    [214, 286, 128, 298], [92, 70, 26, 156], [332, 66, 396, 150],
  ];
  const dots = [[164, 30, 7], [268, 26, 9], [396, 150, 8], [26, 156, 9], [306, 296, 7], [128, 298, 8]];
  return (
    <svg {...svg} className="hero-art" viewBox="0 0 420 320">
      <circle cx="210" cy="150" r="146" className="art-glow" />
      <circle cx="210" cy="150" r="96" className="art-glow" />
      {lines.map(([x1, y1, x2, y2]) => (
        <line key={`${x1}-${y1}-${x2}-${y2}`} x1={x1} y1={y1} x2={x2} y2={y2} className="art-line" />
      ))}
      {dots.map(([cx, cy, r]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} className="art-dot" />
      ))}
      <g className="art-e">
        <circle cx="92" cy="70" r="30" />
        <path d="M80 80c0-16 10-24 25-25 1 15-7 26-20 26m-5 6c3-8 9-14 15-18" className="art-stroke" />
      </g>
      <g className="art-s">
        <circle cx="332" cy="66" r="30" />
        <circle cx="325" cy="58" r="6" className="art-fill" />
        <circle cx="341" cy="60" r="5" className="art-fill" />
        <path d="M314 80c1-9 6-13 11-13s10 4 11 13zm24-12c6 0 9 4 10 11h-10" className="art-fill" />
      </g>
      <g className="art-g">
        <circle cx="356" cy="226" r="30" />
        <path d="M341 220l15-9 15 9zm3 3h4v13h-4zm10 0h4v13h-4zm10 0h4v13h-4zm-22 15h28v3h-28z" className="art-fill" />
      </g>
      <g className="art-center">
        <circle cx="210" cy="150" r="52" />
        <path d="M184 170v-16m13 16v-26m13 26v-20m13 20v-34m13 34v-44" className="art-bars" />
        <path d="M184 142l13-10 13 6 13-16 13-10" className="art-trend" />
      </g>
      <circle cx="78" cy="232" r="20" className="art-node" />
      <path d="M69 225h18m-18 7h18m-18 7h11" className="art-stroke-soft" />
      <circle cx="214" cy="286" r="20" className="art-node" />
      <path d="M205 293v-7m6 7v-13m6 13v-10m6 10v-16" className="art-stroke-soft" />
    </svg>
  );
}

/** E: природа — холмы, солнце, дерево. */
export function EcoScene() {
  return (
    <svg {...svg} className="scene" viewBox="0 0 280 110" preserveAspectRatio="xMidYMid slice">
      <rect width="280" height="110" fill="var(--ok-bg)" />
      <circle cx="222" cy="32" r="17" fill="var(--warn-bg)" stroke="var(--warn)" strokeWidth="2" />
      <path d="M0 82c44-34 86-36 132-14s88 18 148-16v58H0z" fill="#9fd0b4" />
      <path d="M0 96c60-22 122-20 170-8s72 8 110-6v28H0z" fill="var(--accent)" />
      <path d="M72 76V50" stroke="var(--sidebar)" strokeWidth="3" strokeLinecap="round" />
      <path d="M72 18c15 11 19 25 0 38-19-13-15-27 0-38z" fill="var(--accent-hover)" />
      <path d="M116 80V60" stroke="var(--sidebar)" strokeWidth="3" strokeLinecap="round" />
      <path d="M116 36c11 8 14 18 0 28-14-10-11-20 0-28z" fill="var(--accent)" />
    </svg>
  );
}

/** S: люди рядом. */
export function PeopleScene() {
  const people: Array<[number, number, string]> = [
    [70, 1, "#4f7fb8"], [122, 1.2, "var(--info-text)"], [176, 1.05, "#6d97c9"], [224, 0.9, "#4f7fb8"],
  ];
  return (
    <svg {...svg} className="scene" viewBox="0 0 280 110" preserveAspectRatio="xMidYMid slice">
      <rect width="280" height="110" fill="var(--info-bg)" />
      <path d="M0 96h280v14H0z" fill="#b9cfea" />
      {people.map(([x, k, c]) => (
        <g key={x} transform={`translate(${x} 96) scale(${k})`} fill={c}>
          <circle cy="-52" r="12" />
          <path d="M-18 0c0-24 7-36 18-36S18-24 18 0z" />
        </g>
      ))}
      <path d="M148 24c-5-7-15-3-13 5 1 5 13 12 13 12s12-7 13-12c2-8-8-12-13-5z" fill="#c9553a" />
    </svg>
  );
}

/** G: здание с колоннами. */
export function GovScene() {
  return (
    <svg {...svg} className="scene" viewBox="0 0 280 110" preserveAspectRatio="xMidYMid slice">
      <rect width="280" height="110" fill="var(--warn-bg)" />
      <path d="M0 96h280v14H0z" fill="#efc99c" />
      <g fill="var(--warn-text)">
        <path d="M140 12l66 30H74z" />
        <rect x="80" y="46" width="120" height="6" />
        {[90, 114, 138, 162, 186].map((x) => (
          <rect key={x} x={x - 5} y="54" width="10" height="34" />
        ))}
        <rect x="74" y="88" width="132" height="8" />
      </g>
    </svg>
  );
}

/** Направление 1: вложения превращаются в результат. */
export function InvestArt() {
  return (
    <svg {...svg} className="study-art" viewBox="0 0 160 84">
      <g fill="var(--warn-bg)" stroke="var(--warn)" strokeWidth="2">
        <ellipse cx="30" cy="62" rx="18" ry="7" />
        <path d="M12 50v12c0 4 8 7 18 7s18-3 18-7V50" />
        <ellipse cx="30" cy="50" rx="18" ry="7" />
        <path d="M12 38v12c0 4 8 7 18 7s18-3 18-7V38" />
        <ellipse cx="30" cy="38" rx="18" ry="7" />
      </g>
      <path d="M58 44h26m-8-8l9 8-9 8" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <g fill="var(--accent)">
        <rect x="98" y="54" width="12" height="18" rx="2" opacity=".55" />
        <rect x="116" y="38" width="12" height="34" rx="2" opacity=".75" />
        <rect x="134" y="16" width="12" height="56" rx="2" />
      </g>
    </svg>
  );
}

/** Направление 2: агентства оценивают одну и ту же компанию по-разному. */
export function RatingsArt() {
  const rows: Array<[number, string, number]> = [[18, "var(--accent)", 118], [42, "var(--info-text)", 48], [66, "var(--warn)", 86]];
  return (
    <svg {...svg} className="study-art" viewBox="0 0 160 84">
      {rows.map(([y, c, x]) => (
        <g key={y}>
          <line x1="10" x2="150" y1={y} y2={y} stroke="var(--border)" strokeWidth="4" strokeLinecap="round" />
          <circle cx={x} cy={y} r="9" fill={c} />
        </g>
      ))}
    </svg>
  );
}

const ICONS = {
  article: "M6 3h9l4 4v14H6zM15 3v4h4M9 11h7M9 15h7",
  link: "M5 7a2.5 2.5 0 1 0 0-.01zM19 5a2.5 2.5 0 1 0 0-.01zM19 19a2.5 2.5 0 1 0 0-.01zM7.3 7.5l9.4-1.8M6.5 9l10.8 8",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z",
  chart: "M4 20h16M7 20v-6M12 20V8M17 20v-9",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  edit: "M4 20l1-4L16 5l3 3L8 19zM13.5 7.5l3 3",
  quote: "M9 7c-3 1-4 3-4 6v3h5v-5H7.5M19 7c-3 1-4 3-4 6v3h5v-5h-2.5",
  repeat: "M4 10a8 8 0 0 1 14-4l2 2M20 4v4h-4M20 14a8 8 0 0 1-14 4l-2-2M4 20v-4h4",
  flag: "M6 21V4M6 4h11l-2 4 2 4H6",
  scale: "M12 4v16M7 20h10M5 8h14M5 8l-3 7c1 2 5 2 6 0zM19 8l-3 7c1 2 5 2 6 0z",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 20c0-4 2.500-6 6-6s6 2 6 6M16 11a3 3 0 1 0-1-5.800M17 14c2.500.4 4 2.400 4 6",
} as const;

export function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg {...svg} className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={ICONS[name]} />
    </svg>
  );
}
