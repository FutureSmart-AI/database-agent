import type { CSSProperties, ReactNode } from "react";

/**
 * Icon set for the app — the glyphs from the product's design artifact, drawn
 * inline rather than pulled from an icon library.
 *
 * Every path below is the artifact's own sprite: one 20×20 grid, `fill: none`,
 * `currentColor` stroke, so weight and geometry are identical to the design and
 * a glyph takes its colour from whatever it sits in. A handful of names the
 * screens need are not in the sprite (chevrons, `info`, `percent`, `eyeOff`,
 * `plug`, `layers`, the circled `x` and `plus`); those are drawn to the same
 * grid and the same stroke language. Names that the artifact answers with an
 * existing glyph reuse it deliberately — `chart` and `clipboard` are the
 * artifact's table and document, `bot` is its database mark, which is what it
 * puts on an assistant turn.
 *
 * Call sites name icons by role rather than reaching for a glyph directly,
 * which keeps swapping any single one to a line in here.
 */
const ICONS = {
  db: (
    <>
      <ellipse cx="10" cy="5" rx="6.4" ry="2.6" />
      <path d="M3.6 5v10c0 1.4 2.9 2.6 6.4 2.6s6.4-1.2 6.4-2.6V5" />
      <path d="M3.6 10c0 1.4 2.9 2.6 6.4 2.6s6.4-1.2 6.4-2.6" />
    </>
  ),
  home: (
    <>
      <path d="M3 8.6L10 3l7 5.6V17H3z" />
      <path d="M8 17v-5h4v5" />
    </>
  ),
  chat: (
    <>
      <path d="M3.4 4.4h13.2v9H9l-4 3.4V13.4H3.4z" />
      <path d="M7 8.4h6M7 11h4" />
    </>
  ),
  share: (
    <>
      <circle cx="5" cy="10" r="2.3" />
      <circle cx="15" cy="5.4" r="2.3" />
      <circle cx="15" cy="14.6" r="2.3" />
      <path d="M7.1 8.9l5.8-2.5M7.1 11.1l5.8 2.5" />
    </>
  ),
  cog: (
    <>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 2.4v2.2M10 15.4v2.2M2.4 10h2.2M15.4 10h2.2M4.6 4.6l1.6 1.6M13.8 13.8l1.6 1.6M15.4 4.6l-1.6 1.6M6.2 13.8l-1.6 1.6" />
    </>
  ),
  plus: <path d="M10 4v12M4 10h12" />,
  chk: <path d="M4 10.5l4 4L16 6" />,
  x: <path d="M5 5l10 10M15 5L5 15" />,
  warn: (
    <>
      <path d="M10 3.2l7.2 12.6H2.8z" />
      <path d="M10 8v3.8M10 13.8v.1" />
    </>
  ),
  search: (
    <>
      <circle cx="9" cy="9" r="5.2" />
      <path d="M12.9 12.9l4 4" />
    </>
  ),
  ref: (
    <>
      <path d="M16.4 10a6.4 6.4 0 1 1-2-4.7" />
      <path d="M16.4 3.2v3h-3" />
    </>
  ),
  send: <path d="M3.4 10l13.2-6-6 13.2-1.8-5.4z" />,
  back: (
    <>
      <polyline points="11.6,4.2 5.4,10 11.6,15.8" />
      <line x1="5.4" y1="10" x2="16.6" y2="10" />
    </>
  ),
  bolt: <path d="M11.6 2.2L4.6 11h4.4l-1 6.6L15.4 8.6H11z" />,
  clock: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l3 2" />
    </>
  ),
  tbl: (
    <>
      <rect x="3" y="4" width="14" height="12" rx="1.8" />
      <path d="M3 8h14M7.6 8v8" />
    </>
  ),
  copy: (
    <>
      <rect x="7" y="7" width="9.6" height="9.6" rx="1.6" />
      <path d="M13.2 7V5.2c0-.9-.7-1.6-1.6-1.6H5.2c-.9 0-1.6.7-1.6 1.6v6.4c0 .9.7 1.6 1.6 1.6H7" />
    </>
  ),
  dn: <path d="M10 3.6v10M5.8 10l4.2 4.2 4.2-4.2M3.6 17h12.8" />,
  up: <path d="M10 16.4v-10M5.8 10l4.2-4.2 4.2 4.2" />,
  up2: <path d="M10 15V5M6 9l4-4 4 4M4 17h12" />,
  thumb: (
    <>
      <path d="M6.6 17V9l3.8-5.8c1.2.3 1.8 1.2 1.5 2.4l-.6 2.7h3.8c1.2 0 1.9 1 1.6 2.1l-1.1 4.9c-.2.9-1 1.5-1.9 1.5z" />
      <path d="M3 9h3.6v8H3z" />
    </>
  ),
  menu: <path d="M3 5.5h14M3 10h14M3 14.5h14" />,
  eye: (
    <>
      <path d="M1.6 10S4.6 4.4 10 4.4 18.4 10 18.4 10 15.4 15.6 10 15.6 1.6 10 1.6 10z" />
      <circle cx="10" cy="10" r="2.4" />
    </>
  ),
  ext: <path d="M11 3h6v6M17 3l-8 8M15 12v5H3V5h5" />,
  /** The way out of the product — the same glyph Document Intelligence
      puts on its "Back to the site" control, so the two read as one suite. */
  globe: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M3 10h14" />
      <path d="M10 3c1.9 2 2.9 4.4 2.9 7s-1 5-2.9 7c-1.9-2-2.9-4.4-2.9-7s1-5 2.9-7z" />
    </>
  ),
  key: (
    <>
      <circle cx="7" cy="13" r="3.4" />
      <path d="M9.4 10.6L16.4 3.6M13.6 6.4l2 2M15.6 4.4l2 2" />
    </>
  ),
  code: <path d="M7 6L3 10l4 4M13 6l4 4-4 4" />,
  cloud: (
    <path d="M14.4 15.4H6a3.6 3.6 0 0 1-.4-7.2A5 5 0 0 1 15 9.2a3.1 3.1 0 0 1-.6 6.2z" />
  ),
  file: (
    <>
      <path d="M11.4 3H5.4v14h9.2V6.2z" />
      <path d="M11.4 3v3.2h3.2" />
    </>
  ),
  /**
   * One person — the reader, beside their own question.
   *
   * `users` is the pair, which reads as an audience rather than as the person
   * who asked; drawn to the same grid and stroke language as `bot`, so the two
   * sit at the same weight on either side of a turn.
   */
  user: (
    <>
      <circle cx="10" cy="7" r="3" />
      <path d="M4.6 16.4c0-3 2.4-5.4 5.4-5.4s5.4 2.4 5.4 5.4" />
    </>
  ),
  users: (
    <>
      <circle cx="7.4" cy="7" r="2.8" />
      <path d="M2.8 16.4c0-2.6 2.1-4.6 4.6-4.6s4.6 2 4.6 4.6" />
      <path d="M13.4 5.2a2.6 2.6 0 0 1 0 5M14.6 11.9c2 .5 3.4 2.3 3.4 4.5" />
    </>
  ),
  spark: (
    <path d="M10 2.6l1.9 4.1 4.5.6-3.3 3.1.9 4.5L10 12.7l-4 2.2.9-4.5L3.6 7.3l4.5-.6z" />
  ),
  play: <path d="M6 4l9 6-9 6z" />,
  trash: <path d="M4.4 6.4h11.2M8 6.4V4.6h4v1.8M6 6.4l.7 10h6.6l.7-10" />,
  mic: (
    <>
      <rect x="7.4" y="2.6" width="5.2" height="9.2" rx="2.6" />
      <path d="M4.4 9.4a5.6 5.6 0 0 0 11.2 0" />
      <path d="M10 15v2.4M7 17.4h6" />
    </>
  ),
  speak: (
    <>
      <path d="M4 7.6h2.8L10.6 4v12L6.8 12.4H4z" />
      <path d="M13.4 7.6a3.4 3.4 0 0 1 0 4.8" />
      <path d="M15.6 5.2a6.6 6.6 0 0 1 0 9.6" />
    </>
  ),
  stop: <rect x="5.6" y="5.6" width="8.8" height="8.8" rx="1.6" />,
  eraser: (
    <>
      <path d="M8.6 16.4H16" />
      <path d="M11.8 3.6l4.6 4.6-7 7H6l-2.4-2.4z" />
    </>
  ),
  expand: <path d="M4 8V4h4M16 12v4h-4M4 4l5 5M16 16l-5-5" />,

  /* The artifact answers these roles with a glyph it already has: its
   * Analytics rail item and its "suggested chart" line both carry the table,
   * Batch Query Reports carries the document, and an assistant turn carries
   * the database mark. */
  chart: (
    <>
      <rect x="3" y="4" width="14" height="12" rx="1.8" />
      <path d="M3 8h14M7.6 8v8" />
    </>
  ),
  /* The seven readings of one result the chart picker offers. Drawn to the
     sprite's 20×20 grid and stroke language; the artifact has no chart-type
     glyphs of its own because it never offered the choice. */
  barsH: (
    <>
      <path d="M3.4 5h9.2M3.4 10h12.2M3.4 15h6.2" />
    </>
  ),
  barsV: (
    <>
      <path d="M5 16.6V9M10 16.6V3.4M15 16.6v-5.2" />
    </>
  ),
  lineUp: (
    <>
      <path d="M3.2 16.8V3.2" />
      <path d="M3.2 16.8h13.6" />
      <path d="M5.4 13.2l3.4-3.8 3 2.4 4-5.2" />
    </>
  ),
  areaUp: (
    <>
      <path d="M3.2 16.8V3.2" />
      <path d="M3.2 16.8h13.6" />
      <path d="M4.6 14.6l3.6-4.4 2.8 2.2 4.4-5.6v7.8z" />
    </>
  ),
  pie: (
    <>
      <circle cx="10" cy="10" r="6.8" />
      <path d="M10 3.2v6.8h6.8" />
    </>
  ),
  donut: (
    <>
      <circle cx="10" cy="10" r="6.8" />
      <circle cx="10" cy="10" r="2.8" />
      <path d="M10 3.2v4" />
    </>
  ),
  points: (
    <>
      <path d="M3.2 16.8V3.2" />
      <path d="M3.2 16.8h13.6" />
      <circle cx="6.4" cy="12.6" r="1.1" />
      <circle cx="9.6" cy="8.4" r="1.1" />
      <circle cx="12.4" cy="12" r="1.1" />
      <circle cx="14.8" cy="6.4" r="1.1" />
    </>
  ),
  clipboard: (
    <>
      <path d="M11.4 3H5.4v14h9.2V6.2z" />
      <path d="M11.4 3v3.2h3.2" />
    </>
  ),
  bot: (
    <>
      <ellipse cx="10" cy="5" rx="6.4" ry="2.6" />
      <path d="M3.6 5v10c0 1.4 2.9 2.6 6.4 2.6s6.4-1.2 6.4-2.6V5" />
      <path d="M3.6 10c0 1.4 2.9 2.6 6.4 2.6s6.4-1.2 6.4-2.6" />
    </>
  ),
  activity: <path d="M11.6 2.2L4.6 11h4.4l-1 6.6L15.4 8.6H11z" />,
  /** The refresh arc without its arrowhead — spun by the caller. */
  spinner: <path d="M16.4 10a6.4 6.4 0 1 1-2-4.7" />,

  /* Drawn to the artifact's grid and stroke language for the roles its sprite
   * does not cover. The chevrons are its `back` chevron, rotated and centred on
   * the box — call sites spin them with `rotate-90` / `rotate-180`, which is
   * only true to the glyph if its apex sits on the centre line. */
  down: <path d="M10 3.6v10M5.8 10l4.2 4.2 4.2-4.2" />,
  caret: <polyline points="4.2,7.2 10,12.8 15.8,7.2" />,
  caretLeft: <polyline points="12.8,4.2 7.2,10 12.8,15.8" />,
  caretRight: <polyline points="7.2,4.2 12.8,10 7.2,15.8" />,
  caretUpDown: <path d="M6.4 8.2L10 4.6l3.6 3.6M6.4 11.8L10 15.4l3.6-3.6" />,
  layers: (
    <>
      <path d="M10 2.6L3.2 6.2 10 9.8l6.8-3.6z" />
      <path d="M3.2 10.4L10 14l6.8-3.6" />
      <path d="M3.2 14.2L10 17.8l6.8-3.6" />
    </>
  ),
  percent: (
    <>
      <circle cx="6.2" cy="6.2" r="1.9" />
      <circle cx="13.8" cy="13.8" r="1.9" />
      <path d="M15.4 4.6L4.6 15.4" />
    </>
  ),
  xCircle: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M7.6 7.6l4.8 4.8M12.4 7.6l-4.8 4.8" />
    </>
  ),
  plusCircle: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6.4v7.2M6.4 10h7.2" />
    </>
  ),
  info: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 9.2v4.4M10 6.6v.1" />
    </>
  ),
  plug: (
    <>
      <path d="M7.4 2.6v4M12.6 2.6v4" />
      <path d="M4.8 6.6h10.4v2.4a5.2 5.2 0 0 1-10.4 0z" />
      <path d="M10 14.2v3.2" />
    </>
  ),
  eyeOff: (
    <>
      <path d="M7.2 5.1A9 9 0 0 1 10 4.4c5.4 0 8.4 5.6 8.4 5.6a15.6 15.6 0 0 1-2.5 3.2" />
      <path d="M4.6 6.3A15.4 15.4 0 0 0 1.6 10s3 5.6 8.4 5.6a8.6 8.6 0 0 0 3-.5" />
      <path d="M8.3 8.3a2.4 2.4 0 0 0 3.4 3.4" />
      <path d="M3 3l14 14" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof ICONS;

interface IconProps {
  name: IconName;
  /** Defaults to the 16px this product uses for inline icons. */
  className?: string;
  style?: CSSProperties;
  /**
   * The artifact varies weight by context: 1.7 in the nav rail, 1.8 on buttons
   * and cards, 2.1–2.2 on a chip or a send button. 1.8 is the common case.
   */
  strokeWidth?: number;
}

export default function Icon({
  name,
  className = "size-4",
  style,
  strokeWidth = 1.8,
}: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      className={className}
      style={style}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  );
}
