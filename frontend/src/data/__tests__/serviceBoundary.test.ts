import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { APIS } from "../api";

/**
 * The Database Agent talks to the NL2SQL service and nothing else.
 *
 * The code carried over from the agent UI (`src/platform/`) was written against
 * the chat, dashboard and usage services, and it kept falling back to them: a
 * credentials call with no routes passed went to `/api/usage`, the analytics
 * scope defaulted to `/api/dashboard`, feedback without a service id went to
 * the dashboard's session route. Those services answer 403 for an `NL2SQL_…`
 * agent, so every such fallback is a screen that silently reads empty. This
 * walks every source file — the shared code included — and fails on any path
 * on another service.
 */

const SRC = join(__dirname, "../..");

/**
 * The two stated exceptions: the hosted login (`authServiceUrl` /
 * `authLoginUrlFor`, which the NL2SQL service has no equivalent for) and the
 * voice gateway (`sttUrl`, optional, hidden without a key). Negated matchers in
 * tests name a path in order to forbid it.
 */
const ALLOWED = [
  /authServiceUrl/,
  /authLoginUrlFor/,
  /export const sttUrl = /,
  /\.not\.(toContain|toMatch|toEqual|toBe|toHaveBeenCalledWith)\b/,
];

/** `/api/<service>` anywhere, except the NL2SQL service's own `/nl2sql/api/…`. */
const OTHER_SERVICE = /(?<!\/nl2sql)\/api\/[a-z][a-z0-9-]*/;

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/^\s*\/\/.*$/gm, "");
}

function sourceFiles(dir = SRC): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [relative(SRC, path)] : [];
  });
}

const FILES = sourceFiles();

describe("every route this app names is on the NL2SQL service", () => {
  it("lists only NL2SQL routes", () => {
    for (const url of Object.values(APIS)) {
      expect(url.startsWith("/nl2sql/api/"), url).toBe(true);
    }
  });
});

describe("no other service is called from this app", () => {
  it("scans the whole source tree, shared code included", () => {
    expect(FILES.length).toBeGreaterThan(250);
    expect(FILES).toContain(join("data", "api.ts"));
    expect(FILES).toContain(join("platform", "hooks", "useChatStream.tsx"));
  });

  it("catches a route however it is written", () => {
    for (const line of [
      "const API_PREFIX = " + JSON.stringify("/ap" + "i/usage") + ";",
      "url: `${baseUrl}" + "/ap" + "i/chat/v1/chat_completion`,",
      "axios.get(`" + "/ap" + "i/dashboard/v1/sessions`)",
    ]) {
      expect(OTHER_SERVICE.test(line), line).toBe(true);
    }
    expect(OTHER_SERVICE.test("`/nl2sql/api/v1/agents/${id}/chat`")).toBe(
      false,
    );
  });

  it.each(FILES)("%s", (file) => {
    const source = stripComments(readFileSync(join(SRC, file), "utf8"));
    const offending = source
      .split("\n")
      .map((line, index) => `${index + 1}: ${line.trim()}`)
      .filter(
        (line) =>
          OTHER_SERVICE.test(line) &&
          !ALLOWED.some((allowed) => allowed.test(line)),
      );
    expect(offending).toEqual([]);
  });
});
