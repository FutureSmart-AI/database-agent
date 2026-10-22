import { describe, expect, it } from "vitest";

import {
  buildAnalyticsContract,
  endpointKey,
  parseVocabulary,
} from "../openapiVocab";

/**
 * The descriptions below are copied verbatim from
 * `https://app.futuresmart.ai/nl2sql/api/openapi.json`. They are the input
 * the generator actually runs on, so a service that rewords one of them fails
 * here rather than silently producing an empty dropdown.
 */
describe("parseVocabulary", () => {
  it("reads a bare pipe-separated list", () => {
    expect(parseVocabulary("sql | cross_db | pandas | direct_answer")).toEqual([
      "sql",
      "cross_db",
      "pandas",
      "direct_answer",
    ]);
  });

  it("drops the prose lead-in before a colon", () => {
    expect(
      parseVocabulary(
        "Node the failure is attributed to: router | db_router | sql_gen | sql_exec | final_answer | chat_api",
      ),
    ).toEqual([
      "router",
      "db_router",
      "sql_gen",
      "sql_exec",
      "final_answer",
      "chat_api",
    ]);
  });

  it("drops parenthetical glosses", () => {
    expect(
      parseVocabulary(
        "Filter by user feedback: positive | negative | none (unrated) | any (rated)",
      ),
    ).toEqual(["positive", "negative", "none", "any"]);
  });

  it("reads a csv list introduced by 'of'", () => {
    expect(
      parseVocabulary(
        "csv subset of success_rate,avg_ms,p95_ms,cost,failures,total_queries",
      ),
    ).toEqual([
      "success_rate",
      "avg_ms",
      "p95_ms",
      "cost",
      "failures",
      "total_queries",
    ]);
  });

  it("reads a list whose values carry parenthetical glosses", () => {
    expect(
      parseVocabulary(
        "run_id (direct read_run per row) | metadata (agent_id/chat_id rollup) | both",
      ),
    ).toEqual(["run_id", "metadata", "both"]);
  });

  it("reads the scorecard granularity", () => {
    expect(
      parseVocabulary("usage.per_day granularity: hour | day | week | month"),
    ).toEqual(["hour", "day", "week", "month"]);
  });

  /**
   * The guard that matters most. This description splits on its comma into two
   * candidates and would otherwise be read as the two-value enum
   * `["end", "exclusive"]` — a filter dropdown built from an English sentence.
   */
  it("rejects prose that merely contains a comma", () => {
    expect(
      parseVocabulary("Custom range end, exclusive (ISO-8601)"),
    ).toBeNull();
  });

  it("rejects prose with a semicolon and a lead-in colon", () => {
    expect(
      parseVocabulary(
        "Custom range start (ISO-8601); with end_date overrides period",
      ),
    ).toBeNull();
  });

  it("rejects a single-value description", () => {
    expect(parseVocabulary("Only queries routed to this database")).toBeNull();
  });

  it("rejects an absent description", () => {
    expect(parseVocabulary(undefined)).toBeNull();
    expect(parseVocabulary("")).toBeNull();
  });
});

describe("endpointKey", () => {
  it("keys on the last path segment, camel-cased", () => {
    expect(endpointKey("/v1/agents/{agent_id}/analytics/sync-costs")).toBe(
      "syncCosts",
    );
    expect(endpointKey("/v1/agents/{agent_id}/analytics/scorecard")).toBe(
      "scorecard",
    );
    expect(endpointKey("/v1/agents/analytics/overview")).toBe("overview");
  });
});

describe("buildAnalyticsContract", () => {
  const spec = {
    paths: {
      "/v1/agents/{agent_id}/analytics/queries": {
        get: {
          parameters: [
            { name: "agent_id", in: "path", schema: { type: "string" } },
            {
              name: "route",
              in: "query",
              description: "sql | cross_db | pandas | direct_answer",
              schema: { anyOf: [{ type: "string" }, { type: "null" }] },
            },
            {
              name: "limit",
              in: "query",
              schema: {
                type: "integer",
                maximum: 100,
                minimum: 1,
                default: 20,
              },
            },
            {
              name: "include_node_data",
              in: "query",
              description:
                "Include the per-node breakdown (metrics.node_data) in each row; set false for a lean list",
              schema: { type: "boolean", default: true },
            },
          ],
        },
      },
      "/v1/agents/{agent_id}/chat": { post: { parameters: [] } },
    },
  };

  const contract = buildAnalyticsContract(spec);

  it("covers only the analytics paths", () => {
    expect(Object.keys(contract)).toEqual(["queries"]);
  });

  it("skips path parameters", () => {
    expect(contract.queries.agent_id).toBeUndefined();
  });

  it("carries values, bounds and defaults", () => {
    expect(contract.queries.route.values).toEqual([
      "sql",
      "cross_db",
      "pandas",
      "direct_answer",
    ]);
    expect(contract.queries.limit).toEqual({
      default: 20,
      min: 1,
      max: 100,
      values: null,
    });
    expect(contract.queries.include_node_data.default).toBe(true);
  });
});
