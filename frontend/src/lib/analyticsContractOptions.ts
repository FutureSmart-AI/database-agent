import type {
  AnalyticsFilterOptions,
  AnalyticsLimits,
  AnalyticsOption,
} from "@/platform/analytics/constants";

import { ANALYTICS_CONTRACT } from "../generated/analyticsContract";

/**
 * The analytics filter vocabularies this product sends, built from the NL2SQL
 * service's own OpenAPI document.
 *
 * Nothing in this file states which routes, feedback states or page sizes the
 * API accepts. Every value comes out of `ANALYTICS_CONTRACT`, which
 * `scripts/gen-analytics-contract.ts` extracts from the service's spec — so a
 * route added or renamed server-side reaches the dropdown by regenerating,
 * not by someone remembering to edit a list. The previous arrangement had the
 * agent dashboard's service families (`knowledge`, `integration`, …) hardcoded
 * as NL2SQL's `route`, which the service does not recognise: the query log came
 * back empty for every option offered, with no error to explain it.
 *
 * Only the labels are ours, and they are computed, not enumerated.
 */

/**
 * Fragments that are initialisms rather than words, for labelling only.
 *
 * A list of *spellings*, not of API values — a new route or failure category
 * needs no entry here, it just renders title-cased.
 */
const INITIALISMS = new Set(["sql", "db", "api", "id", "llm", "usd", "ms"]);

/** `cross_db` → `Cross DB`, `sql_error` → `SQL error`. */
export function humanizeCode(code: string): string {
  const words = code.split("_").filter(Boolean);
  return words
    .map((word, index) => {
      if (INITIALISMS.has(word)) return word.toUpperCase();
      // Sentence case: only the first word is capitalised, so a label reads as
      // a phrase ("Direct answer") rather than a headline ("Direct Answer").
      return index === 0
        ? word.charAt(0).toUpperCase() + word.slice(1)
        : word.toLowerCase();
    })
    .join(" ");
}

type Endpoint = keyof typeof ANALYTICS_CONTRACT;

/** The values the spec documents for one parameter, as dropdown options. */
export function contractOptions(
  endpoint: Endpoint,
  param: string,
): AnalyticsOption[] {
  const spec = (
    ANALYTICS_CONTRACT[endpoint] as Record<
      string,
      { values: readonly string[] | null } | undefined
    >
  )[param];
  return (spec?.values ?? []).map((value) => ({
    value,
    label: humanizeCode(value),
  }));
}

/** A numeric bound the spec publishes, or the given fallback. */
export function contractNumber(
  endpoint: Endpoint,
  param: string,
  field: "default" | "min" | "max",
  fallback: number,
): number {
  const spec = (
    ANALYTICS_CONTRACT[endpoint] as Record<
      string,
      Record<string, unknown> | undefined
    >
  )[param];
  const value = spec?.[field];
  return typeof value === "number" ? value : fallback;
}

/**
 * Rows-per-page choices for a paginated endpoint.
 *
 * Derived from the two numbers the spec publishes — the server's own default
 * page and its hard cap — rather than from a list someone picked, so a service
 * that raises its cap offers the larger page without a code change. Asking for
 * more than the cap is a 422, which is exactly the bug this avoids.
 */
export function pageSizeLadder(endpoint: Endpoint, param = "limit"): number[] {
  const base = contractNumber(endpoint, param, "default", 20);
  const max = contractNumber(endpoint, param, "max", base);
  return [...new Set([base, base * 2, max])]
    .filter((size) => size > 0 && size <= max)
    .sort((a, b) => a - b);
}

export const NL2SQL_FILTER_OPTIONS: AnalyticsFilterOptions = {
  routes: contractOptions("queries", "route"),
  // Not "Services Used": these are the plan the router chose for one question,
  // and this product is a single service.
  routesLabel: "Route",
  outcomes: contractOptions("queries", "outcome"),
  // Empty: this service filters the log on `outcome`, which it documents, so
  // the Status dropdown keeps sending that rather than the literal `status`.
  statuses: [],
  feedback: contractOptions("queries", "feedback").filter(
    // `any` means "rated either way", which the three explicit choices plus
    // "All" already cover; offering it reads as a fourth rating.
    (option) => option.value !== "any",
  ),
  buckets: contractOptions("scorecard", "bucket"),
  costStrategies: contractOptions("syncCosts", "strategy"),
  rowsPerPage: pageSizeLadder("queries"),
};

export const NL2SQL_LIMITS: AnalyticsLimits = {
  scorecardTopN: contractNumber("scorecard", "top_n", "default", 10),
  queriesPageSize: contractNumber("queries", "limit", "default", 20),
  failuresPageSize: contractNumber("failures", "limit", "default", 50),
};

/** Paging bounds for the fleet grid, from `/agents/analytics/overview`. */
export const NL2SQL_OVERVIEW_OPTIONS = {
  pageSizes: pageSizeLadder("overview"),
  defaultLimit: contractNumber("overview", "limit", "default", 50),
};

/** `category` and `failed_stage` on `/failures`, for that tab's own filters. */
export const NL2SQL_FAILURE_OPTIONS = {
  categories: contractOptions("failures", "category"),
  stages: contractOptions("failures", "failed_stage"),
  pageSizes: pageSizeLadder("failures"),
  maxLimit: contractNumber("failures", "limit", "max", 200),
};
