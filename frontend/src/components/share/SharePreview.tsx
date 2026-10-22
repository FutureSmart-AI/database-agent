"use client";

import { useEffect, useState } from "react";

import Icon, { type IconName } from "@/components/Icon";
import type { WidgetAppearance } from "@/data/widgetSettings";

import RemoteAsset from "./RemoteAsset";

/** Launcher/avatar icon presets. */
export const PRESET_ICONS: IconName[] = [
  "chat",
  "db",
  "spark",
  "bolt",
  "users",
  "cloud",
];

/**
 * The chosen launcher icon or chat avatar, as the widget will render it.
 *
 * The picked image is what the widget shows, so the preview draws that rather
 * than a preset glyph. A file picked but not yet saved has no URL yet, hence
 * the object URL; a stored asset goes through `RemoteAsset` because the bucket
 * mislabels the default SVGs (see `SwatchImage` in `ShareView`), and only when
 * neither route paints does the preset glyph stand in.
 */
function PreviewImage({
  url,
  file,
  preset,
  className,
}: {
  url?: string;
  file?: File;
  preset: IconName;
  className: string;
}) {
  const [fileFailed, setFileFailed] = useState(false);
  const [fileUrl, setFileUrl] = useState<string>();
  useEffect(() => {
    setFileFailed(false);
    if (!file) {
      setFileUrl(undefined);
      return () => undefined;
    }
    const objectUrl = URL.createObjectURL(file);
    setFileUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  const presetGlyph = <Icon name={preset} className={className} />;

  if (file)
    return fileUrl && !fileFailed ? (
      <img
        src={fileUrl}
        alt=""
        className={`${className} object-contain`}
        onError={() => setFileFailed(true)}
      />
    ) : (
      presetGlyph
    );

  return (
    <RemoteAsset
      url={url}
      className={`${className} object-contain`}
      fallback={presetGlyph}
    />
  );
}

interface SharePreviewProps {
  appearance: WidgetAppearance;
  mode: "bubble" | "full";
}

/**
 * Live preview of the shared chat — the same surface the widget and the
 * full-page link render, so appearance changes can be judged without deploying.
 *
 * The brand colour is applied inline: it is user data, not a design token.
 */
export default function SharePreview({ appearance, mode }: SharePreviewProps) {
  const color = appearance.color;

  return (
    <div className="space-y-3">
      <div
        className={`overflow-hidden rounded-xl border border-gray-200 shadow-sm ${
          mode === "full" ? "" : "mx-auto max-w-xs"
        }`}
      >
        <div
          className="flex items-center gap-2 px-3 py-2.5 text-white"
          style={{ background: color }}
        >
          <span className="flex size-7 items-center justify-center overflow-hidden rounded-full bg-white/20">
            <PreviewImage
              url={appearance.widget_avatar}
              file={appearance.widget_avatar_file}
              preset={PRESET_ICONS[appearance.avatar] ?? "chat"}
              className="size-4"
            />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold">
              {appearance.heading || "Untitled"}
            </span>
            <span className="block truncate text-[11px] opacity-80">
              {appearance.sub}
            </span>
          </span>
          <Icon name="ref" className="ml-auto size-3.5 opacity-85" />
        </div>

        <div
          className={`space-y-2 bg-slate-50 p-3 ${mode === "full" ? "min-h-72" : "min-h-40"}`}
        >
          <div className="w-fit max-w-[85%] rounded-2xl rounded-tl-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
            {appearance.greet}
          </div>
          <div
            className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-tr-md px-3 py-2 text-xs text-white"
            style={{ background: color }}
          >
            Show products with stock quantity less than 10
          </div>
          <div className="w-fit max-w-[85%] rounded-2xl rounded-tl-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
            <b>7 products are below 10 units.</b> Two are already at zero.
            {appearance.show_sources && (
              <div className="mt-2 flex items-center gap-1 text-[11px] text-indigo-600">
                <Icon name="code" className="size-3" />
                View the SQL behind this answer
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 border-t border-gray-100 bg-white px-3 py-2">
          <span className="flex-1 rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-400">
            Type your message…
          </span>
          <span
            className="flex size-7 items-center justify-center rounded-full text-white"
            style={{ background: color }}
          >
            <Icon name="send" className="size-3.5" />
          </span>
        </div>
        <div className="border-t border-gray-100 bg-white py-1.5 text-center text-[10px] text-slate-400">
          Agent powered by <b className="text-indigo-600">FutureSmart AI</b>
        </div>
      </div>

      {mode === "bubble" && (
        <div className="flex items-center justify-center gap-2">
          <span
            className="flex size-10 items-center justify-center overflow-hidden rounded-full text-white shadow-lg"
            style={{ background: color }}
          >
            <PreviewImage
              url={appearance.widget_icon}
              file={appearance.widget_icon_file}
              preset={PRESET_ICONS[appearance.icon] ?? "chat"}
              className="size-5"
            />
          </span>
          <span className="text-xs text-slate-400">
            Launcher, bottom-right of your page
          </span>
        </div>
      )}

      <p className="text-center text-[11px] text-slate-400">
        Live preview — every change above shows here immediately.
      </p>
    </div>
  );
}
