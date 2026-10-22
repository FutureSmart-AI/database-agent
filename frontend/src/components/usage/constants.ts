import type { IconName } from "@/components/Icon";
import { USAGE_PERIODS } from "@/data/usage";

export const TABS = [
  { key: "overview", label: "Overview" },
  { key: "limits", label: "Limits" },
  { key: "agents", label: "Agents" },
  { key: "filters", label: "Custom Filters" },
] as const;

export const USAGE_NAV_ICONS: Record<(typeof TABS)[number]["key"], IconName> = {
  overview: "spark",
  limits: "bolt",
  agents: "db",
  filters: "search",
};

export const USAGE_SOURCE_OPTIONS = [
  { value: "total", label: "Total Consumptions" },
  { value: "platform", label: "Platform Consumptions" },
  { value: "owner", label: "Owner Consumptions" },
] as const;

export const USAGE_PERIOD_OPTIONS = USAGE_PERIODS.map(({ value, label }) => ({
  value,
  label,
}));

export const TREND_METRIC_OPTIONS = [
  { value: "total_tokens", label: "Total Tokens" },
  { value: "input_tokens", label: "Input Tokens" },
  { value: "output_tokens", label: "Output Tokens" },
  { value: "requests", label: "Requests" },
  { value: "cost", label: "Cost" },
] as const;

/**
 * `/v1/trend` buckets by day, week or month and 422s on anything else — an
 * hourly option was offered here until it was checked against the service.
 */
export const TREND_GRANULARITY_OPTIONS = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
] as const;

/**
 * The four account metrics, and what each reads off an aggregate group.
 *
 * `Requests` is `event_count`, which the API contract names as the Requests
 * figure; the other three are metric totals.
 */
export const ACCOUNT_METRICS = [
  {
    key: "total_tokens",
    label: "Total Tokens",
    foot: "input + output, every agent",
  },
  {
    key: "input_tokens",
    label: "Input Tokens",
    foot: "prompts sent to the models",
  },
  {
    key: "output_tokens",
    label: "Output Tokens",
    foot: "completions written back",
  },
  {
    key: "requests",
    label: "Requests",
    foot: "operations billed in this period",
  },
] as const;

export type AccountMetricKey = (typeof ACCOUNT_METRICS)[number]["key"];

/**
 * The two operations this product records that are not model calls.
 *
 * Matched on the exact `operation` value the service groups by, not on a
 * substring of a label: `db_query` and `code_execution` are the values, and
 * guessing at them from words like "sql" would silently pick up an LLM call
 * named after the SQL it writes.
 */
export const SERVICE_OPERATIONS = [
  {
    operation: "db_query",
    label: "Database queries",
    foot: "statements executed against your databases",
  },
  {
    operation: "code_execution",
    label: "Code executions",
    foot: "post-processing runs over returned rows",
  },
] as const;
