"use client";

import { useEffect, useState } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import Icon from "@/components/Icon";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import Field from "@/components/ui/Field";
import PageHeader from "@/components/ui/PageHeader";
import TabNav from "@/components/ui/TabNav";
import { changedParams, fetchNodes, toFeatures } from "@/data/agents";
import { FEATURES } from "@/data/constants";
import type { DbCredentials } from "@/data/databases";
import { useAgentMutations, useDatabaseMutations } from "@/data/mutations";
import { useProviders } from "@/data/providers";
import type { AgentDatabase, AgentFeatures, NodeConfig } from "@/data/types";
import { useAgent, useAgentParams } from "@/data/useAgents";
import { apiMessage } from "@/lib/apiError";
import { useToast } from "@/platform/components/ToastContext";
import {
  Button,
  Checkbox,
  Input,
  Modal,
  Select,
  Switch,
} from "@/platform/components/ui";

import AddDatabaseMenuModal from "./AddDatabaseMenuModal";
import { TABS, type AddDbMode } from "./constants";
import DatabaseConfigPanel from "./DatabaseConfigPanel";
import DatabaseCredentialsModal from "./DatabaseCredentialsModal";
import ImportDatabasesModal from "./ImportDatabasesModal";
import RdsDatabasesModal from "./RdsDatabasesModal";

type SettingsTab = "databases" | "answers" | "advanced";

const settingsSchema = z.object({
  name: z.string(),
  feats: z.custom<AgentFeatures | null>(),
  suggested: z.array(z.string()),
  nodes: z.array(z.custom<NodeConfig>()),
});

type SettingsForm = z.infer<typeof settingsSchema>;

/**
 * One three-state chip per database: a connection failure always wins, then
 * whether a description exists at all.
 */
function StatusChip({
  db,
  latency,
}: {
  db: AgentDatabase;
  /** Round trip from the last check this session, if one has run. */
  latency?: number;
}) {
  if (!db.reachable) {
    return (
      <Chip tone="rose" size="sm">
        <Icon name="warn" className="size-3" /> Connection failed
      </Chip>
    );
  }
  if (db.description) {
    // The check this session is the fresher number, and the one the list
    // endpoint does not carry — reading `db.latency` alone meant "Check all"
    // measured every database and then showed none of the timings.
    const shown = latency ?? db.latency;
    return (
      <Chip tone="green" size="sm">
        <Icon name="chk" className="size-3" /> Description set
        {shown ? ` · ${shown}ms` : ""}
      </Chip>
    );
  }
  return (
    <Chip tone="amber" size="sm">
      <Icon name="warn" className="size-3" /> Add description to activate
    </Chip>
  );
}

interface SettingsViewProps {
  agentId?: string;
}

export default function SettingsView({ agentId }: SettingsViewProps) {
  const { toast } = useToast();
  const { agent, isLoading: agentLoading } = useAgent(agentId);
  const serviceId = agent?.service_ref ?? null;
  const dbs = agent?.dbs ?? [];
  const databaseMutations = useDatabaseMutations(serviceId);
  const agentMutations = useAgentMutations(agent);
  const client = useQueryClient();

  /**
   * Re-reads the database list after a flow that adds several at once. Those
   * call `POST …/databases` directly rather than through the mutation, so the
   * invalidation the mutations do has to happen here — without it the list still
   * shows what was there before the import.
   */
  const refreshDatabases = () => {
    client.invalidateQueries({ queryKey: ["databases", serviceId] });
    client.invalidateQueries({ queryKey: ["tables", serviceId] });
  };

  const [tab, setTab] = useState<SettingsTab>("databases");
  const [configuring, setConfiguring] = useState<string | null>(null);
  /** `"new"` opens the add form; a db_id opens that database's credentials. */
  const [credentialsFor, setCredentialsFor] = useState<string | null>(null);
  /**
   * Which step of "Add database" is open: the chooser, or one of the three
   * flows. The manual flow is the credentials modal in add mode, so it sets
   * `credentialsFor` instead of living here.
   */
  const [adding, setAdding] = useState<"menu" | "import" | "rds" | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  /** Round trips from the last check, which the list endpoint does not carry. */
  const [latencies, setLatencies] = useState<Record<string, number>>({});
  /**
   * Which node rows are expanded, by `node_name`.
   *
   * Held here rather than left to `<details>`: editing a node calls
   * `setValue("nodes", …)`, which makes `useFieldArray` hand back freshly
   * generated ids. Those were the rows' React keys, so every edit remounted the
   * row and a `<details>` that owns its own `open` came back closed — picking a
   * provider shut the panel you were working in. Keying on the node's own name
   * keeps the row mounted, and keeping `open` in state means only a click on
   * the summary ever opens or closes it.
   */
  const [openNodes, setOpenNodes] = useState<Record<string, boolean>>({});
  const { control, getValues, setValue, watch } = useForm<SettingsForm>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      name: "",
      feats: null,
      suggested: [],
      nodes: [],
    },
  });
  const { replace: replaceNodes } = useFieldArray({ control, name: "nodes" });
  const name = watch("name");
  const feats = watch("feats");
  const suggested = watch("suggested");
  const nodes = watch("nodes");
  const setName = (value: string) => setValue("name", value);
  const setFeats = (
    updater: (current: AgentFeatures | null) => AgentFeatures | null,
  ) => setValue("feats", updater(getValues("feats")));
  const setSuggested = (updater: (current: string[]) => string[]) =>
    setValue("suggested", updater(getValues("suggested")));
  const setNodes = (updater: (current: NodeConfig[]) => NodeConfig[]) =>
    setValue("nodes", updater(getValues("nodes")));

  // The Answers form edits a draft of the parameters the service holds, read
  // from `GET …/config?fields=agent_params` — the path that owns them — rather
  // than from whatever the agent list happened to carry. The agent row is only
  // the fallback while that call is in flight.
  //
  // `useAgent` rebuilds the agent object on every render to attach `dbs`, so the
  // seeding effect reads these fields rather than the object — depending on the
  // object itself re-seeded the form on every render.
  const paramsQuery = useAgentParams(serviceId);
  const loadedParams = paramsQuery.data;
  const loadedName = loadedParams?.agent_name ?? agent?.name;
  const loadedFeats = loadedParams ? toFeatures(loadedParams) : agent?.feats;
  const loadedSuggested =
    loadedParams?.suggested_questions ?? agent?.suggested_questions;
  const featsKey = JSON.stringify(loadedFeats ?? null);
  const suggestedKey = JSON.stringify(loadedSuggested ?? []);

  useEffect(() => {
    if (loadedName === undefined) return;
    setValue("name", loadedName);
    setValue("feats", (JSON.parse(featsKey) as AgentFeatures | null) ?? null);
    setValue("suggested", JSON.parse(suggestedKey) as string[]);
  }, [loadedName, featsKey, suggestedKey, setValue]);

  const providers = useProviders();
  /** Models for a provider, from the service rather than a list of our own. */
  const modelsFor = (provider: string) =>
    providers.data?.find((entry) => entry.provider === provider)?.models ?? [];

  const nodeQuery = useQuery({
    queryKey: ["nodes", serviceId],
    queryFn: () => fetchNodes(serviceId as string),
    enabled: Boolean(serviceId),
  });

  useEffect(() => {
    if (nodeQuery.data) replaceNodes(nodeQuery.data);
  }, [nodeQuery.data, replaceNodes]);

  const toggleFeature = (key: string, value: boolean) =>
    setFeats((current) => (current ? { ...current, [key]: value } : current));

  const editing = dbs.find((db) => db.db_id === credentialsFor);
  const pendingDelete = dbs.find((db) => db.db_id === deleting);

  /** `POST …/databases/check` — the service tests each database and times it. */
  const checkAll = async () => {
    try {
      const results = await databaseMutations.checkAll.mutateAsync();
      const ok = results.filter((row) => row.connection === "connected").length;
      const failed = results.length - ok;
      setLatencies(
        Object.fromEntries(results.map((row) => [row.db_id, row.response_ms])),
      );
      if (failed) {
        toast.warning(
          `${ok} database${ok === 1 ? "" : "s"} answered, ${failed} could not be reached.`,
        );
      } else {
        toast.success(`All ${ok} database${ok === 1 ? "" : "s"} answered.`);
      }
    } catch (error) {
      toast.error(`Could not check the databases: ${apiMessage(error)}`);
    }
  };

  /** Re-tests one database by running the same check and reading its row. */
  const retry = async (dbId: string, dbName: string) => {
    try {
      const results = await databaseMutations.checkAll.mutateAsync();
      const row = results.find((entry) => entry.db_id === dbId);
      setLatencies((current) => ({
        ...current,
        ...(row ? { [row.db_id]: row.response_ms } : {}),
      }));
      if (row?.connection === "connected") {
        toast.success(`${dbName} answered in ${row.response_ms}ms.`);
      } else {
        toast.error(row?.error || `${dbName} still cannot be reached.`);
      }
    } catch (error) {
      toast.error(`Could not reach ${dbName}: ${apiMessage(error)}`);
    }
  };

  const saveCredentials = async (credentials: DbCredentials) => {
    try {
      if (credentialsFor === "new") {
        const db = await databaseMutations.add.mutateAsync(credentials);
        toast[db.reachable ? "success" : "warning"](
          db.reachable
            ? `${db.db_name} connected.`
            : `${db.db_name} was saved but could not be reached.`,
        );
      } else if (credentialsFor) {
        const db = await databaseMutations.update.mutateAsync({
          dbId: credentialsFor,
          credentials,
        });
        toast[db.reachable ? "success" : "warning"](
          db.reachable
            ? `${db.db_name} reconnected.`
            : `Saved, but ${db.db_name} still cannot be reached.`,
        );
      }
      setCredentialsFor(null);
    } catch (error) {
      toast.error(`Could not save the connection: ${apiMessage(error)}`);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await databaseMutations.remove.mutateAsync(pendingDelete.db_id);
      if (configuring === pendingDelete.db_id) setConfiguring(null);
      toast.success(`${pendingDelete.db_name} removed from this agent.`);
    } catch (error) {
      toast.error(
        `Could not remove ${pendingDelete.db_name}: ${apiMessage(error)}`,
      );
    }
    setDeleting(null);
  };

  const saveAdvanced = async () => {
    try {
      const result = await agentMutations.saveNodeConfig.mutateAsync(nodes);
      toast.success(result.message ?? "Node configuration saved.");
    } catch (error) {
      toast.error(`Could not save the nodes: ${apiMessage(error)}`);
    }
  };

  /** Drops one node's override server-side, rather than only in the form. */
  const resetNode = async (nodeName: string) => {
    try {
      const result = await agentMutations.resetNodeConfig.mutateAsync(nodeName);
      toast.success(result.message ?? `${nodeName} is back on the default.`);
    } catch (error) {
      toast.error(`Could not reset ${nodeName}: ${apiMessage(error)}`);
    }
  };

  /**
   * `PATCH …/config/params` with the service's own field names, and only the
   * fields that changed — the parameters the NL2SQL contract does not define
   * (memory, raw response, transcription language) are not sent at all.
   *
   * "Show sources" writes three fields, not two: `debug_info` is the master
   * switch for the whole sources block, and `show_sql_query` / `show_db_result`
   * only choose what goes inside it. Now that the chat no longer forces
   * `debug_info: true` on every request, writing only the latter two would mean
   * the block never renders at all.
   */
  const saveAnswers = async () => {
    if (!feats) return;
    const patch = changedParams(loadedParams, {
      agent_name: name.trim() || agent?.name,
      debug_info: feats.show_sources,
      show_sql_query: feats.show_sources,
      show_db_result: feats.show_sources,
      follow_up: feats.follow_up,
      graph_output: feats.chart_output,
      voice_input_enabled: feats.voice_input,
      voice_output_enabled: feats.voice_output,
      suggested_questions: suggested.filter((question) => question.trim()),
    });

    if (!Object.keys(patch).length) {
      toast.success("Nothing to save — these are the settings in use.");
      return;
    }

    try {
      await agentMutations.saveParams.mutateAsync(patch);
      await paramsQuery.refetch();
      toast.success("Answer settings saved.");
    } catch (error) {
      toast.error(`Could not save the settings: ${apiMessage(error)}`);
    }
  };

  if (agentLoading && !agent) {
    return (
      <Card>
        <EmptyState icon="ref" title="Loading this agent…" />
      </Card>
    );
  }

  if (!agent) {
    return (
      <Card>
        <EmptyState
          icon="warn"
          title="No database agent"
          note="This account has no agent with the Database Agent service enabled."
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
          note="Its settings, name included, are not editable here. One agent serves every user, so only its owner can change it. Ask it questions from Conversations."
        />
      </Card>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Your databases, what the agent is allowed to read, and how answers are presented. Everything else runs on defaults that already work."
      />

      <TabNav<SettingsTab>
        className="mb-5"
        label="Settings sections"
        activeTab={tab}
        onChange={setTab}
        tabs={TABS as Array<{ key: SettingsTab; label: string }>}
      />

      {tab === "databases" && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <p className="min-w-56 flex-1 text-sm text-slate-500">
              Each database is queried on its own. A question that spans two of
              them is combined automatically.
            </p>
            <Button
              variant="secondary"
              size="sm"
              loading={databaseMutations.checkAll.isPending}
              loadingText="Checking…"
              startIcon={<Icon name="ref" className="size-4" />}
              onClick={checkAll}
            >
              Check all
            </Button>
            <Button
              size="sm"
              startIcon={<Icon name="plus" className="size-4" />}
              onClick={() => setAdding("menu")}
            >
              Add database
            </Button>
          </div>

          <Card>
            {dbs.map((db) => {
              const tableCount = db.table_count ?? 0;
              return (
                <div
                  key={db.db_id}
                  className="border-b border-gray-100 last:border-0"
                >
                  <div className="flex flex-wrap items-center gap-2 px-4 py-3">
                    <span className="min-w-44 flex-1">
                      <span className="block text-sm font-medium text-slate-800">
                        {db.db_name}
                      </span>
                      <span className="block font-mono text-xs text-slate-400">
                        {db.db_host}:{db.db_port}
                      </span>
                    </span>
                    <Chip tone="blue" size="sm">
                      {db.db_engine}
                    </Chip>
                    <StatusChip db={db} latency={latencies[db.db_id]} />
                    <Chip tone="slate" size="sm">
                      {tableCount} table{tableCount === 1 ? "" : "s"}
                    </Chip>
                    <span className="ml-auto flex flex-wrap items-center gap-2">
                      <Switch
                        checked={db.active}
                        aria-label={`Include ${db.db_name} in answers`}
                        title="Include in answers"
                        onCheckedChange={async (checked) => {
                          try {
                            await databaseMutations.setActive.mutateAsync({
                              dbId: db.db_id,
                              isActive: checked,
                            });
                            toast.success(
                              checked
                                ? `${db.db_name} is included in answers.`
                                : `${db.db_name} is excluded from answers.`,
                            );
                          } catch (error) {
                            toast.error(
                              `Could not update ${db.db_name}: ${apiMessage(error)}`,
                            );
                          }
                        }}
                      />
                      {!db.reachable && (
                        <Button
                          variant="secondary"
                          size="sm"
                          startIcon={<Icon name="ref" className="size-4" />}
                          onClick={() => retry(db.db_id, db.db_name)}
                        >
                          Retry
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        size="sm"
                        startIcon={<Icon name="key" className="size-4" />}
                        onClick={() => setCredentialsFor(db.db_id)}
                      >
                        Edit credentials
                      </Button>
                      <Button
                        variant={
                          configuring === db.db_id ? "primary" : "secondary"
                        }
                        size="sm"
                        startIcon={<Icon name="cog" className="size-4" />}
                        onClick={() =>
                          setConfiguring((current) =>
                            current === db.db_id ? null : db.db_id,
                          )
                        }
                      >
                        Configure
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove ${db.db_name}`}
                        startIcon={<Icon name="trash" className="size-4" />}
                        onClick={() => setDeleting(db.db_id)}
                      />
                    </span>
                  </div>
                  {configuring === db.db_id && (
                    <DatabaseConfigPanel
                      serviceId={serviceId as string}
                      db={db}
                      onClose={() => setConfiguring(null)}
                      onRetry={() => retry(db.db_id, db.db_name)}
                      onEditCredentials={() => setCredentialsFor(db.db_id)}
                    />
                  )}
                </div>
              );
            })}
          </Card>
        </>
      )}

      {tab === "answers" && (
        <div className="space-y-4">
          <Card>
            <CardHeader title="General" />
            <CardBody>
              <Field required label="Agent Name" htmlFor="agName">
                <Input id="agName" value={name} onChange={setName} />
              </Field>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Features" />
            <CardBody className="grid gap-3 sm:grid-cols-2">
              {FEATURES.map(([key, title, hint]) => (
                <label key={key} className="flex cursor-pointer gap-2">
                  <Checkbox
                    className="mt-0.5"
                    checked={Boolean(feats?.[key as keyof AgentFeatures])}
                    onCheckedChange={(checked) => toggleFeature(key, checked)}
                  />
                  <span>
                    <span className="block text-sm font-medium text-slate-800">
                      {title}
                    </span>
                    <span className="block text-xs text-slate-500">{hint}</span>
                  </span>
                </label>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Voice" />
            <CardBody className="space-y-3">
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={Boolean(feats?.voice_input)}
                  onCheckedChange={(checked) =>
                    toggleFeature("voice_input", checked)
                  }
                />
                <span className="text-sm font-medium text-slate-800">
                  Enable Voice Input
                </span>
              </label>
              {feats?.voice_input && (
                <p className="ml-7 max-w-md text-xs text-slate-500">
                  The language is detected from what is spoken — the service
                  stores no per-agent transcription language, so there is
                  nothing to choose here.
                </p>
              )}
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={Boolean(feats?.voice_output)}
                  onCheckedChange={(checked) =>
                    toggleFeature("voice_output", checked)
                  }
                />
                <span className="text-sm font-medium text-slate-800">
                  Enable Voice Output
                </span>
              </label>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Suggested Questions"
              note="shown to users so they can click to start a conversation"
            />
            <CardBody className="space-y-2">
              {suggested.map((question, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Input
                    className="flex-1"
                    value={question}
                    aria-label={`Suggested question ${index + 1}`}
                    onChange={(value) =>
                      setSuggested((current) =>
                        current.map((row, i) => (i === index ? value : row)),
                      )
                    }
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove suggested question ${index + 1}`}
                    startIcon={<Icon name="trash" className="size-4" />}
                    onClick={() =>
                      setSuggested((current) =>
                        current.filter((_, i) => i !== index),
                      )
                    }
                  />
                </div>
              ))}
              <Button
                variant="secondary"
                size="sm"
                fullWidth
                startIcon={<Icon name="plus" className="size-4" />}
                onClick={() => setSuggested((current) => [...current, ""])}
              >
                Add Question
              </Button>
            </CardBody>
          </Card>

          <Button onClick={saveAnswers}>Save Changes</Button>
        </div>
      )}

      {adding === "menu" && (
        <AddDatabaseMenuModal
          onClose={() => setAdding(null)}
          onPick={(mode: AddDbMode) => {
            setAdding(mode === "manual" ? null : mode);
            if (mode === "manual") setCredentialsFor("new");
          }}
        />
      )}

      {adding === "import" && serviceId && (
        <ImportDatabasesModal
          serviceId={serviceId}
          onClose={() => setAdding(null)}
          onImported={refreshDatabases}
        />
      )}

      {adding === "rds" && serviceId && (
        <RdsDatabasesModal
          serviceId={serviceId}
          existingNames={dbs.map((db) => db.db_name)}
          onClose={() => setAdding(null)}
          onAdded={refreshDatabases}
        />
      )}

      {credentialsFor && (
        <DatabaseCredentialsModal
          db={editing}
          onClose={() => setCredentialsFor(null)}
          onSave={saveCredentials}
        />
      )}

      <Modal
        open={Boolean(pendingDelete)}
        variant="danger"
        maxWidth="md"
        title={`Remove ${pendingDelete?.db_name ?? ""}?`}
        confirmText="Remove database"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      >
        <p className="text-sm text-slate-600">
          The agent stops answering questions from this database. Its tables,
          descriptions and few-shot examples are removed with it — the database
          itself is untouched.
        </p>
      </Modal>

      {tab === "advanced" && (
        <>
          <PageHeader
            title="Agent Node Configuration"
            subtitle="Manage AI models and system prompts for each node in your agent's workflow."
          />
          <Card>
            {nodes.map((node, index) => (
              <details
                key={node.node_name}
                open={Boolean(openNodes[node.node_name])}
                onToggle={(event) => {
                  const open = event.currentTarget.open;
                  setOpenNodes((current) =>
                    current[node.node_name] === open
                      ? current
                      : { ...current, [node.node_name]: open },
                  );
                }}
                className="border-b border-gray-100 last:border-0"
              >
                <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-slate-700">
                  <span className="flex-1">{node.label}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
                    {node.model}
                  </span>
                  {node.is_default ? (
                    <Chip tone="slate" size="sm">
                      default
                    </Chip>
                  ) : (
                    <Chip tone="amber" size="sm">
                      changed
                    </Chip>
                  )}
                </summary>
                <div className="space-y-4 border-t border-gray-100 p-4">
                  <p className="text-sm text-slate-500">{node.hint}</p>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Provider">
                      <Select
                        value={node.provider}
                        aria-label={`Provider for ${node.label}`}
                        onChange={(value) =>
                          setNodes((current) =>
                            current.map((row, i) =>
                              i === index
                                ? {
                                    ...row,
                                    provider: value,
                                    model:
                                      providers.data?.find(
                                        (entry) => entry.provider === value,
                                      )?.defaultModel ??
                                      modelsFor(value)[0] ??
                                      row.model,
                                    is_default: false,
                                  }
                                : row,
                            ),
                          )
                        }
                        options={(providers.data ?? []).map((entry) => ({
                          value: entry.provider,
                          label: entry.provider,
                        }))}
                      />
                    </Field>
                    <Field label="Model">
                      <Select
                        value={node.model}
                        aria-label={`Model for ${node.label}`}
                        onChange={(value) =>
                          setNodes((current) =>
                            current.map((row, i) =>
                              i === index
                                ? { ...row, model: value, is_default: false }
                                : row,
                            ),
                          )
                        }
                        options={modelsFor(node.provider).map((model) => ({
                          value: model,
                          label: model,
                        }))}
                      />
                    </Field>
                    <Field label="Temperature">
                      <Input
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={String(node.temperature)}
                        aria-label={`Temperature for ${node.label}`}
                        onChange={(value) =>
                          setNodes((current) =>
                            current.map((row, i) =>
                              i === index
                                ? {
                                    ...row,
                                    temperature: Number(value),
                                    is_default: false,
                                  }
                                : row,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label="Max Tokens">
                      <Input
                        type="number"
                        min={1}
                        max={8000}
                        value={String(node.max_tokens)}
                        aria-label={`Max tokens for ${node.label}`}
                        onChange={(value) =>
                          setNodes((current) =>
                            current.map((row, i) =>
                              i === index
                                ? {
                                    ...row,
                                    max_tokens: Number(value),
                                    is_default: false,
                                  }
                                : row,
                            ),
                          )
                        }
                      />
                    </Field>
                  </div>
                  <Field
                    label="Prompt"
                    hint="Appended to the built-in prompt for this step — it never replaces it."
                  >
                    <Input
                      as="textarea"
                      rows={3}
                      value={node.prompt}
                      placeholder="e.g. revenue always excludes cancelled orders"
                      aria-label={`Prompt for ${node.label}`}
                      onChange={(value) =>
                        setNodes((current) =>
                          current.map((row, i) =>
                            i === index
                              ? { ...row, prompt: value, is_default: false }
                              : row,
                          ),
                        )
                      }
                    />
                  </Field>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-slate-400">
                      {node.node_name}
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="ml-auto"
                      loading={
                        agentMutations.resetNodeConfig.isPending &&
                        agentMutations.resetNodeConfig.variables ===
                          node.node_name
                      }
                      loadingText="Resetting…"
                      onClick={() => resetNode(node.node_name)}
                    >
                      Reset to default
                    </Button>
                  </div>
                </div>
              </details>
            ))}
          </Card>
          <div className="mt-4 flex items-center gap-2">
            <span className="text-xs text-slate-400">
              Changes apply to the next question this agent is asked.
            </span>
            <Button className="ml-auto" onClick={saveAdvanced}>
              Save node configuration
            </Button>
          </div>
        </>
      )}
    </>
  );
}
