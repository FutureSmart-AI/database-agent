"use client";

import type { ReactNode } from "react";

import { useRecoveredImage } from "@/lib/remoteImage";
import { cn } from "@/platform/utils";

/**
 * A stored icon or avatar, painted whichever way the asset allows.
 *
 * `useRecoveredImage` hands back either a URL for an `<img>` or sanitised SVG
 * markup to inline; the inline route is what lets an icon that strokes with
 * `currentColor` take the colour of whatever it sits in. `fallback` is drawn
 * only when neither route works.
 */
export default function RemoteAsset({
  url,
  className,
  fallback,
}: {
  url?: string;
  className: string;
  fallback: ReactNode;
}) {
  const { src, markup, failed, onError } = useRecoveredImage(url);

  if (failed || (!src && !markup)) return <>{fallback}</>;

  if (markup)
    return (
      <span
        aria-hidden
        className={cn(
          "inline-flex items-center justify-center [&>svg]:size-full",
          className,
        )}
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    );

  return <img src={src} alt="" className={className} onError={onError} />;
}
