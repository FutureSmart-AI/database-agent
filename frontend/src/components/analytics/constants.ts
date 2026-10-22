import type { AnalyticsTabKey } from "@/platform/analytics/types";

/**
 * The agent dashboard's five tabs, plus one.
 *
 * Deliberately not widening `AnalyticsTabKey` itself: that union drives the
 * dashboard page's exhaustive `tabComponents` record, and adding a key there
 * would oblige a product that has no `/failures` endpoint to render a tab it
 * cannot fill.
 */
export type Nl2sqlTabKey = AnalyticsTabKey | "failures";

/**
 * Failures sits after Cost and before Query Logs — it answers the question
 * Quality raises and cannot settle (*why* did the unanswered ones fail), and
 * Query Logs stays last as the raw drill-down it is on the agent dashboard.
 */
export const NL2SQL_ANALYTICS_TABS: { key: Nl2sqlTabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "quality", label: "Quality & Accuracy" },
  { key: "performance", label: "Performance" },
  { key: "cost", label: "Cost" },
  { key: "failures", label: "Failures" },
  { key: "querylogs", label: "Query Logs" },
];
