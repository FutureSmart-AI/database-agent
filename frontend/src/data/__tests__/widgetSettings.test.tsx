import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import { useWidgetSettings, type WidgetAppearance } from "../widgetSettings";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const mockedPost = vi.mocked(axios.post);
const mockedGet = vi.mocked(axios.get);

const AGENT = "NL2SQL_E5DC283F";

const appearance = (extra: Partial<WidgetAppearance> = {}): WidgetAppearance =>
  ({
    heading: "Sales data",
    sub: "Ask anything",
    greet: "Hello!",
    color: "#3a5fe3",
    show_sources: true,
    icon: 0,
    avatar: 0,
    ...extra,
  }) as WidgetAppearance;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function save(draft: WidgetAppearance) {
  const { result } = renderHook(() => useWidgetSettings(AGENT), { wrapper });
  await result.current.save.mutateAsync(draft);
  await waitFor(() => expect(mockedPost).toHaveBeenCalled());
  const [url, body, config] = mockedPost.mock.calls[0] as [
    string,
    FormData,
    { headers?: Record<string, string> },
  ];
  return { url, body, config };
}

describe("useWidgetSettings — save", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGet.mockResolvedValue({ data: { widget_settings: {} } });
    mockedPost.mockResolvedValue({ data: {} });
  });

  // This axios instance defaults to `application/json`, and axios serialises a
  // FormData body to JSON when that is the declared content type. The service
  // takes form fields only: it answers a JSON body 200 "Added widget settings
  // successfully" and stores none of it, so every save reported success while
  // the appearance stayed at the defaults.
  it("posts multipart, never JSON", async () => {
    const { url, body, config } = await save(appearance());

    expect(url).toBe(`/nl2sql/api/v1/agents/${AGENT}/widget/settings`);
    expect(config.headers?.["Content-Type"]).toBe("multipart/form-data");
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("heading")).toBe("Sales data");
    expect(body.get("color")).toBe("#3a5fe3");
    expect(body.get("show_sources")).toBe("true");
  });

  it("sends the chosen default as a URL", async () => {
    const { body } = await save(
      appearance({ widget_icon: "https://cdn/icon.svg" }),
    );

    expect(body.get("widget_icon_url")).toBe("https://cdn/icon.svg");
    expect(body.get("widget_icon")).toBeNull();
  });

  // The service applies the file over the URL, so sending both would leave the
  // outcome to the backend rather than to what was picked last.
  it("sends an uploaded file instead of the URL", async () => {
    const file = new File(["<svg />"], "logo.svg", { type: "image/svg+xml" });
    const { body } = await save(
      appearance({
        widget_icon: "https://cdn/icon.svg",
        widget_icon_file: file,
      }),
    );

    expect(body.get("widget_icon")).toBe(file);
    expect(body.get("widget_icon_url")).toBeNull();
  });
});
