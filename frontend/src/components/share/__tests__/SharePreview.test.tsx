import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WidgetAppearance } from "@/data/widgetSettings";

import SharePreview from "../SharePreview";

const iconUrl =
  "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_1/widget_icon.svg";
const svgBytes =
  '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor"><path d="M0 0"/></svg>';

const appearance = (extra: Partial<WidgetAppearance> = {}): WidgetAppearance =>
  ({
    heading: "Sales data",
    sub: "Ask anything",
    greet: "Hello!",
    color: "#3a5fe3",
    show_sources: false,
    icon: 0,
    avatar: 0,
    ...extra,
  }) as WidgetAppearance;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(svgBytes)));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The `<img>` the launcher starts with, before the browser refuses it. */
const launcherImage = () =>
  document.querySelector<HTMLImageElement>(`img[src="${iconUrl}"]`);

describe("SharePreview launcher icon", () => {
  it("inlines the stored icon when the browser refuses it", async () => {
    render(
      <SharePreview
        appearance={appearance({ widget_icon: iconUrl })}
        mode="bubble"
      />,
    );
    expect(launcherImage()).not.toBeNull();

    await act(async () => {
      launcherImage()!.dispatchEvent(new Event("error"));
    });

    const inlined = document.querySelector('span[aria-hidden="true"] > svg');
    expect(inlined).not.toBeNull();
    // Inline, so the glyph takes its colour from the launcher it sits in.
    expect(inlined).toHaveAttribute("stroke", "currentColor");
  });

  it("falls back to the preset glyph when the asset cannot be recovered", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(
      <SharePreview
        appearance={appearance({ widget_icon: iconUrl })}
        mode="bubble"
      />,
    );

    await act(async () => {
      launcherImage()!.dispatchEvent(new Event("error"));
    });

    expect(launcherImage()).toBeNull();
    // The preset stands in — the launcher row still renders its caption.
    expect(screen.getByText(/Launcher, bottom-right/)).toBeInTheDocument();
  });
});
