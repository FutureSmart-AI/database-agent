"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isEffectivelyDone } from "@/platform/components/batch-reports/runStatus";
import type {
  CreateReportRequest,
  CreateReportResponse,
  ExportFormat,
  MessageResponse,
  QueryGroupInput,
  ReportSummary,
  RunListItem,
  RunResult,
  RunStatus,
  RunStatusResponse,
  ScheduleInput,
  UpdateReportRequest,
} from "@/platform/types/batch-reports";
import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Batch query reports, from the NL2SQL service's own routes:
 *
 * - `GET|POST   /nl2sql/api/v1/agents/{agent_id}/reports`
 * - `GET|PUT    /nl2sql/api/v1/agents/{agent_id}/reports/settings`
 * - `GET|PUT|DELETE …/reports/{report_id}`
 * - `GET|POST   …/reports/{report_id}/runs`
 * - `GET        …/runs/{run_id}` · `…/status` · `…/export?format=`
 * - `POST       …/runs/{run_id}/cancel`
 *
 * Not the dashboard service (`/api/dashboard/v1/reports?agent_id=`): those
 * routes are keyed by chat-registry ids and reject an `NL2SQL_…` agent, which is
 * why this page used to show "reports are not available for this agent yet".
 * The NL2SQL routes take the agent in the path and carry no `agent_id` query
 * param, so the wire shapes are shared with the root app but the URLs are not.
 *
 * The wire shapes stay in `@/platform/types/batch-reports` — a hand-copied shape is
 * exactly how the run page came to read `results` and `overall_analysis`,
 * neither of which the API has ever sent. Only the fields that genuinely differ
 * from the dashboard service are restated below.
 */

export type GroupType = QueryGroupInput["type"];
export type ReportSchedule = ScheduleInput;
export type QueryGroup = QueryGroupInput;

/**
 * `ReportResponse` on the NL2SQL service: `user_id` and `query_groups` are
 * nullable, and it also reports the next scheduled fire time.
 */
export type Report = Omit<ReportSummary, "user_id" | "query_groups"> & {
  user_id?: string | null;
  query_groups?: QueryGroupInput[] | null;
  next_run_at?: string | null;
};

export type ReportRun = RunListItem;
export type { RunResult, RunStatusResponse };

/** `RunCreatedResponse` / `CancelRunResponse` — no `message`, status may be null. */
type RunActionResponse = {
  run_id: string;
  status?: RunStatus | null;
};

/** `ReportSettingsResponse` — the PUT echoes it too, so there is no `message`. */
export type ReportSettings = {
  max_queries_per_report: number;
  default_max_queries_per_report: number;
};

/** Matches the root dashboard's poll cadence for a live run. */
const RUN_POLL_INTERVAL_MS = 3000;

const reportsUrl = (agentId: string) =>
  buildApiUrl(APIS.REPORTS, { agent_id: agentId });

const reportUrl = (agentId: string, reportId: string) =>
  buildApiUrl(APIS.REPORT, { agent_id: agentId, report_id: reportId });

const runsUrl = (agentId: string, reportId: string) =>
  buildApiUrl(APIS.REPORT_RUNS, { agent_id: agentId, report_id: reportId });

/** The four run routes all take the same three path params. */
type RunTemplate =
  | typeof APIS.REPORT_RUN
  | typeof APIS.REPORT_RUN_STATUS
  | typeof APIS.REPORT_RUN_EXPORT
  | typeof APIS.REPORT_RUN_CANCEL;

const runUrl = (
  template: RunTemplate,
  agentId: string,
  reportId: string,
  runId: string,
) =>
  buildApiUrl(template, {
    agent_id: agentId,
    report_id: reportId,
    run_id: runId,
  });

export function useReports(agentId: string | undefined) {
  return useQuery({
    queryKey: ["reports", agentId],
    enabled: Boolean(agentId),
    queryFn: async (): Promise<Report[]> => {
      const response = await axios.get<{ reports?: Report[] }>(
        reportsUrl(agentId as string),
      );
      return response.data.reports ?? [];
    },
  });
}

/**
 * The per-agent cap on how many queries one report may hold, plus the system
 * default so nothing here hardcodes it. Owner-scoped on the dashboard service;
 * a caller without access just gets an error and the cap stays unknown.
 */
export function useReportSettings(agentId: string | undefined) {
  return useQuery({
    queryKey: ["report-settings", agentId],
    enabled: Boolean(agentId),
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<ReportSettings> => {
      const response = await axios.get<ReportSettings>(
        buildApiUrl(APIS.REPORT_SETTINGS, { agent_id: agentId as string }),
      );
      return response.data;
    },
  });
}

export function useRuns(agentId: string | undefined, reportId: string | null) {
  return useQuery({
    queryKey: ["report-runs", agentId, reportId],
    enabled: Boolean(agentId && reportId),
    queryFn: async (): Promise<ReportRun[]> => {
      const response = await axios.get<{ runs?: ReportRun[] }>(
        runsUrl(agentId as string, reportId as string),
      );
      return response.data.runs ?? [];
    },
    // Keep the history fresh while any run in it is still going.
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (run) => !isEffectivelyDone(run.status, run.progress),
      )
        ? RUN_POLL_INTERVAL_MS
        : false,
    refetchIntervalInBackground: true,
  });
}

/**
 * Poll one run's status. Stops once the run is terminal — or effectively done,
 * since the worker can leave `status` at "pending" after the last query lands.
 */
export function useRunStatus(
  agentId: string | undefined,
  reportId: string | null,
  runId: string | null,
) {
  return useQuery({
    queryKey: ["report-run-status", agentId, reportId, runId],
    enabled: Boolean(agentId && reportId && runId),
    queryFn: async (): Promise<RunStatusResponse> => {
      const response = await axios.get<RunStatusResponse>(
        runUrl(
          APIS.REPORT_RUN_STATUS,
          agentId as string,
          reportId as string,
          runId as string,
        ),
      );
      return response.data;
    },
    refetchInterval: (query) =>
      isEffectivelyDone(query.state.data?.status, query.state.data?.progress)
        ? false
        : RUN_POLL_INTERVAL_MS,
    refetchIntervalInBackground: true,
  });
}

/**
 * The full result of a run. `enabled` gates it on the run being finished — a
 * run still in flight has no `query_groups` to show.
 */
export function useRun(
  agentId: string | undefined,
  reportId: string | null,
  runId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ["report-run", agentId, reportId, runId],
    enabled: enabled && Boolean(agentId && reportId && runId),
    queryFn: async (): Promise<RunResult> => {
      const response = await axios.get<RunResult>(
        runUrl(
          APIS.REPORT_RUN,
          agentId as string,
          reportId as string,
          runId as string,
        ),
      );
      return response.data;
    },
  });
}

export function useReportMutations(agentId: string | undefined) {
  const client = useQueryClient();
  const invalidate = () => {
    client.invalidateQueries({ queryKey: ["reports", agentId] });
    client.invalidateQueries({ queryKey: ["report-runs", agentId] });
  };

  const create = useMutation({
    mutationFn: async (
      payload: CreateReportRequest,
    ): Promise<CreateReportResponse> => {
      const response = await axios.post<CreateReportResponse>(
        reportsUrl(agentId as string),
        payload,
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: async ({
      reportId,
      payload,
    }: {
      reportId: string;
      payload: UpdateReportRequest;
    }): Promise<MessageResponse> => {
      const response = await axios.put<MessageResponse>(
        reportUrl(agentId as string, reportId),
        payload,
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: async (reportId: string): Promise<MessageResponse> => {
      const response = await axios.delete<MessageResponse>(
        reportUrl(agentId as string, reportId),
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const run = useMutation({
    mutationFn: async (reportId: string): Promise<RunActionResponse> => {
      // 202 — the run always starts "pending"; poll `useRunStatus` from there.
      const response = await axios.post<RunActionResponse>(
        runsUrl(agentId as string, reportId),
        undefined,
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: async ({
      reportId,
      runId,
    }: {
      reportId: string;
      runId: string;
    }): Promise<RunActionResponse> => {
      const response = await axios.post<RunActionResponse>(
        runUrl(APIS.REPORT_RUN_CANCEL, agentId as string, reportId, runId),
        undefined,
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  /** The run's results as a downloadable file — json, md or csv. */
  const exportRun = useMutation({
    mutationFn: async ({
      reportId,
      runId,
      format = "csv",
    }: {
      reportId: string;
      runId: string;
      format?: ExportFormat;
    }): Promise<Blob> => {
      const response = await axios.get<Blob>(
        runUrl(APIS.REPORT_RUN_EXPORT, agentId as string, reportId, runId),
        { params: { format }, responseType: "blob" },
      );
      return response.data;
    },
  });

  /** PUT echoes the settings back, so the cache is set from the response. */
  const setMaxQueries = useMutation({
    mutationFn: async (
      maxQueriesPerReport: number,
    ): Promise<ReportSettings> => {
      const response = await axios.put<ReportSettings>(
        buildApiUrl(APIS.REPORT_SETTINGS, { agent_id: agentId as string }),
        { max_queries_per_report: maxQueriesPerReport },
      );
      return response.data;
    },
    onSuccess: (settings) =>
      client.setQueryData(["report-settings", agentId], settings),
  });

  return { create, update, remove, run, cancel, exportRun, setMaxQueries };
}
