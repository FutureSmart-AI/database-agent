import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sanitizeSvg, useRecoveredImage } from "../remoteImage";

/** The first default launcher icon, as the bucket stores it. */
const svgBytes =
  '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2z"/></svg>';
const iconUrl =
  "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_bot/widget_icon.svg";

function Probe({ url }: { url?: string }) {
  const { src, markup, failed, onError } = useRecoveredImage(url);
  if (failed) return <span data-testid="fallback">fallback</span>;
  if (markup)
    return (
      <span data-testid="inline" dangerouslySetInnerHTML={{ __html: markup }} />
    );
  return <img data-testid="img" alt="" src={src} onError={onError} />;
}

/** The blob the hook hands to `<img>`, so the sniffed type can be asserted. */
let lastBlob: Blob | undefined;

beforeEach(() => {
  lastBlob = undefined;
  vi.stubGlobal("URL", {
    ...global.URL,
    createObjectURL: (blob: Blob) => {
      lastBlob = blob;
      return "blob:recovered";
    },
    revokeObjectURL: () => {},
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** An `<img>` that the browser refused to paint. */
const fireError = async (img: HTMLElement) => {
  await act(async () => {
    img.dispatchEvent(new Event("error"));
  });
};

describe("useRecoveredImage", () => {
  it("serves the URL as-is until the browser refuses it", () => {
    render(<Probe url={iconUrl} />);
    expect(screen.getByTestId("img")).toHaveAttribute("src", iconUrl);
  });

  it("inlines a mislabelled SVG so currentColor can resolve", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(svgBytes, {
          headers: { "Content-Type": "binary/octet-stream" },
        }),
      ),
    );

    render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));

    const svg = screen.getByTestId("inline").querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("stroke", "currentColor");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    // Sized by the caller's classes, not by the file.
    expect(svg?.hasAttribute("width")).toBe(false);
  });

  it("sniffs a mislabelled PNG from its magic bytes and blobs it", async () => {
    const png = new Uint8Array([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2,
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(png)));

    render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));

    expect(screen.getByTestId("img")).toHaveAttribute("src", "blob:recovered");
    expect(lastBlob?.type).toBe("image/png");
  });

  it("gives up when the bytes are not an image", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope")));

    render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));

    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("gives up when the fetch itself fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("CORS")));

    render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));

    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("gives up when the recovered blob is also refused", async () => {
    const png = new Uint8Array([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2,
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(png)));

    render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));
    await fireError(screen.getByTestId("img"));

    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("fetches once per URL and starts over when the URL changes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(svgBytes));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<Probe url={iconUrl} />);
    await fireError(screen.getByTestId("img"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender(<Probe url={`${iconUrl}?v=2`} />);
    expect(screen.getByTestId("img")).toHaveAttribute("src", `${iconUrl}?v=2`);
  });
});

describe("sanitizeSvg", () => {
  const parse = (markup: string) => {
    const sanitized = sanitizeSvg(markup);
    expect(sanitized).toBeDefined();
    return new DOMParser().parseFromString(sanitized!, "image/svg+xml")
      .documentElement;
  };

  it("keeps the drawing instructions", () => {
    const root = parse(svgBytes);
    expect(root.querySelector("path")).not.toBeNull();
    expect(root.getAttribute("fill")).toBe("none");
  });

  it("accepts an XML prolog and a comment before the root", () => {
    expect(
      sanitizeSvg(
        `<?xml version="1.0" encoding="iso-8859-1"?>\r\n<!-- Uploaded -->\n${svgBytes}`,
      ),
    ).toContain("<path");
  });

  it("drops script, style and event handlers", () => {
    const root = parse(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" onload="alert(1)">' +
        "<script>alert(2)</script><style>@import url(http://x/y.css);</style>" +
        '<rect width="8" height="8" onclick="alert(3)"/></svg>',
    );
    expect(root.querySelector("script")).toBeNull();
    expect(root.querySelector("style")).toBeNull();
    expect(root.hasAttribute("onload")).toBe(false);
    expect(root.querySelector("rect")?.hasAttribute("onclick")).toBe(false);
  });

  it("drops off-document references and javascript: URLs", () => {
    const root = parse(
      '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 8 8">' +
        '<use xlink:href="http://evil/x.svg#a"/><use href="#local"/>' +
        '<path d="M0 0" style="fill:url(http://evil/y)"/></svg>',
    );
    const uses = root.querySelectorAll("use");
    expect(uses[0].getAttributeNS("http://www.w3.org/1999/xlink", "href")).toBe(
      null,
    );
    expect(uses[1].getAttribute("href")).toBe("#local");
    expect(root.querySelector("path")?.hasAttribute("style")).toBe(false);
  });

  it("synthesises a viewBox when the file has none", () => {
    const root = parse(
      '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="32"><path d="M0 0"/></svg>',
    );
    expect(root.getAttribute("viewBox")).toBe("0 0 48 32");
  });

  it("rejects anything that is not SVG", () => {
    expect(sanitizeSvg("<html><body>hi</body></html>")).toBeUndefined();
    expect(sanitizeSvg("<svg><unclosed>")).toBeUndefined();
  });
});
