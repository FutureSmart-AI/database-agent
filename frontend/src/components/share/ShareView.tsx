"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import { Card } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import CodeBlock from "@/components/ui/CodeBlock";
import EmptyState from "@/components/ui/EmptyState";
import Field from "@/components/ui/Field";
import PageHeader from "@/components/ui/PageHeader";
import TabNav from "@/components/ui/TabNav";
import { toShare, type Nl2sqlAgentParams } from "@/data/agents";
import { useApiKeyMutations, useApiKeys } from "@/data/keys";
import { useAgentMutations } from "@/data/mutations";
import { usePeople, usePeopleMutations } from "@/data/people";
import type { AgentShare } from "@/data/types";
import { useAgent, useAgentParams } from "@/data/useAgents";
import {
  MAX_WIDGET_ASSET_BYTES,
  useWidgetSettings,
  type WidgetAppearance,
} from "@/data/widgetSettings";
import { apiMessage } from "@/lib/apiError";
import { copyText } from "@/lib/clipboard";
import { agentRoute, publicHost, ROUTES } from "@/lib/routes";
import { useToast } from "@/platform/components/ToastContext";
import {
  Button,
  Checkbox,
  Input,
  Select,
  Switch,
} from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import {
  FEATURE_CHIPS,
  SHARE_ROWS,
  SWATCHES,
  type ShareRowKey,
} from "./constants";
import RemoteAsset from "./RemoteAsset";
import ShareActivity from "./ShareActivity";
import SharePreview from "./SharePreview";
import ShareRow, { ShareGroup } from "./ShareRow";

/** "18 Jun 2026" — keys carry a creation timestamp, not a relative age. */
const absT = (at: number) =>
  at
    ? new Date(at).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";

/**
 * A default icon or avatar from object storage.
 *
 * The bucket serves these SVGs as `binary/octet-stream`, which no browser will
 * paint in an `<img>`, so `RemoteAsset` re-fetches and inlines a refused asset.
 * If even that fails the swatch falls back to its position number, so the
 * picker still reads as a row of distinct choices.
 */
function SwatchImage({ url, label }: { url: string; label: string }) {
  return (
    <RemoteAsset
      url={url}
      className="size-5"
      fallback={<span className="text-[11px] font-medium">{label}</span>}
    />
  );
}

/**
 * Upload control for a launcher icon or chat avatar.
 *
 * The service answers 400 for anything that is not an image or is over 2 MB,
 * so both are checked before the file is taken — a pick that cannot work
 * should say so where it was made, not after a round trip.
 */
function AssetUpload({
  id,
  label,
  file,
  onPick,
  onClear,
  onReject,
}: {
  id: string;
  label: string;
  file?: File;
  onPick: (file: File) => void;
  onClear: () => void;
  onReject: (reason: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 pt-2">
      <input
        id={id}
        type="file"
        aria-label={label}
        accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif"
        className="max-w-full cursor-pointer text-xs text-slate-500 file:mr-2 file:cursor-pointer file:rounded-md file:border file:border-slate-200 file:bg-white file:px-2 file:py-1 file:text-xs file:font-medium file:text-slate-700 hover:file:bg-slate-50"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          event.target.value = "";
          if (!picked) return;
          if (!picked.type.startsWith("image/"))
            return onReject(`${picked.name} is not an image.`);
          if (picked.size > MAX_WIDGET_ASSET_BYTES)
            return onReject(`${picked.name} is over 2 MB.`);
          onPick(picked);
        }}
      />
      {file && (
        <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 py-0.5 pl-2 pr-1 text-xs text-slate-600">
          <span className="max-w-40 truncate">{file.name}</span>
          <button
            type="button"
            aria-label={`Remove ${file.name}`}
            className="cursor-pointer rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
            onClick={onClear}
          >
            <Icon name="x" className="size-3" />
          </button>
        </span>
      )}
    </div>
  );
}

type ApiLang = "py" | "js" | "curl";

interface ShareViewProps {
  agentId?: string;
}

/** Domain allowlist editor, shared by the widget and full-page cards. */
function Domains({
  domains,
  onAdd,
  onRemove,
}: {
  domains: string[];
  onAdd: (domain: string) => void;
  onRemove: (domain: string) => void;
}) {
  const [draft, setDraft] = useState("");
  return (
    <Field
      label="Allowed domains"
      hint={
        <>
          Leave empty to allow anywhere. <code>acme.com</code> for the apex,{" "}
          <code>*.acme.com</code> for subdomains.
        </>
      }
    >
      <div className="flex items-center gap-2">
        <Input
          className="flex-1"
          placeholder="e.g. acme.com"
          value={draft}
          aria-label="Domain to allow"
          onChange={setDraft}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            if (draft.trim()) onAdd(draft.trim());
            setDraft("");
          }}
        >
          Add
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-2">
        {domains.length ? (
          domains.map((domain) => (
            <span
              key={domain}
              className="inline-flex items-center gap-1 rounded-md bg-slate-100 py-0.5 pl-2 pr-1 font-mono text-xs text-slate-600"
            >
              {domain}
              <button
                type="button"
                aria-label={`Remove ${domain}`}
                className="cursor-pointer rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                onClick={() => onRemove(domain)}
              >
                <Icon name="x" className="size-3" />
              </button>
            </span>
          ))
        ) : (
          <span className="text-xs font-medium text-emerald-600">
            All domains allowed — it can be loaded on any website.
          </span>
        )}
      </div>
    </Field>
  );
}

/** "Enabled" label plus switch, as used in each share-channel card header. */
function EnabledToggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <span className="flex items-center gap-2">
      <span className="text-xs font-medium text-slate-500">Enabled</span>
      <Switch checked={checked} aria-label={label} onCheckedChange={onChange} />
    </span>
  );
}

export default function ShareView({ agentId }: ShareViewProps) {
  const router = useRouter();
  const { toast } = useToast();
  const { agent, isLoading: agentLoading } = useAgent(agentId);

  const keys = useApiKeys(agent?.agent_id);
  const peopleQuery = usePeople(agent?.agent_id, agent?.owner);
  const peopleMutations = usePeopleMutations(agent?.agent_id);
  const widgetSettings = useWidgetSettings(agent?.agent_id);
  const people = peopleQuery.data ?? [];
  const keyMutations = useApiKeyMutations(agent?.agent_id);
  const agentMutations = useAgentMutations(agent);

  /**
   * The stored share settings, which only the config route carries.
   *
   * `GET /agents` leaves `is_public`, `allowed_domains`,
   * `fullscreen_is_public` and `fullscreen_allowed_domains` out of the row
   * entirely, so seeding from `agent.share` alone showed every agent as "off,
   * all domains" no matter what had been saved.
   */
  const paramsQuery = useAgentParams(agent?.agent_id);

  const [appearance, setAppearance] = useState<WidgetAppearance>();
  const [share, setShare] = useState(agent?.share);

  // Seed the drafts once the agent resolves, and again if it changes.
  //
  // Depend on the parts, never on `agent` itself: the hook rebuilds that object
  // on every render while it attaches databases, so an `[agent]` dependency
  // re-seeded the drafts on every render — "Maximum update depth exceeded" the
  // moment this page opened.
  const agentAppearance = agent?.appearance;
  const agentShare = agent?.share;
  const settings = widgetSettings.settings.data;
  const seeded = useCallback(
    (): WidgetAppearance | undefined =>
      agentAppearance && {
        ...agentAppearance,
        ...(settings?.heading ? { heading: settings.heading } : {}),
        ...(settings?.sub_heading ? { sub: settings.sub_heading } : {}),
        ...(settings?.greet_message ? { greet: settings.greet_message } : {}),
        ...(settings?.color ? { color: settings.color } : {}),
        ...(settings?.show_sources !== undefined
          ? { show_sources: settings.show_sources }
          : {}),
        ...(settings?.widget_icon ? { widget_icon: settings.widget_icon } : {}),
        ...(settings?.widget_avatar
          ? { widget_avatar: settings.widget_avatar }
          : {}),
      },
    [agentAppearance, settings],
  );
  const storedParams = paramsQuery.data;
  useEffect(() => {
    if (!agentAppearance || !agentShare) return;
    setAppearance(seeded());
    // The config's share fields win over the agent row's, which never has them.
    setShare(storedParams ? toShare(storedParams) : agentShare);
  }, [agentAppearance, agentShare, seeded, storedParams]);
  const [invite, setInvite] = useState("");
  const [inviteRole, setInviteRole] = useState<"editor" | "viewer">("viewer");
  /** Keys shown in full, by key id — masked until asked for. */
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [lang, setLang] = useState<ApiLang>("py");
  const [mode, setMode] = useState<"bubble" | "full">("bubble");
  /**
   * Which disclosure rows are open. Every row starts closed so the whole screen
   * — all seven features — is readable without scrolling; opening one is how you
   * say which one you came for. Several may be open at once, deliberately:
   * copying an embed snippet while the preview is open is a real thing to do.
   */
  const [openRows, setOpenRows] = useState<ShareRowKey[]>([]);
  /**
   * Set up is what you change; Activity is what came back. They are two jobs on
   * one subject, so they are tabs rather than two screens: nobody navigates to
   * "the share settings page" to read what a customer asked last week.
   */
  const [tab, setTab] = useState<"setup" | "activity">("setup");
  const inviteRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  const isOpen = (row: ShareRowKey) => openRows.includes(row);
  const setOpen = (row: ShareRowKey, open: boolean) =>
    setOpenRows((current) =>
      open
        ? current.includes(row)
          ? current
          : [...current, row]
        : current.filter((key) => key !== row),
    );
  const toggle = (row: ShareRowKey) => (open: boolean) => setOpen(row, open);
  const allOpen = openRows.length === SHARE_ROWS.length;

  if (!agent || !share || !appearance) {
    return (
      <Card>
        <EmptyState
          icon={agentLoading ? "ref" : "warn"}
          title={agentLoading ? "Loading this agent…" : "No database agent"}
        />
      </Card>
    );
  }

  if (agent.demo) {
    return (
      <Card>
        <EmptyState
          icon="warn"
          title="This is a shared example agent"
          note="It cannot be shared from here. One agent serves every user, so only its owner can change it. Ask it questions from Conversations."
        />
      </Card>
    );
  }

  const host = publicHost();
  const shareUrl = `${host}/agent/${agent.agent_id}/?mode=fullscreen`;
  const copy = async (text: string, what: string) => {
    const copied = await copyText(text);
    toast[copied ? "success" : "error"](
      copied ? `${what} copied.` : `Could not copy the ${what.toLowerCase()}.`,
    );
  };

  /**
   * `POST …/api-keys` — issues a key, copies it, and shows it revealed in the
   * list below. Repeat calls are safe: the service returns the caller's existing
   * active key rather than a second one.
   */
  const generateKey = async () => {
    try {
      const { key, secret } = await keyMutations.create.mutateAsync();
      // The key list lives inside the row, and this button sits on the closed
      // header — so open it: a primary action must not produce a result its own
      // row is hiding.
      setOpen("api", true);
      setRevealed((current) => ({ ...current, [key.id]: true }));
      const copied = await copyText(secret);
      toast.success(
        `API key ready${copied ? " and copied" : ""} — it is listed below.`,
        { duration: 8000 },
      );
    } catch (error) {
      toast.error(`Could not create a key: ${apiMessage(error)}`);
    }
  };

  /**
   * `PATCH …/config/params` — one share setting, the moment it is changed.
   *
   * These four fields are `AgentParamsRequest` members like any other, so the
   * same partial patch Settings uses carries them; only what changed is sent,
   * and every other parameter is left alone. There is no Save button for this
   * card on purpose — a switch that needs a second click to take effect reads
   * as broken, which is exactly how it was reported.
   *
   * The draft moves first so the control responds immediately, and is put back
   * if the service refuses, so what is on screen is never a change that did not
   * happen.
   */
  const persistShare = async (
    change: Partial<AgentShare>,
    params: Partial<Nl2sqlAgentParams>,
    what: string,
  ) => {
    const previous = share;
    setShare((current) => current && { ...current, ...change });
    try {
      await agentMutations.saveParams.mutateAsync(params);
      await paramsQuery.refetch();
      toast.success(`${what} saved.`);
    } catch (error) {
      setShare(previous);
      toast.error(`Could not save ${what.toLowerCase()}: ${apiMessage(error)}`);
    }
  };

  /**
   * `POST …/widget/settings` — the appearance, which is stored separately from
   * the params above.
   */
  const saveAppearance = async () => {
    if (!share) return;
    try {
      await widgetSettings.save.mutateAsync(appearance);
      // An uploaded file is now stored and comes back as a URL on the refetch;
      // holding on to it would upload it again on the next save.
      setAppearance(
        (current) =>
          current && {
            ...current,
            widget_icon_file: undefined,
            widget_avatar_file: undefined,
          },
      );
      toast.success("Saved widget appearance.");
    } catch (error) {
      toast.error(`Could not save the settings: ${apiMessage(error)}`);
    }
  };

  const embed = `<script
  src="${host}/agent.js"
  data-agent-id="${agent.agent_id}"
  defer><\/script>`;

  const iframe = `<iframe
  src="${shareUrl}"
  width="100%" height="640"
  style="border:0"
  allow="clipboard-write"></iframe>`;

  const snippets: Record<ApiLang, string> = {
    py: `import requests

r = requests.post(
    "${host}/nl2sql/api/v1/agents/${agent.agent_id}/chat",
    headers={"x-api-key": "<YOUR_API_KEY>"},
    json={"query": "Show products with stock quantity less than 10",
          "chart_output": True, "follow_up": True, "debug_info": True},
    timeout=120,
)
d = r.json()
print(d["response"])
print(d["debug_info"]["sql_query"])`,
    js: `const r = await fetch(
  "${host}/nl2sql/api/v1/agents/${agent.agent_id}/chat",
  { method: "POST",
    headers: { "Content-Type": "application/json",
               "x-api-key": "<YOUR_API_KEY>" },
    body: JSON.stringify({
      query: "Show products with stock quantity less than 10",
      chart_output: true, follow_up: true, debug_info: true }) },
);
const d = await r.json();
console.log(d.response, d.debug_info.sql_query);`,
    curl: `curl -X POST \\
  "${host}/nl2sql/api/v1/agents/${agent.agent_id}/chat" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: <YOUR_API_KEY>" \\
  -d '{"query": "Show products with stock quantity less than 10",
       "debug_info": true}'`,
  };

  /**
   * The two channels keep separate allowlists, because the service does:
   * `allowed_domains` says where the bubble may be embedded,
   * `fullscreen_allowed_domains` where the full-page link may be opened from.
   * A domain added under one card is deliberately not added to the other.
   */
  const domainList = (channel: "widget" | "fullpage") =>
    channel === "widget" ? share.domains : share.fullscreenDomains;

  const writeDomains = (channel: "widget" | "fullpage", domains: string[]) =>
    persistShare(
      channel === "widget" ? { domains } : { fullscreenDomains: domains },
      channel === "widget"
        ? { allowed_domains: domains }
        : { fullscreen_allowed_domains: domains },
      channel === "widget" ? "Allowed domains" : "Full-page domains",
    );

  const addDomain = (channel: "widget" | "fullpage") => (domain: string) => {
    const domains = domainList(channel);
    if (domains.includes(domain)) return;
    writeDomains(channel, [...domains, domain]);
  };

  const removeDomain = (channel: "widget" | "fullpage") => (domain: string) =>
    writeDomains(
      channel,
      domainList(channel).filter((value) => value !== domain),
    );

  return (
    <>
      <PageHeader
        title="Share"
        subtitle="Let people ask questions without giving them your database. Three ways out — a chat bubble on your site, a full-page link, or the API."
      />

      <TabNav<"setup" | "activity">
        label="Share sections"
        className="mb-5"
        activeTab={tab}
        onChange={setTab}
        tabs={[
          { key: "setup", label: "Set up" },
          { key: "activity", label: "Activity" },
        ]}
      />

      {tab === "activity" ? (
        <ShareActivity agentId={agent.agent_id} />
      ) : (
        <>
          <div className="mb-3.5 flex flex-wrap items-center gap-2 px-0.5">
            <p className="text-sm text-slate-500">
              {SHARE_ROWS.length} features, each one row.{" "}
              <span className="font-semibold text-slate-700">
                {openRows.length === 0
                  ? "Nothing open"
                  : `${openRows.length} open`}
              </span>
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              onClick={() => setOpenRows(allOpen ? [] : [...SHARE_ROWS])}
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </Button>
          </div>

          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_392px]">
            <div className="space-y-4">
              <ShareRow
                id="share-answers"
                icon="chk"
                title="What people will get"
                purpose="What every answer carries — set under Settings → Answers"
                open={isOpen("answers")}
                onToggle={toggle("answers")}
                control={
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      router.push(agentRoute(ROUTES.settings, agent.agent_id))
                    }
                  >
                    Change
                  </Button>
                }
              >
                <div className="flex flex-wrap gap-2">
                  {FEATURE_CHIPS.map(([key, label]) => {
                    const on = Boolean(
                      (agent.feats as unknown as Record<string, boolean>)[key],
                    );
                    return (
                      <Chip key={key} size="sm" tone={on ? "green" : "slate"}>
                        {on && <Icon name="chk" className="size-3" />}
                        {label}
                      </Chip>
                    );
                  })}
                </div>
              </ShareRow>

              <ShareGroup
                step={1}
                title="Ways to share"
                purpose="Three ways people can reach this agent. Switch on the ones you want — each one is set up separately."
              >
                <ShareRow
                  accent
                  id="share-widget"
                  icon="chat"
                  title="Chat bubble on your website"
                  purpose="One script tag, a bubble in the corner of your own pages"
                  open={isOpen("widget")}
                  onToggle={toggle("widget")}
                  control={
                    <>
                      <Chip size="sm" tone={share.widget ? "green" : "slate"}>
                        {share.widget ? "Live" : "Off"}
                      </Chip>
                      <EnabledToggle
                        checked={share.widget}
                        label="Enable the chat bubble"
                        onChange={(checked) =>
                          persistShare(
                            { widget: checked },
                            { is_public: checked },
                            "Chat bubble",
                          )
                        }
                      />
                    </>
                  }
                >
                  <p className="text-sm text-slate-500">
                    A chat bubble you drop into any page with one script tag. No
                    API key — access is controlled by the domain list below.
                  </p>
                  <Domains
                    domains={share.domains}
                    onAdd={addDomain("widget")}
                    onRemove={removeDomain("widget")}
                  />
                  <CodeBlock
                    caption={
                      <span className="flex items-center gap-1.5">
                        <Icon name="code" className="size-3.5" /> Embed snippet
                      </span>
                    }
                    action={
                      <Button
                        variant="secondary"
                        size="xs"
                        onClick={() => copy(embed, "Embed snippet")}
                      >
                        Copy
                      </Button>
                    }
                  >
                    {embed}
                  </CodeBlock>
                  {!share.widget && (
                    <Banner tone="warn">
                      The bubble is switched off, so this snippet will not load
                      anywhere yet.
                    </Banner>
                  )}
                </ShareRow>

                <ShareRow
                  accent
                  id="share-fullpage"
                  icon="expand"
                  title="Full-page chat link"
                  purpose="A link that opens straight into an ask screen — no login"
                  open={isOpen("fullpage")}
                  onToggle={toggle("fullpage")}
                  control={
                    <>
                      <Chip size="sm" tone={share.fullpage ? "green" : "slate"}>
                        {share.fullpage ? "Live" : "Off"}
                      </Chip>
                      <EnabledToggle
                        checked={share.fullpage}
                        label="Enable the full-page link"
                        onChange={(checked) =>
                          persistShare(
                            { fullpage: checked },
                            { fullscreen_is_public: checked },
                            "Full-page link",
                          )
                        }
                      />
                    </>
                  }
                >
                  <p className="text-sm text-slate-500">
                    Opens straight into a full-page ask screen — no login, and
                    nobody has to expand a bubble first.
                  </p>
                  <Domains
                    domains={share.fullscreenDomains}
                    onAdd={addDomain("fullpage")}
                    onRemove={removeDomain("fullpage")}
                  />
                  <CodeBlock
                    caption={
                      <span className="flex items-center gap-1.5">
                        <Icon name="ext" className="size-3.5" /> Shareable link
                      </span>
                    }
                    action={
                      <span className="flex items-center gap-2">
                        <Button
                          variant="secondary"
                          size="xs"
                          onClick={() => copy(shareUrl, "Share link")}
                        >
                          Copy
                        </Button>
                        <Button
                          as="a"
                          href={shareUrl}
                          target="_blank"
                          variant="secondary"
                          size="xs"
                          startIcon={<Icon name="ext" className="size-3.5" />}
                        >
                          Open
                        </Button>
                      </span>
                    }
                  >
                    {shareUrl}
                  </CodeBlock>
                  <CodeBlock
                    caption="Iframe embed"
                    action={
                      <Button
                        variant="secondary"
                        size="xs"
                        onClick={() => copy(iframe, "Iframe embed")}
                      >
                        Copy
                      </Button>
                    }
                  >
                    {iframe}
                  </CodeBlock>
                </ShareRow>

                <ShareRow
                  accent
                  id="share-api"
                  icon="code"
                  title="API"
                  purpose="Ask from your own code, with a key you create here"
                  open={isOpen("api")}
                  onToggle={toggle("api")}
                  control={
                    <Button
                      size="sm"
                      startIcon={<Icon name="key" className="size-4" />}
                      onClick={generateKey}
                    >
                      Generate API key
                    </Button>
                  }
                >
                  <TabNav<ApiLang>
                    label="API language"
                    activeTab={lang}
                    onChange={setLang}
                    tabs={[
                      { key: "py", label: "Python" },
                      { key: "js", label: "JavaScript" },
                      { key: "curl", label: "cURL" },
                    ]}
                  />
                  <CodeBlock>{snippets[lang]}</CodeBlock>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      startIcon={<Icon name="copy" className="size-4" />}
                      onClick={() => copy(snippets[lang], "Code snippet")}
                    >
                      Copy
                    </Button>
                  </div>
                  {keys.data?.length ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-slate-700">
                        Your API keys
                      </p>
                      {keys.data.map((key) => (
                        <div
                          key={key.id}
                          className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 px-3 py-2"
                        >
                          <span className="font-mono text-xs text-slate-700">
                            {revealed[key.id] && key.secret
                              ? key.secret
                              : key.masked}
                          </span>
                          {key.active ? (
                            <Chip tone="green" size="sm">
                              Active
                            </Chip>
                          ) : (
                            <Chip tone="slate" size="sm">
                              Revoked
                            </Chip>
                          )}
                          <span className="text-[11px] text-slate-400">
                            created {absT(key.created)}
                          </span>
                          <div className="ml-auto flex items-center gap-2">
                            {key.secret && (
                              <>
                                <button
                                  type="button"
                                  aria-label={
                                    revealed[key.id] ? "Hide key" : "Show key"
                                  }
                                  title={
                                    revealed[key.id] ? "Hide key" : "Show key"
                                  }
                                  className="text-slate-400 hover:text-slate-700"
                                  onClick={() =>
                                    setRevealed((current) => ({
                                      ...current,
                                      [key.id]: !current[key.id],
                                    }))
                                  }
                                >
                                  {revealed[key.id] ? (
                                    <Icon name="eyeOff" className="size-4" />
                                  ) : (
                                    <Icon name="eye" className="size-4" />
                                  )}
                                </button>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  startIcon={
                                    <Icon name="copy" className="size-4" />
                                  }
                                  onClick={() =>
                                    copy(key.secret as string, "API key")
                                  }
                                >
                                  Copy
                                </Button>
                              </>
                            )}
                            {key.active && (
                              <Button
                                variant="danger"
                                size="sm"
                                startIcon={
                                  <Icon name="trash" className="size-4" />
                                }
                                onClick={async () => {
                                  try {
                                    await keyMutations.revoke.mutateAsync(
                                      key.id,
                                    );
                                    toast.success("API key revoked.");
                                  } catch (error) {
                                    toast.error(
                                      `Could not revoke the key: ${apiMessage(error)}`,
                                    );
                                  }
                                }}
                              >
                                Revoke
                              </Button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400">
                      No keys yet. A key lets your own code ask questions — it
                      can read answers, never change settings.
                    </p>
                  )}
                </ShareRow>
              </ShareGroup>

              <ShareGroup
                step={2}
                title="Who can get in"
                purpose="People you invite by email — inviting someone sends them an email — and what each of them is allowed to do here."
              >
                <ShareRow
                  id="share-people"
                  icon="users"
                  title="People"
                  purpose={`Who you invited, and what each can do · ${people.length} ${
                    people.length === 1 ? "person" : "people"
                  }`}
                  open={isOpen("people")}
                  onToggle={toggle("people")}
                  control={
                    <Button
                      size="sm"
                      startIcon={<Icon name="send" className="size-4" />}
                      onClick={() => {
                        // The invite field lives in the body, so the primary action
                        // has to open the row before it can put the caret in it.
                        setOpen("people", true);
                        requestAnimationFrame(() => inviteRef.current?.focus());
                      }}
                    >
                      Invite someone
                    </Button>
                  }
                >
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <Input
                        ref={inviteRef}
                        className="flex-1"
                        placeholder="name@company.com"
                        value={invite}
                        aria-label="Email to invite"
                        onChange={setInvite}
                      />
                      <Select
                        size="sm"
                        fullWidth={false}
                        className="w-28"
                        value={inviteRole}
                        aria-label="Role for the person being invited"
                        onChange={(value) =>
                          setInviteRole(value as "editor" | "viewer")
                        }
                        options={[
                          { value: "editor", label: "Editor" },
                          { value: "viewer", label: "Viewer" },
                        ]}
                      />
                      <Button
                        size="sm"
                        onClick={async () => {
                          const email = invite.trim();
                          if (!email) return;
                          try {
                            // Inviting somebody who already has access is not an
                            // error — it updates their role — so pressing this twice
                            // is safe and nothing here blocks it.
                            await peopleMutations.invite.mutateAsync({
                              email,
                              role: inviteRole,
                            });
                            setInvite("");
                            toast.success(`Invited ${email} as ${inviteRole}.`);
                          } catch (error) {
                            toast.error(
                              `Could not invite them: ${apiMessage(error)}`,
                            );
                          }
                        }}
                      >
                        Invite
                      </Button>
                    </div>
                    <div>
                      {people.map((person) => (
                        <div
                          key={person.email}
                          className="flex items-center justify-between gap-2 border-b border-gray-100 py-2 last:border-0"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium text-slate-800">
                              {person.email}
                            </span>
                            {person.since ? (
                              <span className="text-[11px] text-slate-400">
                                since {absT(Date.parse(person.since))}
                              </span>
                            ) : null}
                          </span>
                          {person.role === "owner" ? (
                            <Chip tone="slate" size="sm">
                              owner
                            </Chip>
                          ) : (
                            <span className="flex items-center gap-2">
                              <Select
                                size="xs"
                                fullWidth={false}
                                className="w-28"
                                value={person.role}
                                aria-label={`Role for ${person.email}`}
                                onChange={async (value) => {
                                  try {
                                    await peopleMutations.setRole.mutateAsync({
                                      email: person.email,
                                      role: value as "editor" | "viewer",
                                    });
                                    toast.success(
                                      `${person.email} is now a ${value}.`,
                                    );
                                  } catch (error) {
                                    toast.error(
                                      `Could not change the role: ${apiMessage(error)}`,
                                    );
                                  }
                                }}
                                options={[
                                  { value: "editor", label: "Editor" },
                                  { value: "viewer", label: "Viewer" },
                                ]}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={`Remove ${person.email}`}
                                startIcon={<Icon name="x" className="size-4" />}
                                onClick={async () => {
                                  // Access is revoked at once and the record is
                                  // deleted outright — there is nothing to undo, so
                                  // ask first.
                                  if (
                                    !window.confirm(
                                      `Remove ${person.email}? They lose access to this agent immediately.`,
                                    )
                                  )
                                    return;
                                  try {
                                    await peopleMutations.remove.mutateAsync(
                                      person.email,
                                    );
                                    toast.success(`${person.email} removed.`);
                                  } catch (error) {
                                    toast.error(
                                      `Could not remove them: ${apiMessage(error)}`,
                                    );
                                  }
                                }}
                              />
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </ShareRow>
              </ShareGroup>
            </div>

            <div className="xl:sticky xl:top-[78px]">
              <ShareGroup
                step={3}
                title="How it looks"
                purpose="Your branding, and a live preview of exactly what the people you share with will see."
              >
                <ShareRow
                  id="share-appearance"
                  icon="spark"
                  title="Appearance"
                  purpose="Heading, greeting, brand colour and launcher icon"
                  open={isOpen("appearance")}
                  onToggle={toggle("appearance")}
                  control={
                    <>
                      <Chip size="sm" tone="slate">
                        <span
                          aria-hidden="true"
                          className="size-2 rounded-full"
                          style={{ background: appearance.color }}
                        />
                        <span className="max-w-28 truncate">
                          {appearance.heading || "Untitled"}
                        </span>
                      </Chip>
                      <Button
                        variant="ghost"
                        size="sm"
                        // Back to what is stored, not to the product defaults —
                        // this drops unsaved edits, it does not reset the widget.
                        onClick={() => setAppearance(seeded())}
                      >
                        Reset
                      </Button>
                    </>
                  }
                >
                  <Field required label="Heading" htmlFor="apHead">
                    <Input
                      id="apHead"
                      value={appearance.heading}
                      onChange={(value) =>
                        setAppearance(
                          (current) =>
                            current && { ...current, heading: value },
                        )
                      }
                    />
                  </Field>
                  <Field required label="Sub heading" htmlFor="apSub">
                    <Input
                      id="apSub"
                      value={appearance.sub}
                      onChange={(value) =>
                        setAppearance(
                          (current) => current && { ...current, sub: value },
                        )
                      }
                    />
                  </Field>
                  <Field required label="Greeting" htmlFor="apGreet">
                    <Input
                      as="textarea"
                      id="apGreet"
                      rows={3}
                      value={appearance.greet}
                      onChange={(value) =>
                        setAppearance(
                          (current) => current && { ...current, greet: value },
                        )
                      }
                    />
                  </Field>
                  <Field
                    label="Brand colour"
                    hint="Saved with the Database Agent widget settings."
                  >
                    <div className="flex flex-wrap gap-2">
                      {SWATCHES.map((color) => (
                        <button
                          key={color}
                          type="button"
                          aria-pressed={appearance.color === color}
                          aria-label={`Brand colour ${color}`}
                          style={{ background: color }}
                          className={cn(
                            "size-7 cursor-pointer rounded-full transition-shadow",
                            appearance.color === color
                              ? "ring-2 ring-indigo-500 ring-offset-2"
                              : "ring-1 ring-black/10",
                          )}
                          onClick={() =>
                            setAppearance(
                              (current) => current && { ...current, color },
                            )
                          }
                        />
                      ))}
                    </div>
                  </Field>
                  <label className="flex cursor-pointer gap-2">
                    <Checkbox
                      className="mt-0.5"
                      checked={appearance.show_sources}
                      onCheckedChange={(checked) =>
                        setAppearance(
                          (current) =>
                            current && {
                              ...current,
                              show_sources: checked,
                            },
                        )
                      }
                    />
                    <span>
                      <span className="block text-sm font-medium text-slate-800">
                        Show the SQL to viewers
                      </span>
                      <span className="block text-xs text-slate-500">
                        Off keeps just the answer — better for non-technical
                        audiences.
                      </span>
                    </span>
                  </label>
                  <Field label="Launcher icon">
                    <div className="flex flex-wrap gap-2">
                      {(widgetSettings.icons.data ?? []).map(
                        ({ url }, index) => (
                          <button
                            key={url}
                            type="button"
                            aria-pressed={appearance.widget_icon === url}
                            aria-label={`Icon ${index + 1}`}
                            className={cn(
                              "flex size-9 cursor-pointer items-center justify-center rounded-lg border transition-colors",
                              appearance.widget_icon === url
                                ? "border-indigo-500 bg-indigo-50 text-indigo-600"
                                : "border-slate-200 text-slate-500 hover:bg-slate-50",
                            )}
                            onClick={() =>
                              setAppearance(
                                (current) =>
                                  current && {
                                    ...current,
                                    widget_icon: url,
                                    widget_icon_file: undefined,
                                  },
                              )
                            }
                          >
                            <SwatchImage url={url} label={String(index + 1)} />
                          </button>
                        ),
                      )}
                    </div>
                    <AssetUpload
                      id="widgetIconFile"
                      label="Upload a launcher icon"
                      file={appearance.widget_icon_file}
                      onReject={toast.error}
                      onPick={(file) =>
                        setAppearance(
                          (current) =>
                            current && { ...current, widget_icon_file: file },
                        )
                      }
                      onClear={() =>
                        setAppearance(
                          (current) =>
                            current && {
                              ...current,
                              widget_icon_file: undefined,
                            },
                        )
                      }
                    />
                  </Field>
                  <Field label="Chat avatar">
                    <div className="flex flex-wrap gap-2">
                      {(widgetSettings.avatars.data ?? []).map(
                        ({ url }, index) => (
                          <button
                            key={url}
                            type="button"
                            aria-pressed={appearance.widget_avatar === url}
                            aria-label={`Avatar ${index + 1}`}
                            className={cn(
                              "flex size-9 cursor-pointer items-center justify-center rounded-lg border transition-colors",
                              appearance.widget_avatar === url
                                ? "border-indigo-500 bg-indigo-50 text-indigo-600"
                                : "border-slate-200 text-slate-500 hover:bg-slate-50",
                            )}
                            onClick={() =>
                              setAppearance(
                                (current) =>
                                  current && {
                                    ...current,
                                    widget_avatar: url,
                                    widget_avatar_file: undefined,
                                  },
                              )
                            }
                          >
                            <SwatchImage url={url} label={String(index + 1)} />
                          </button>
                        ),
                      )}
                    </div>
                    <AssetUpload
                      id="widgetAvatarFile"
                      label="Upload a chat avatar"
                      file={appearance.widget_avatar_file}
                      onReject={toast.error}
                      onPick={(file) =>
                        setAppearance(
                          (current) =>
                            current && { ...current, widget_avatar_file: file },
                        )
                      }
                      onClear={() =>
                        setAppearance(
                          (current) =>
                            current && {
                              ...current,
                              widget_avatar_file: undefined,
                            },
                        )
                      }
                    />
                  </Field>
                  <Button fullWidth onClick={saveAppearance}>
                    Save appearance
                  </Button>
                  <Button
                    fullWidth
                    variant="secondary"
                    onClick={async () => {
                      if (
                        !window.confirm(
                          "Reset widget appearance to the service defaults?",
                        )
                      )
                        return;
                      try {
                        await widgetSettings.reset.mutateAsync();
                        toast.success("Widget appearance reset.");
                      } catch (error) {
                        toast.error(
                          `Could not reset the widget: ${apiMessage(error)}`,
                        );
                      }
                    }}
                  >
                    Reset widget appearance
                  </Button>
                </ShareRow>

                <ShareRow
                  id="share-preview"
                  icon="eye"
                  title="Live preview"
                  purpose="What the people you share with see"
                  open={isOpen("preview")}
                  onToggle={toggle("preview")}
                  control={
                    <div
                      role="tablist"
                      aria-label="Preview mode"
                      className="flex rounded-md bg-slate-100 p-0.5"
                    >
                      {(
                        [
                          ["bubble", "Bubble"],
                          ["full", "Full page"],
                        ] as const
                      ).map(([key, label]) => (
                        <button
                          key={key}
                          role="tab"
                          type="button"
                          aria-selected={mode === key}
                          onClick={() => setMode(key)}
                          className={cn(
                            "cursor-pointer rounded px-2.5 py-1 text-xs font-medium transition-colors",
                            mode === key
                              ? "bg-white text-slate-900 shadow-sm"
                              : "text-slate-500 hover:text-slate-700",
                          )}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  }
                >
                  <SharePreview appearance={appearance} mode={mode} />
                </ShareRow>
              </ShareGroup>
            </div>
          </div>
        </>
      )}
    </>
  );
}
