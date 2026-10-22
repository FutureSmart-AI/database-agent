import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import { useAgentStatistics } from "../statistics";

vi.mock("@/platform/utils/axios", () => ({ default: { get: vi.fn() } }));

const mockedGet = vi.mocked(axios.get);

const AGENT = "NL2SQL_C0977A77";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function read() {
  const { result } = renderHook(() => useAgentStatistics(AGENT), { wrapper });
  await waitFor(() => expect(result.current.isPending).toBe(false));
  return result;
}

describe("useAgentStatistics", () => {
  beforeEach(() => vi.clearAllMocks());

  it("converts the service's seconds into milliseconds", async () => {
    mockedGet.mockResolvedValue({
      data: {
        data: {
          total_requests: 56,
          avg_gpt_response_time: 11.091689139604568,
          avg_db_fetch_time: 0.0025043742997305734,
          total_tokens_consumed: 7088,
          user_request_counts: [],
        },
      },
    });

    const result = await read();
    expect(result.current.data?.model_ms).toBeCloseTo(11_091.69, 1);
    expect(result.current.data?.db_ms).toBeCloseTo(2.5, 1);
    expect(result.current.data?.requests).toBe(56);
    expect(result.current.data?.tokens).toBe(7088);
  });

  // An unrecorded metric used to be flattened to 0, which printed "0ms" and
  // "0 tokens" over questions that certainly spent both.
  it("keeps an unrecorded metric null instead of zeroing it", async () => {
    mockedGet.mockResolvedValue({
      data: {
        data: {
          total_requests: 0,
          avg_gpt_response_time: null,
          avg_db_fetch_time: null,
          total_tokens_consumed: null,
          user_request_counts: [],
        },
      },
    });

    const result = await read();
    expect(result.current.data?.model_ms).toBeNull();
    expect(result.current.data?.db_ms).toBeNull();
    expect(result.current.data?.tokens).toBeNull();
    expect(result.current.data?.requests).toBe(0);
  });

  it("preserves a measured zero", async () => {
    mockedGet.mockResolvedValue({
      data: {
        data: {
          total_requests: 56,
          avg_gpt_response_time: 0,
          avg_db_fetch_time: 0,
          total_tokens_consumed: 0,
          user_request_counts: [],
        },
      },
    });

    const result = await read();
    expect(result.current.data?.model_ms).toBe(0);
    expect(result.current.data?.tokens).toBe(0);
  });

  it("maps an anonymous asker to a null user", async () => {
    mockedGet.mockResolvedValue({
      data: {
        data: {
          total_requests: 5,
          total_tokens_consumed: 7088,
          user_request_counts: [
            { user_id: "someone@futuresmart.ai", request_count: 1 },
            { user_id: null, request_count: 4 },
          ],
        },
      },
    });

    const result = await read();
    expect(result.current.data?.users).toEqual([
      { user: "someone@futuresmart.ai", requests: 1 },
      { user: null, requests: 4 },
    ]);
  });

  // The route answers 200 with `status: false` when it fails, which would
  // otherwise render as a page of confident zeros.
  it("treats a failure reported inside a 200 as an error", async () => {
    mockedGet.mockResolvedValue({
      data: { message: "Error in get_bot_statistics", status: false },
    });

    const result = await read();
    expect(result.current.isError).toBe(true);
    expect((result.current.error as Error).message).toBe(
      "Error in get_bot_statistics",
    );
  });
});
