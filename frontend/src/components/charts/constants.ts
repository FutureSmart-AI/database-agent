export const ROW_HEIGHT = 34;
/** Donut's drawing size in pixels, matching its `size-20` box. */
export const DONUT_SIZE = 80;
export const LABEL_MAX_CHARS = 24;
/** Height of a category chart in an answer's result card. */
export const CATEGORY_HEIGHT = 260;
/**
 * Slices a pie still fits a legend beside. Past this the legend would take the
 * card, so the names ride in the tooltip instead.
 */
export const PIE_LEGEND_MAX = 12;

/**
 * When a category axis has to angle its labels.
 *
 * Measured on a real answer: seven statuses fit upright, but the last of them
 * ("PROCESSING") sat at the very edge of an area chart and was clipped — a
 * point series puts its first and last labels on the container's edges, where
 * a bar's label is centred under its bar. So length counts as well as count.
 */
export const shouldAngle = (labels: string[]): boolean =>
  labels.length > 8 || labels.some((label) => label.length > 8);
