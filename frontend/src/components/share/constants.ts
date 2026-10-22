export const SWATCHES = [
  "#4f46e5",
  "#7C3AED",
  "#15803D",
  "#B87C15",
  "#DB2777",
  "#0F766E",
  "#111827",
];
export const FEATURE_CHIPS: Array<[key: string, label: string]> = [
  ["show_sources", "Shows the SQL"],
  ["follow_up", "Follow-up questions"],
  ["chart_output", "Charts"],
  ["memory", "Remembers context"],
  ["raw_response", "Raw response"],
  ["voice_input", "Voice input"],
  ["voice_output", "Reads answers aloud"],
];

/**
 * Share row disclosure motion. The open leg is longer than the close: a row
 * opening is content you are about to read, a row closing is out of the way.
 */
export const ROW_OPEN_MS = 260;
export const ROW_CLOSE_MS = 200;
export const ROW_EASE = "cubic-bezier(.22,.61,.36,1)";

/** Every disclosure row on the Share screen, in the order they are worked through. */
export const SHARE_ROWS = [
  "answers",
  "widget",
  "fullpage",
  "api",
  "people",
  "appearance",
  "preview",
] as const;

export type ShareRowKey = (typeof SHARE_ROWS)[number];

/** Date windows the Activity list filters by, as on the artifact's Share screen. */
export const ACTIVITY_RANGES: Array<[value: string, label: string]> = [
  ["all", "All time"],
  ["1", "Last 24 hours"],
  ["7", "Last 7 days"],
  ["30", "Last 30 days"],
];
