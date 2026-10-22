"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import type { AgentAppearance } from "./types";

interface WidgetSettingsWire {
  heading?: string;
  sub_heading?: string;
  greet_message?: string;
  color?: string;
  show_sources?: boolean;
  widget_icon?: string;
  widget_avatar?: string;
}

export interface WidgetAppearance extends AgentAppearance {
  widget_icon?: string;
  widget_avatar?: string;
  /**
   * An uploaded launcher icon / chat avatar, sent as a file rather than a URL.
   * The service takes the file over `…_url` when both are present, so these are
   * only set while a picked file is still unsaved.
   */
  widget_icon_file?: File;
  widget_avatar_file?: File;
}

/** The largest icon or avatar the service accepts — anything more is a 400. */
export const MAX_WIDGET_ASSET_BYTES = 2 * 1024 * 1024;

export function useWidgetSettings(agentId: string | undefined) {
  const client = useQueryClient();
  const url = () =>
    buildApiUrl(APIS.NL2SQL_WIDGET_SETTINGS, { agent_id: agentId as string });
  const settings = useQuery({
    queryKey: ["widget-settings", agentId],
    enabled: Boolean(agentId),
    queryFn: async () =>
      (await axios.get<{ widget_settings?: WidgetSettingsWire }>(url())).data
        .widget_settings,
  });
  const icons = useQuery({
    queryKey: ["widget-icons"],
    queryFn: async () =>
      (
        await axios.get<{ widget_icons?: Array<{ url: string }> }>(
          APIS.NL2SQL_WIDGET_ICONS,
        )
      ).data.widget_icons ?? [],
  });
  const avatars = useQuery({
    queryKey: ["widget-avatars"],
    queryFn: async () =>
      (
        await axios.get<{ widget_avatars?: Array<{ url: string }> }>(
          APIS.NL2SQL_WIDGET_AVATARS,
        )
      ).data.widget_avatars ?? [],
  });
  const save = useMutation({
    mutationFn: async (appearance: WidgetAppearance) => {
      const form = new FormData();
      form.append("heading", appearance.heading);
      form.append("sub_heading", appearance.sub);
      form.append("greet_message", appearance.greet);
      form.append("color", appearance.color);
      form.append("show_sources", String(appearance.show_sources));
      // A picked file wins over the chosen default's URL — the service applies
      // the same precedence, so sending both would be ambiguous.
      if (appearance.widget_icon_file)
        form.append("widget_icon", appearance.widget_icon_file);
      else if (appearance.widget_icon)
        form.append("widget_icon_url", appearance.widget_icon);
      if (appearance.widget_avatar_file)
        form.append("widget_avatar", appearance.widget_avatar_file);
      else if (appearance.widget_avatar)
        form.append("widget_avatar_url", appearance.widget_avatar);
      // The content type is not optional, and not a formality.
      //
      // This axios instance defaults every request to `application/json`, and
      // axios turns a `FormData` body into a JSON string whenever the declared
      // content type is JSON (`transformRequest`). This endpoint takes form
      // fields only: it answered a JSON body with `200 {"message": "Added
      // widget settings successfully"}` and stored none of it, so every save
      // reported success while the appearance stayed at the defaults. Naming
      // the type here keeps the body multipart; the browser fills in the
      // boundary.
      await axios.post(url(), form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["widget-settings", agentId] }),
  });
  const reset = useMutation({
    mutationFn: async () => axios.delete(url()),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["widget-settings", agentId] }),
  });
  return { settings, icons, avatars, save, reset };
}
