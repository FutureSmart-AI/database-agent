"use client";

import { useState } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import Icon from "@/components/Icon";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import Field from "@/components/ui/Field";
import PageHeader from "@/components/ui/PageHeader";
import { TableSkeleton } from "@/components/ui/Skeletons";
import TabNav from "@/components/ui/TabNav";
import {
  useReportMutations,
  useReports,
  useReportSettings,
  useRun,
  useRuns,
  useRunStatus,
  type QueryGroup,
  type Report,
} from "@/data/reports";
import { useAgent } from "@/data/useAgents";
import { apiMessage, friendlyApiMessage } from "@/lib/apiError";
import { nfmt } from "@/lib/format";
import { markdown } from "@/lib/markdown";
import { TABLE } from "@/lib/tableStyles";
import {
  effectiveRunStatus,
  isEffectivelyDone,
} from "@/platform/components/batch-reports/runStatus";
import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import NL2SQLPanel from "@/platform/components/conversations/NL2SQLPanel";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Input, Select } from "@/platform/components/ui";
import type {
  QueryResult,
  RunGroupResult,
  ScheduleFrequency,
} from "@/platform/types/batch-reports";
import { cn } from "@/platform/utils";

import { EMPTY_REPORT, QUERY_VERDICT, STATUS_TONE } from "./constants";

type Page = "list" | "form" | "detail" | "run";
const reportSchema = z.object({
  name: z.string(),
  instructions: z.string(),
  analysis: z.string(),
  schedule: z.string(),
  groups: z.array(
    z.object({
      type: z.enum(["independent", "sequential"]),
      queries: z.array(z.string()),
    }),
  ),
});
type ReportForm = z.infer<typeof reportSchema>;

const queryVerdict = (result: QueryResult) => {
  if (!result.answer && !result.error) return QUERY_VERDICT.pending;
  if (result.error) return QUERY_VERDICT.fail;
  const reported = (result as Record<string, unknown>).status as
    string | undefined;
  if (reported && QUERY_VERDICT[reported]) return QUERY_VERDICT[reported];
  const score = result.relevance_score;
  if (score == null || score >= 0.7) return QUERY_VERDICT.pass;
  return score >= 0.4 ? QUERY_VERDICT.weak : QUERY_VERDICT.fail;
};

/** "1.4s", "820ms", "—" */
const ms = (value: number | null | undefined) => {
  if (value == null) return "—";
  return value >= 1000
    ? `${(value / 1000).toFixed(1)}s`
    : `${Math.round(value)}ms`;
};

/** "18 Jun 2026, 14:30" */
const absT = (at: string | null | undefined) =>
  at
    ? new Date(at).toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

// `query_groups` is nullable on the NL2SQL service's ReportResponse.
const countQueries = (groups: QueryGroup[] | null | undefined) =>
  (groups ?? []).reduce((total, group) => total + group.queries.length, 0);

/** `token_usage` is a bare total on some runs and a breakdown object on others. */
const totalTokens = (result: QueryResult): number | undefined => {
  const usage = (result as Record<string, unknown>).token_usage;
  if (typeof usage === "number") return usage;
  if (usage && typeof usage === "object") {
    const total = (usage as Record<string, unknown>).total_tokens;
    if (typeof total === "number") return total;
  }
  return undefined;
};

/** One query inside a run: its answer, its failure, and the SQL it ran. */
function ResultCard({ result }: { result: QueryResult }) {
  const verdict = queryVerdict(result);
  const tokens = totalTokens(result);
  // SQL agents carry execution_details in the same shape chat's data.nl2sql
  // uses, so the chat panel renders the query, tables and result rows as-is.
  const nl2sql = result.execution_details
    ? normalizeNl2sql({ data: { nl2sql: result.execution_details } })
    : null;

  return (
    <div className="border-t border-slate-100 p-4 first:border-t-0">
      <div className="flex items-start gap-2">
        <b className="text-sm text-slate-800">{result.question}</b>
        <Chip size="sm" tone={verdict.tone} className="ml-auto shrink-0">
          {verdict.label}
        </Chip>
      </div>

      <p className="mt-1 text-xs text-slate-500">
        {ms(result.response_time_ms)}
        {tokens != null ? ` · ${nfmt(tokens)} tokens` : ""}
        {result.relevance_score != null
          ? ` · relevance ${result.relevance_score.toFixed(2)}`
          : ""}
      </p>

      {result.answer ? (
        <div className="mt-2 text-sm text-slate-700">
          {markdown(result.answer)}
        </div>
      ) : result.error ? (
        <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900">
          {result.error}
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-400 italic">
          No answer recorded for this query.
        </p>
      )}

      {nl2sql && (
        <div className="mt-3">
          <NL2SQLPanel view={nl2sql} showQuery showResults />
        </div>
      )}
    </div>
  );
}

/** One query group — independent queries, or the steps of a sequential run. */
function GroupSection({
  group,
  index,
}: {
  group: RunGroupResult;
  index: number;
}) {
  const sequential = group.type === "sequential";
  return (
    <Card className="mb-3 overflow-hidden">
      <CardHeader
        title={`Group ${index + 1} · ${sequential ? "Sequential" : "Independent"}`}
        note={`${group.results.length} ${sequential ? "steps" : "queries"}`}
      />
      {group.results.length ? (
        group.results.map((result, i) => (
          <ResultCard key={result.query_id ?? i} result={result} />
        ))
      ) : (
        <CardBody className="text-sm text-slate-400">
          This group produced no results.
        </CardBody>
      )}
    </Card>
  );
}

interface ReportsViewProps {
  agentId?: string;
}

/**
 * Batch query reports, live: the list, its runs and each run's results all come
 * from `/nl2sql/api/v1/agents/{agent_id}/reports…`. Running a report starts a
 * real backend run.
 */
export default function ReportsView({ agentId }: ReportsViewProps) {
  const { toast } = useToast();
  const { agent, isLoading: agentLoading } = useAgent(agentId);

  const [page, setPage] = useState<Page>("list");
  const [reportId, setReportId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const { control, reset, setValue, watch } = useForm<ReportForm>({
    resolver: zodResolver(reportSchema),
    defaultValues: EMPTY_REPORT,
  });
  const {
    fields: groupFields,
    append: appendGroup,
    remove: removeGroup,
  } = useFieldArray({ control, name: "groups", keyName: "fieldId" });
  const form = watch();

  const reports = useReports(agent?.agent_id);
  // The service caps how many queries one report may hold and answers 422 over
  // it, so the form checks the agent's own cap before sending.
  const maxQueries = useReportSettings(agent?.agent_id).data
    ?.max_queries_per_report;
  const runs = useRuns(agent?.agent_id, reportId);
  // The full result only exists once the run stops moving, so poll the cheap
  // status endpoint and fetch the body when it settles.
  const runStatus = useRunStatus(agent?.agent_id, reportId, runId);
  const runFinished = isEffectivelyDone(
    runStatus.data?.status,
    runStatus.data?.progress,
  );
  const run = useRun(agent?.agent_id, reportId, runId, runFinished);
  const mutations = useReportMutations(agent?.agent_id);

  const report = reports.data?.find((entry) => entry.report_id === reportId);

  if (!agent) {
    return (
      <Card>
        <EmptyState
          icon={agentLoading ? "ref" : "warn"}
          title={agentLoading ? "Loading this agent…" : "No agent"}
        />
      </Card>
    );
  }

  const startRun = async (target: Report) => {
    try {
      const started = await mutations.run.mutateAsync(target.report_id);
      setReportId(target.report_id);
      setRunId(started.run_id ?? null);
      setPage("detail");
      toast.success(`${target.name} is running.`);
    } catch (error) {
      toast.error(`Could not start the run: ${apiMessage(error)}`);
    }
  };

  const save = async (runNow: boolean) => {
    const groups = form.groups
      .map((group) => ({
        type: group.type,
        queries: group.queries.filter((query) => query.trim()),
      }))
      .filter((group) => group.queries.length);

    if (!form.name.trim() || !groups.length) {
      toast.error("A report needs a name and at least one query.");
      return;
    }

    const total = countQueries(groups);
    if (maxQueries != null && total > maxQueries) {
      toast.error(
        `This agent allows ${maxQueries} queries per report — remove ${total - maxQueries}.`,
      );
      return;
    }

    try {
      await mutations.create.mutateAsync({
        name: form.name.trim(),
        query_groups: groups,
        report_instructions: form.instructions || undefined,
        analysis_prompt: form.analysis || undefined,
        // The service takes an object, not a bare frequency.
        schedule:
          form.schedule === "none"
            ? null
            : {
                frequency: form.schedule as ScheduleFrequency,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              },
        run_immediately: runNow,
      });
      toast.success(runNow ? "Report created and running." : "Report created.");
      setPage("list");
    } catch (error) {
      toast.error(`Could not save the report: ${apiMessage(error)}`);
    }
  };

  // ── list ──────────────────────────────────────────────────────────────────
  if (page === "list") {
    return (
      <>
        <PageHeader
          title="Reports"
          subtitle="Batch query evaluations — define a set of queries, run them on demand or on a schedule."
          action={
            <Button
              startIcon={<Icon name="plus" className="size-4" />}
              onClick={() => {
                reset(EMPTY_REPORT);
                setPage("form");
              }}
            >
              New Report
            </Button>
          }
        />

        <Card className="overflow-hidden">
          {reports.isLoading ? (
            <TableSkeleton cols={5} />
          ) : reports.error ? (
            <EmptyState
              icon="warn"
              title="Reports could not be loaded"
              note={friendlyApiMessage(
                reports.error,
                "The Database Agent service did not return this agent's reports. Try again in a moment.",
              )}
            />
          ) : !reports.data?.length ? (
            <EmptyState
              icon="file"
              title="No reports yet"
              note="Create one to evaluate a set of questions in a batch."
            />
          ) : (
            <div className={TABLE.wrap}>
              <table className={TABLE.table}>
                <thead>
                  <tr className={TABLE.headRow}>
                    {["Report", "Queries", "Schedule", "Created", ""].map(
                      (head, index) => (
                        <th key={index} className={TABLE.th}>
                          {head}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {reports.data.map((entry) => (
                    <tr
                      key={entry.report_id}
                      className={cn(TABLE.row, "cursor-pointer")}
                      onClick={() => {
                        setReportId(entry.report_id);
                        setPage("detail");
                      }}
                    >
                      <td
                        className={cn(TABLE.td, "font-medium text-slate-800")}
                      >
                        {entry.name}
                      </td>
                      <td className={TABLE.td}>
                        {entry.query_groups?.length ?? 0} groups ·{" "}
                        {countQueries(entry.query_groups)} queries
                      </td>
                      <td className={TABLE.td}>
                        <Chip tone="slate" size="sm">
                          {entry.schedule?.frequency ?? "Manual"}
                        </Chip>
                      </td>
                      <td className={cn(TABLE.td, "text-xs text-slate-500")}>
                        {absT(entry.created_at)}
                      </td>
                      <td className={cn(TABLE.td, "whitespace-nowrap")}>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Run ${entry.name} now`}
                          startIcon={<Icon name="play" className="size-4" />}
                          onClick={(event) => {
                            event.stopPropagation();
                            startRun(entry);
                          }}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete ${entry.name}`}
                          startIcon={<Icon name="trash" className="size-4" />}
                          onClick={async (event) => {
                            event.stopPropagation();
                            try {
                              await mutations.remove.mutateAsync(
                                entry.report_id,
                              );
                              toast.success(`${entry.name} deleted.`);
                            } catch (error) {
                              toast.error(
                                `Could not delete it: ${apiMessage(error)}`,
                              );
                            }
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </>
    );
  }

  // ── create ────────────────────────────────────────────────────────────────
  if (page === "form") {
    return (
      <>
        <button
          type="button"
          onClick={() => setPage("list")}
          className="mb-4 inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-indigo-600"
        >
          <Icon name="back" className="size-4" /> Reports
        </button>
        <PageHeader
          title="Create Report"
          subtitle={
            maxQueries != null
              ? `Define the queries this report runs against the agent — up to ${maxQueries}.`
              : "Define the queries this report runs against the agent."
          }
        />

        <Card className="mb-4">
          <CardBody className="space-y-4">
            <Field required label="Report name" htmlFor="repName">
              <Input
                id="repName"
                placeholder="e.g. Weekly QA"
                value={form.name}
                onChange={(value) => setValue("name", value)}
              />
            </Field>
            <Field label="Report instructions" htmlFor="repInstr">
              <Input
                as="textarea"
                id="repInstr"
                rows={2}
                placeholder="Guidance applied to every query."
                value={form.instructions}
                onChange={(value) => setValue("instructions", value)}
              />
            </Field>
            <Field label="Analysis prompt" htmlFor="repAnalysis">
              <Input
                as="textarea"
                id="repAnalysis"
                rows={2}
                placeholder="Runs after every query completes."
                value={form.analysis}
                onChange={(value) => setValue("analysis", value)}
              />
            </Field>
            <Field className="max-w-xs" label="Schedule" htmlFor="repSchedule">
              <Select
                id="repSchedule"
                value={form.schedule}
                onChange={(value) => setValue("schedule", value)}
                options={[
                  { value: "none", label: "Manual runs only" },
                  { value: "daily", label: "Daily" },
                  { value: "weekly", label: "Weekly" },
                ]}
              />
            </Field>
          </CardBody>
        </Card>

        {groupFields.map((field, groupIndex) => {
          const group = form.groups[groupIndex] ?? field;
          return (
            <Card key={field.fieldId} className="mb-3 shadow-none">
              <CardBody className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <b className="text-sm text-slate-800">
                    Group {groupIndex + 1}
                  </b>
                  <TabNav<"independent" | "sequential">
                    label={`Group ${groupIndex + 1} type`}
                    activeTab={group.type}
                    onChange={(type) =>
                      setValue(`groups.${groupIndex}.type`, type)
                    }
                    tabs={[
                      { key: "independent", label: "Independent" },
                      { key: "sequential", label: "Sequential" },
                    ]}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() => removeGroup(groupIndex)}
                  >
                    Remove
                  </Button>
                </div>
                {group.queries.map((query, queryIndex) => (
                  <div key={queryIndex} className="flex items-center gap-2">
                    <Input
                      className="flex-1"
                      placeholder="Query…"
                      value={query}
                      aria-label={`Query ${queryIndex + 1} of group ${groupIndex + 1}`}
                      onChange={(value) =>
                        setValue(
                          `groups.${groupIndex}.queries.${queryIndex}`,
                          value,
                        )
                      }
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Remove query"
                      startIcon={<Icon name="x" className="size-4" />}
                      onClick={() =>
                        setValue(
                          `groups.${groupIndex}.queries`,
                          group.queries.filter((_, i) => i !== queryIndex),
                        )
                      }
                    />
                  </div>
                ))}
                <Button
                  variant="secondary"
                  size="sm"
                  startIcon={<Icon name="plus" className="size-4" />}
                  onClick={() =>
                    setValue(`groups.${groupIndex}.queries`, [
                      ...group.queries,
                      "",
                    ])
                  }
                >
                  Add query
                </Button>
              </CardBody>
            </Card>
          );
        })}

        <div className="mb-4 flex gap-2">
          {(["independent", "sequential"] as const).map((type) => (
            <Button
              key={type}
              variant="secondary"
              size="sm"
              startIcon={<Icon name="plus" className="size-4" />}
              onClick={() => appendGroup({ type, queries: [""] })}
            >
              {type === "independent" ? "Independent" : "Sequential"} group
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => setPage("list")}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            className="ml-auto"
            loading={mutations.create.isPending}
            onClick={() => save(false)}
          >
            Save Report
          </Button>
          <Button
            startIcon={<Icon name="play" className="size-4" />}
            loading={mutations.create.isPending}
            onClick={() => save(true)}
          >
            Save &amp; Run
          </Button>
        </div>
      </>
    );
  }

  // ── detail: run history ───────────────────────────────────────────────────
  if (page === "detail" && report) {
    return (
      <>
        <button
          type="button"
          onClick={() => setPage("list")}
          className="mb-4 inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-indigo-600"
        >
          <Icon name="back" className="size-4" /> Reports
        </button>
        <PageHeader
          title={report.name}
          subtitle={`${report.query_groups?.length ?? 0} query groups · ${countQueries(report.query_groups)} queries`}
          action={
            <>
              <Button
                variant="secondary"
                startIcon={<Icon name="ref" className="size-4" />}
                onClick={() => runs.refetch()}
              >
                Check status
              </Button>
              <Button
                startIcon={<Icon name="play" className="size-4" />}
                loading={mutations.run.isPending}
                onClick={() => startRun(report)}
              >
                Run now
              </Button>
            </>
          }
        />

        <Card className="overflow-hidden">
          {runs.isLoading ? (
            <TableSkeleton cols={5} />
          ) : !runs.data?.length ? (
            <EmptyState icon="clock" title="No runs yet" />
          ) : (
            <div className={TABLE.wrap}>
              <table className={TABLE.table}>
                <thead>
                  <tr className={TABLE.headRow}>
                    {["Run", "Status", "Queries", "Time", ""].map(
                      (head, index) => (
                        <th
                          key={index}
                          className={
                            index > 1 && index < 4 ? TABLE.thNumeric : TABLE.th
                          }
                        >
                          {head}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {runs.data.map((entry) => {
                    const progress = entry.progress;
                    // The worker can leave `status` at "pending" once every
                    // query has landed, so read the progress counters too.
                    const status = effectiveRunStatus(entry.status, progress);
                    return (
                      <tr key={entry.run_id} className={TABLE.row}>
                        {/* created_at, not started_at: the backend re-derives
                            started_at on refresh and leaves it null until the
                            worker picks the run up. */}
                        <td className={cn(TABLE.td, "text-xs")}>
                          {absT(entry.started_at ?? entry.created_at)}
                        </td>
                        <td className={TABLE.td}>
                          <Chip tone={STATUS_TONE[status] ?? "slate"} size="sm">
                            {status}
                          </Chip>
                        </td>
                        <td className={TABLE.tdNumeric}>
                          {nfmt(progress?.total_queries ?? 0)}
                          {progress?.failed_queries
                            ? ` · ${progress.failed_queries} failed`
                            : ""}
                        </td>
                        <td className={TABLE.tdNumeric}>
                          {entry.total_time_ms == null
                            ? "—"
                            : ms(entry.total_time_ms)}
                        </td>
                        <td className={TABLE.td}>
                          <Button
                            variant="link"
                            size="sm"
                            className="font-semibold"
                            onClick={() => {
                              setRunId(entry.run_id);
                              setPage("run");
                            }}
                          >
                            View results →
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </>
    );
  }

  // ── run results ───────────────────────────────────────────────────────────
  if (page === "run" && report) {
    // GET …/runs/{run_id} nests every answer under query_groups[].results[] —
    // there is no flat `results` array on the response.
    const groups = run.data?.query_groups ?? [];
    const summary = run.data?.summary;
    const progress = runStatus.data?.progress;
    const status = run.data
      ? effectiveRunStatus(run.data.status, progress)
      : (runStatus.data?.status ?? "pending");

    const stats: Array<[string, string]> = summary
      ? [
          ["Queries", nfmt(summary.total_queries)],
          ["Completed", nfmt(summary.completed_queries)],
          ["Failed", nfmt(summary.failed_queries)],
          ["Avg response", ms(summary.avg_response_time_ms)],
          ["Tokens", nfmt(summary.total_tokens)],
          ["Total time", ms(summary.total_time_ms)],
        ]
      : [];

    return (
      <>
        <button
          type="button"
          onClick={() => setPage("detail")}
          className="mb-4 inline-flex cursor-pointer items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-indigo-600"
        >
          <Icon name="back" className="size-4" /> Run history
        </button>
        <PageHeader
          title={report.name}
          subtitle={`Run · ${absT(run.data?.started_at ?? run.data?.executed_at)}`}
          action={
            <Chip tone={STATUS_TONE[status] ?? "slate"} size="sm">
              {status}
            </Chip>
          }
        />

        {!runFinished ? (
          <Card>
            <EmptyState
              icon="clock"
              title="This run is still going"
              note={
                progress
                  ? `${progress.completed_queries + progress.failed_queries} of ${progress.total_queries} queries done — results appear as soon as it finishes.`
                  : "Results appear as soon as it finishes."
              }
            />
          </Card>
        ) : run.isLoading ? (
          <Card>
            <TableSkeleton cols={4} />
          </Card>
        ) : run.error ? (
          <Card>
            <CardBody className="text-sm text-slate-600">
              {friendlyApiMessage(
                run.error,
                "This run could not be loaded. It may still be starting.",
              )}
            </CardBody>
          </Card>
        ) : (
          <>
            {stats.length > 0 && (
              <Card className="mb-4">
                <CardBody className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                  {stats.map(([label, value]) => (
                    <div key={label}>
                      <p className="text-xs text-slate-500">{label}</p>
                      <p className="text-base font-semibold text-slate-900">
                        {value}
                      </p>
                    </div>
                  ))}
                </CardBody>
              </Card>
            )}

            {run.data?.failure_reason && (
              <Card className="mb-4">
                <CardBody className="text-sm text-rose-700">
                  {run.data.failure_reason}
                </CardBody>
              </Card>
            )}

            {run.data?.overall_summary && (
              <Card className="mb-4">
                <CardHeader title="Overall analysis" />
                <CardBody className="text-sm text-slate-700">
                  {markdown(run.data.overall_summary)}
                </CardBody>
              </Card>
            )}

            {groups.length ? (
              groups.map((group, index) => (
                <GroupSection
                  key={group.group_id ?? index}
                  group={group}
                  index={index}
                />
              ))
            ) : (
              <Card>
                <EmptyState
                  icon="clock"
                  title="This run has no results"
                  note="The run finished without recording any query results."
                />
              </Card>
            )}
          </>
        )}
      </>
    );
  }

  return null;
}
