/**
 * Formatters ported verbatim from the design prototype so numbers render
 * character-for-character the same as the artifact.
 */

/** 1284 → "1,284" · 273700 → "273.7K" · 1.6e6 → "1.6M" */
export const nfmt = (n: number): string =>
  n >= 1e6
    ? `${(n / 1e6).toFixed(1)}M`
    : n >= 1e4
      ? `${(n / 1e3).toFixed(1)}K`
      : n >= 1000
        ? n.toLocaleString("en-US")
        : String(n);

/** 104 → "104ms" · 1450 → "1.45s" · 42000 → "42.0s" */
export const ms = (n: number): string =>
  n >= 1000
    ? `${(n / 1000).toFixed(n < 10000 ? 2 : 1)}s`
    : `${Math.round(n)}ms`;

/** 96.2 → "96.2%" */
export const pct = (n: number): string => `${n.toFixed(1)}%`;

/** Chart value labels: 742183.55 → "742.2K" · 8774 → "8.8K" · 2.4 → "2.4" */
export const compact = (v: number): string =>
  Math.abs(v) >= 1e6
    ? `${(v / 1e6).toFixed(1)}M`
    : Math.abs(v) >= 1e3
      ? `${(v / 1e3).toFixed(1)}K`
      : String(+(+v).toFixed(2));

/**
 * Relative time, as the artifact's `ago()`. Takes `now` so callers can pass a
 * fixed instant and keep server and client markup identical.
 */
export const ago = (at: number, now: number): string => {
  const seconds = (now - at) / 1000;
  if (seconds < 60) return `${Math.max(1, Math.floor(seconds))}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  const days = Math.floor(seconds / 86400);
  return days < 30 ? `${days}d ago` : `${Math.floor(days / 30)}mo ago`;
};
