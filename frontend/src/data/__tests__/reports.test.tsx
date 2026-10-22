import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import {
  useReportMutations,
  useReports,
  useReportSettings,
  useRun,
  useRuns,
  useRunStatus,
} from "../reports";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const mockedGet = vi.mocked(axios.get);
const mockedPost = vi.mocked(axios.post);
const mockedPut = vi.mocked(axios.put);
const mockedDelete = vi.mocked(axios.delete);

const AGENT = "NL2SQL_E5DC283F";
const REPORT = "rep_123";
const RUN = "run_456";
const BASE = `/nl2sql/api/v1/agents/${AGENT}/reports`;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const mutations = () =>
  renderHook(() => useReportMutations(AGENT), { wrapper }).result;

describe("reports data layer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGet.mockResolvedValue({ data: {} });
    mockedPost.mockResolvedValue({ data: { run_id: RUN, status: "pending" } });
    mockedPut.mockResolvedValue({ data: { message: "ok" } });
    mockedDelete.mockResolvedValue({ data: { message: "ok" } });
  });

  // The dashboard service takes `?agent_id=`; the NL2SQL service puts the agent
  // in the path and rejects the dashboard shape, so the URL is the whole fix.
  it("reads the list from the NL2SQL agent-scoped path with no agent_id param", async () => {
    const { result } = renderHook(() => useReports(AGENT), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedGet).toHaveBeenCalledWith(BASE);
  });

  it("reads settings, runs, run status and one run from NL2SQL paths", async () => {
    renderHook(() => useReportSettings(AGENT), { wrapper });
    renderHook(() => useRuns(AGENT, REPORT), { wrapper });
    renderHook(() => useRunStatus(AGENT, REPORT, RUN), { wrapper });
    renderHook(() => useRun(AGENT, REPORT, RUN), { wrapper });

    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(4));

    const urls = mockedGet.mock.calls.map(([url]) => url);
    expect(urls).toContain(`${BASE}/settings`);
    expect(urls).toContain(`${BASE}/${REPORT}/runs`);
    expect(urls).toContain(`${BASE}/${REPORT}/runs/${RUN}/status`);
    expect(urls).toContain(`${BASE}/${REPORT}/runs/${RUN}`);
  });

  it("creates, updates and deletes on the NL2SQL paths", async () => {
    const payload = {
      name: "Weekly QA",
      query_groups: [{ type: "independent" as const, queries: ["how many?"] }],
    };
    mockedPost.mockResolvedValueOnce({ data: { report_id: REPORT } });

    const m = mutations();
    await m.current.create.mutateAsync(payload);
    await m.current.update.mutateAsync({
      reportId: REPORT,
      payload: { name: "Renamed" },
    });
    await m.current.remove.mutateAsync(REPORT);

    expect(mockedPost).toHaveBeenCalledWith(BASE, payload);
    expect(mockedPut).toHaveBeenCalledWith(`${BASE}/${REPORT}`, {
      name: "Renamed",
    });
    expect(mockedDelete).toHaveBeenCalledWith(`${BASE}/${REPORT}`);
  });

  it("starts and cancels a run, and returns the new run id", async () => {
    const m = mutations();
    const started = await m.current.run.mutateAsync(REPORT);
    await m.current.cancel.mutateAsync({ reportId: REPORT, runId: RUN });

    expect(started.run_id).toBe(RUN);
    expect(mockedPost).toHaveBeenCalledWith(
      `${BASE}/${REPORT}/runs`,
      undefined,
    );
    expect(mockedPost).toHaveBeenCalledWith(
      `${BASE}/${REPORT}/runs/${RUN}/cancel`,
      undefined,
    );
  });

  // `format` is the one query param the report routes take.
  it("exports a run as a blob with the requested format", async () => {
    mockedGet.mockResolvedValueOnce({ data: new Blob(["a,b"]) });

    await mutations().current.exportRun.mutateAsync({
      reportId: REPORT,
      runId: RUN,
      format: "md",
    });

    expect(mockedGet).toHaveBeenCalledWith(
      `${BASE}/${REPORT}/runs/${RUN}/export`,
      { params: { format: "md" }, responseType: "blob" },
    );
  });

  it("writes the settings PUT echo straight into the cache", async () => {
    mockedPut.mockResolvedValueOnce({
      data: { max_queries_per_report: 50, default_max_queries_per_report: 25 },
    });

    const result = await mutations().current.setMaxQueries.mutateAsync(50);

    expect(mockedPut).toHaveBeenCalledWith(`${BASE}/settings`, {
      max_queries_per_report: 50,
    });
    expect(result.max_queries_per_report).toBe(50);
  });
});
