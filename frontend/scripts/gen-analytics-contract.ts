#!/usr/bin/env bun
/**
 * Generate the NL2SQL analytics parameter contract from the service's OpenAPI
 * document.
 *
 * The analytics screen needs to know which values each filter accepts — routes,
 * feedback states, failure categories, page bounds. Those used to be typed by
 * hand next to the dropdowns, and one of the copies was wrong: the agent
 * dashboard's service families were being sent as NL2SQL's `route`, whose
 * values are `sql | cross_db | pandas | direct_answer`. Every choice in that
 * dropdown returned an empty log, quietly.
 *
 * So they are read from the service instead. Run this whenever the analytics
 * API changes; the output is committed, so no build or test run needs network
 * access.
 *
 * Usage:
 *   bun scripts/gen-analytics-contract.ts
 *   bun scripts/gen-analytics-contract.ts --check       # fail if the committed file is stale
 *   bun scripts/gen-analytics-contract.ts --spec ./openapi.json
 *
 * Env:
 *   NL2SQL_OPENAPI_URL  override the spec URL (defaults to production)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import prettier from "prettier";

import {
  buildAnalyticsContract,
  type AnalyticsContract,
} from "../src/lib/openapiVocab";

const REPO_ROOT = join(dirname(new URL(import.meta.url).pathname), "..");
const OUT_FILE = join(REPO_ROOT, "src/generated/analyticsContract.ts");
const DEFAULT_URL =
  process.env.NL2SQL_OPENAPI_URL ??
  "https://app.futuresmart.ai/nl2sql/api/openapi.json";

async function loadSpec(local: string | undefined): Promise<unknown> {
  if (local) return JSON.parse(readFileSync(local, "utf8"));
  const res = await fetch(DEFAULT_URL);
  if (!res.ok) {
    throw new Error(`GET ${DEFAULT_URL} → ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/**
 * The contract as a TypeScript literal.
 *
 * Emitted key-sorted and `as const` so the file is a stable diff — a rerun that
 * changes nothing produces a byte-identical file, which is what makes `--check`
 * meaningful — and so every value keeps its literal type downstream.
 */
function render(contract: AnalyticsContract, version: string): string {
  const body = Object.keys(contract)
    .sort()
    .map((endpoint) => {
      const params = contract[endpoint];
      const lines = Object.keys(params)
        .sort()
        .map((name) => {
          const p = params[name];
          const values = p.values
            ? `[${p.values.map((v) => JSON.stringify(v)).join(", ")}]`
            : "null";
          return (
            `    ${JSON.stringify(name)}: { ` +
            `default: ${JSON.stringify(p.default)}, ` +
            `min: ${JSON.stringify(p.min)}, ` +
            `max: ${JSON.stringify(p.max)}, ` +
            `values: ${values} },`
          );
        })
        .join("\n");
      return `  ${JSON.stringify(endpoint)}: {\n${lines}\n  },`;
    })
    .join("\n");

  return `/**
 * GENERATED FILE — do not edit.
 *
 * The analytics query parameters the NL2SQL service accepts, extracted from its
 * OpenAPI document (spec version ${version}) by
 * \`scripts/gen-analytics-contract.ts\`. Regenerate with:
 *
 *   bun run gen:analytics
 *
 * \`values\` is the closed set a parameter accepts, or \`null\` where the spec
 * documents no vocabulary — \`sort\`, \`order\` and \`period\` have none, so those
 * stay declared alongside the code that uses them.
 */
import type { AnalyticsContract } from "../lib/openapiVocab";

export const ANALYTICS_CONTRACT = {
${body}
} as const satisfies AnalyticsContract;

export type AnalyticsEndpoint = keyof typeof ANALYTICS_CONTRACT;
`;
}

async function main() {
  const args = process.argv.slice(2);
  const check = args.includes("--check");
  const specIndex = args.indexOf("--spec");
  const local = specIndex >= 0 ? args[specIndex + 1] : undefined;

  const spec = await loadSpec(local);
  const version =
    ((spec as { info?: { version?: string } })?.info?.version ?? "unknown") ||
    "unknown";
  const contract = buildAnalyticsContract(spec);

  const endpoints = Object.keys(contract);
  if (!endpoints.length) {
    throw new Error(
      "No /analytics paths found in the spec — refusing to write",
    );
  }

  // Formatted with the repo's own prettier config, so the generated file is
  // indistinguishable from a hand-written one to `format:check` and to review.
  const next = await prettier.format(render(contract, version), {
    ...(await prettier.resolveConfig(OUT_FILE)),
    filepath: OUT_FILE,
  });
  const current = (() => {
    try {
      return readFileSync(OUT_FILE, "utf8");
    } catch {
      return null;
    }
  })();

  if (check) {
    if (current === next) {
      console.log(
        `✓ analyticsContract.ts is current (${endpoints.length} endpoints)`,
      );
      return;
    }
    console.error(
      "✗ analyticsContract.ts is stale — run `bun run gen:analytics`",
    );
    process.exit(1);
  }

  if (current === next) {
    console.log(`✓ no change (${endpoints.length} endpoints)`);
    return;
  }

  writeFileSync(OUT_FILE, next);
  console.log(
    `✓ wrote ${OUT_FILE.replace(`${REPO_ROOT}/`, "")} — ${endpoints.length} endpoints: ${endpoints.join(", ")}`,
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
