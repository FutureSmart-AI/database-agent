/** Product wordmark, shown in the sidebar and page titles. */
export const PRODUCT_NAME = "Database Agent";

/**
 * Badges an agent card shows before rolling the rest into "+N more" — two rows
 * of pills, which is what fits under the name at `AGENT_CARD_HEIGHT`.
 */
export const BADGES_PER_CARD = 4;

/**
 * Every card in the agent grid is this tall, as on the agent UI's own All
 * Agents board — a row of cards that all end at the same line.
 */
export const AGENT_CARD_HEIGHT = "h-[280px]";

/** The agent grid itself, same track sizing as the agent UI's board. */
export const AGENT_GRID =
  "grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4";
