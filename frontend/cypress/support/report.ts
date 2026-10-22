import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";

/**
 * Writes a run report after `cypress run` finishes.
 *
 * Cypress' own terminal table scrolls away and its JSON reporter output is
 * shaped for CI tooling, not for a person reading what a lifecycle run actually
 * did. This writes both: `run-report.md` to read, `run-report.json` to diff or
 * feed to something else.
 *
 * Only fires for `cypress run` — the interactive runner has no run-level
 * results to report.
 */

type RunResult = CypressCommandLine.CypressRunResult;
type SpecResult = RunResult["runs"][number];
type TestResult = SpecResult["tests"][number];

const REPORT_DIR = "cypress/reports";

const STATE_MARK: Record<string, string> = {
  passed: "✅",
  failed: "❌",
  pending: "⏭️",
  skipped: "⚪",
};

const ms = (value: number | null | undefined): string => {
  if (!value) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
};

const titleOf = (test: TestResult): string => test.title.join(" › ");

/** The first failure's message, trimmed to something a table can hold. */
const failureOf = (test: TestResult): string => {
  const message = test.displayError ?? "";
  if (!message) return "";
  return message.split("\n")[0].slice(0, 200);
};

function markdown(results: RunResult): string {
  const { totalTests, totalPassed, totalFailed, totalPending, totalSkipped } =
    results;
  const started = results.startedTestsAt;
  const ended = results.endedTestsAt;

  const lines: string[] = [
    "# Cypress run report",
    "",
    `- **Started** ${started}`,
    `- **Finished** ${ended}`,
    `- **Duration** ${ms(results.totalDuration)}`,
    `- **Browser** ${results.browserName} ${results.browserVersion}`,
    `- **Cypress** ${results.cypressVersion}`,
    "",
    "| Total | Passed | Failed | Pending | Skipped |",
    "| ----- | ------ | ------ | ------- | ------- |",
    `| ${totalTests} | ${totalPassed} | ${totalFailed} | ${totalPending} | ${totalSkipped} |`,
    "",
  ];

  if (totalFailed > 0) {
    lines.push("## Failures", "");
    results.runs.forEach((run) => {
      run.tests
        ?.filter((test) => test.state === "failed")
        .forEach((test) => {
          lines.push(
            `- **${relative(process.cwd(), run.spec.absolute)}** — ${titleOf(test)}`,
            `  - ${failureOf(test) || "no message reported"}`,
          );
        });
    });
    lines.push("");
  }

  lines.push("## Specs", "");

  results.runs.forEach((run) => {
    const spec = run.spec.relative;
    lines.push(`### ${spec}`, "");
    lines.push("| | Test | Duration |", "| - | ---- | -------- |");
    (run.tests ?? []).forEach((test) => {
      const mark = STATE_MARK[test.state] ?? test.state;
      // Pipes inside a title would break the table row.
      const title = titleOf(test).replace(/\|/g, "\\|");
      lines.push(`| ${mark} | ${title} | ${ms(test.duration)} |`);
    });
    lines.push("");
  });

  return lines.join("\n");
}

/** Registers the `after:run` hook that writes the report. */
export function registerRunReport(
  on: Cypress.PluginEvents,
  projectRoot: string,
): void {
  on("after:run", (results) => {
    // `after:run` also fires for `cypress open`, where the payload carries no
    // per-spec results — nothing worth writing.
    if (!results || !("runs" in results)) return;

    const directory = join(projectRoot, REPORT_DIR);
    mkdirSync(directory, { recursive: true });

    const markdownPath = join(directory, "run-report.md");
    const jsonPath = join(directory, "run-report.json");

    mkdirSync(dirname(markdownPath), { recursive: true });
    writeFileSync(markdownPath, markdown(results as RunResult), "utf-8");
    writeFileSync(jsonPath, JSON.stringify(results, null, 2), "utf-8");

    // eslint-disable-next-line no-console
    console.log(`\nRun report written to ${REPORT_DIR}/run-report.md\n`);
  });
}
