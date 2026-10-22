"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import Icon, { type IconName } from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import CodeBlock from "@/components/ui/CodeBlock";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import { createNl2sqlAgent, listRdsDatabases } from "@/data/agents";
import {
  addDatabase,
  fetchDatabases,
  generateDescription,
  testConnection,
  type DbCredentials,
} from "@/data/databases";
import { useOwnerId } from "@/data/session";
import type { AgentDatabase } from "@/data/types";
import { apiMessage } from "@/lib/apiError";
import { parseConnections } from "@/lib/parseConnections";
import { agentRoute, ROUTES } from "@/lib/routes";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Checkbox, Input, Select } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import {
  ENGINES,
  MONO_INPUT,
  PROVISION_STEPS,
  SAMPLE_ROWS,
  TABLE_COUNT_POLLS,
} from "./constants";

type Mode = "manual" | "file" | "rds";
type StepState = "idle" | "run" | "done";

/** Tables across an agent's databases, ignoring rows the service left null. */
const countTables = (rows: AgentDatabase[]) =>
  rows.reduce((total, row) => total + (row.table_count ?? 0), 0);

/**
 * What step 2 needs before anything is tested or created, by source.
 *
 * Each issue's message is the label of the field it names, so the footer can
 * say "Still needed: Host, Password" and each field can light up on its own.
 * `mode` is part of the form because it decides which of these apply.
 */
const wizardSchema = z
  .object({
    mode: z.enum(["manual", "file", "rds"]),
    name: z.string(),
    paste: z.string(),
    db: z.object({
      engine: z.string(),
      host: z.string(),
      port: z.number(),
      name: z.string(),
      user: z.string(),
      pass: z.string(),
      description: z.string(),
    }),
    rds: z.object({
      host: z.string(),
      engine: z.string(),
      user: z.string(),
      pass: z.string(),
      fetched: z.boolean(),
      picked: z.array(z.string()),
    }),
  })
  .superRefine((form, ctx) => {
    const need = (path: (string | number)[], label: string) =>
      ctx.addIssue({ code: "custom", path, message: label });
    if (form.mode === "manual") {
      if (!form.db.host.trim()) need(["db", "host"], "Host");
      if (!form.db.name.trim()) need(["db", "name"], "Database name");
      if (!form.db.user.trim()) need(["db", "user"], "Username");
      if (!form.db.pass) need(["db", "pass"], "Password");
      return;
    }
    if (form.mode === "rds") {
      if (!form.rds.host.trim()) need(["rds", "host"], "RDS host");
      if (!form.rds.pass) need(["rds", "pass"], "Password");
      if (!form.rds.picked.length) {
        need(["rds", "picked"], "At least one database");
      }
      return;
    }
    if (!form.paste.trim()) {
      need(["paste"], "Connection rows");
      return;
    }
    const parsed = parseConnections(form.paste);
    if (!parsed.connections.length) {
      need(["paste"], parsed.errors[0] ?? "Readable connection rows");
      return;
    }
    // A row that could not be read is reported rather than dropped in silence
    // — a half-imported set is worse than a refused one.
    parsed.errors.forEach((error, index) => need(["paste", index], error));
  });
type WizardForm = z.infer<typeof wizardSchema>;

/** Every message in react-hook-form's nested error object, in field order. */
function errorMessages(errors: unknown): string[] {
  if (!errors || typeof errors !== "object") return [];
  const own = (errors as { message?: unknown }).message;
  if (typeof own === "string") return [own];
  return Object.values(errors).flatMap(errorMessages);
}

interface NewAgentWizardProps {
  onClose: () => void;
}

/**
 * New-agent flow: name it, describe its databases (by hand, from pasted CSV/JSON,
 * or discovered on an RDS host), then provision.
 *
 * Both steps are real calls — `POST /nl2sql/api/v1/agents`, then one
 * `POST …/databases` per connection, which the service tests and reads the
 * schema from. Each step is timed by the request it made, so the progress list
 * reports what actually happened rather than a rehearsal.
 */
export default function NewAgentWizard({ onClose }: NewAgentWizardProps) {
  const router = useRouter();
  const client = useQueryClient();
  const [step, setStep] = useState(1);
  const {
    clearErrors,
    formState: { errors, isSubmitted },
    getValues,
    handleSubmit,
    setValue,
    trigger,
    watch,
  } = useForm<WizardForm>({
    resolver: zodResolver(wizardSchema),
    defaultValues: {
      mode: "manual",
      name: "",
      db: {
        engine: "postgresql",
        host: "",
        port: 5432,
        name: "",
        user: "",
        pass: "",
        description: "",
      },
      rds: {
        host: "",
        engine: "postgresql",
        user: "postgres",
        pass: "",
        fetched: false,
        picked: [],
      },
      paste: "",
    },
  });
  const name = watch("name");
  const db = watch("db");
  const rds = watch("rds");
  const paste = watch("paste");
  // Once a submit has been tried, each edit re-checks the whole schema, so a
  // field leaves "Still needed" as soon as it is filled rather than on the next
  // try. The whole form, not the one path: these values are not registered
  // inputs, and a single-path check drops the other fields' errors.
  const recheck = () => {
    if (isSubmitted) void trigger();
  };
  const setName = (value: string) => {
    setValue("name", value);
    recheck();
  };
  const setPaste = (value: string) => {
    setValue("paste", value);
    recheck();
  };
  const setDb = (updater: (current: WizardForm["db"]) => WizardForm["db"]) => {
    setValue("db", updater(getValues("db")));
    recheck();
  };
  const setRds = (
    updater: (current: WizardForm["rds"]) => WizardForm["rds"],
  ) => {
    setValue("rds", updater(getValues("rds")));
    recheck();
  };
  const mode = watch("mode");
  const setMode = (value: Mode) => setValue("mode", value);
  /** What the schema says is still missing, once a submit has been tried. */
  const missing = errorMessages(errors);
  const [states, setStates] = useState<StepState[]>(
    PROVISION_STEPS.map(() => "idle"),
  );
  const [timings, setTimings] = useState<string[]>(
    PROVISION_STEPS.map(() => ""),
  );
  const { toast } = useToast();
  const ownerId = useOwnerId();
  const [failure, setFailure] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  /** Databases the RDS host reported, once discovery has run. */
  const [rdsFound, setRdsFound] = useState<string[]>([]);
  const [created, setCreated] = useState<{
    name: string;
    dbs: number;
    tables: number;
    id: string;
  } | null>(null);

  // Guards the async steps against setting state after unmount. Reset on mount:
  // React re-runs effects (Strict Mode mounts twice), and a flag left `true` by
  // the first cleanup would abort every later step.
  const cancelled = useRef(false);
  useEffect(() => {
    cancelled.current = false;
    return () => {
      cancelled.current = true;
    };
  }, []);

  /**
   * Re-reads the agent's databases until one reports tables, then corrects the
   * ready banner in place. Silent on failure — the count is a nicety, and the
   * agent is usable either way.
   */
  const pollTableCount = async (serviceId: string) => {
    for (const wait of TABLE_COUNT_POLLS) {
      await new Promise((resolve) => setTimeout(resolve, wait));
      if (cancelled.current) return;
      const rows = await fetchDatabases(serviceId).catch(() => null);
      if (cancelled.current) return;
      if (!rows) return;
      const total = countTables(rows);
      if (total > 0) {
        setCreated((current) =>
          current ? { ...current, tables: total } : current,
        );
        client.invalidateQueries({ queryKey: ["databases"] });
        return;
      }
    }
  };

  /**
   * Provisions the agent for real: create the NL2SQL agent, then add each
   * database (the service tests the connection and reads the schema as part of
   * that call). Each step flips to done only once its request returns, so the
   * progress list reports what actually happened.
   */
  const provision = async () => {
    if (!ownerId) return;

    setStep(3);
    const mark = (index: number, state: StepState, tookMs?: number) => {
      setStates((current) => current.map((s, i) => (i === index ? state : s)));
      if (tookMs !== undefined) {
        setTimings((current) =>
          current.map((t, i) => (i === index ? `${tookMs}ms` : t)),
        );
      }
    };

    const run = async <T,>(index: number, work: () => Promise<T>) => {
      mark(index, "run");
      const started = performance.now();
      const result = await work();
      mark(index, "done", Math.round(performance.now() - started));
      return result;
    };

    try {
      let connections: DbCredentials[];
      if (mode === "rds") {
        // The port follows the engine — an RDS MySQL host does not answer on
        // PostgreSQL's 5432.
        const rdsPort =
          ENGINES.find(([key]) => key === rds.engine)?.[2] ?? 5432;
        connections = rds.picked.map((dbName) => ({
          db_name: dbName,
          db_engine: rds.engine,
          db_host: rds.host,
          db_port: rdsPort,
          db_user: rds.user,
          db_password: rds.pass,
        }));
      } else if (mode === "file") {
        const parsed = parseConnections(paste);
        if (!parsed.connections.length) {
          throw new Error(
            parsed.errors[0] ?? "No connections could be read from those rows.",
          );
        }
        connections = parsed.connections;
      } else {
        connections = [
          {
            db_name: db.name,
            db_engine: db.engine,
            db_host: db.host,
            db_port: db.port,
            db_user: db.user,
            db_password: db.pass,
            description: db.description,
          },
        ];
      }

      // Every connection is checked before an agent exists, so a typo does not
      // leave a half-provisioned agent behind.
      await run(0, async () => {
        const results = await Promise.all(
          connections.map(async (connection) => ({
            connection,
            result: await testConnection(connection).catch(
              (error: unknown) => ({
                status: "error",
                message: apiMessage(error),
              }),
            ),
          })),
        );
        const bad = results.filter(
          (entry) => entry.result.status !== "connected",
        );
        if (bad.length) {
          throw new Error(
            bad
              .map(
                (entry) =>
                  `${entry.connection.db_name}: ${entry.result.message || "could not connect"}`,
              )
              .join(" · "),
          );
        }
      });

      const provisioned = await run(1, () =>
        createNl2sqlAgent({ ownerId, name: name.trim() || "Untitled agent" }),
      );

      const added = await run(2, () =>
        Promise.all(
          connections.map((connection) =>
            addDatabase(provisioned.service_id, connection),
          ),
        ),
      );

      /**
       * A description left blank is the Generate this step promises: the service
       * reads the schema and writes one. Started here and deliberately not
       * awaited — describing a large schema takes minutes, and the agent is
       * usable meanwhile. Settings → Configure shows the result, and offers
       * Generate again.
       */
      for (const database of added) {
        if (!database.description) {
          void generateDescription(provisioned.service_id, database.db_id)
            .then(() => {
              client.invalidateQueries({ queryKey: ["databases"] });
            })
            .catch(() => {
              // The agent is created either way; Settings → Configure →
              // Generate is where a failed description is retried.
            });
        }
      }

      const tables = countTables(added);
      setCreated({
        name: name.trim() || "Untitled agent",
        dbs: added.length,
        tables,
        id: provisioned.agent_id,
      });
      // The create call reports 0 until the schema read finishes; the list call
      // carries the real count, so ask it for one rather than claiming 0.
      if (tables === 0) void pollTableCount(provisioned.service_id);

      // The workspace list is cached for minutes and is not refetched on mount,
      // so without this the agent just created is missing from Home and from
      // every view the wizard hands off to — which is what dropped the shell's
      // rail and agent chip on the conversation it opens.
      client.invalidateQueries({ queryKey: ["agents"] });
      client.invalidateQueries({ queryKey: ["databases"] });
    } catch (error) {
      setFailure(apiMessage(error));
      setStates((current) =>
        current.map((state) => (state === "run" ? "idle" : state)),
      );
    }
  };

  const rail = (
    <div className="flex items-center gap-2">
      {(["Name", "Database", "Build"] as const).map((label, index) => {
        const number = index + 1;
        const done = step > number;
        const active = step === number;
        return (
          <span key={label} className="flex flex-1 items-center gap-2">
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                done
                  ? "bg-indigo-600 text-white"
                  : active
                    ? "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-500"
                    : "bg-slate-100 text-slate-500",
              )}
            >
              {done ? <Icon name="chk" className="size-3.5" /> : number}
            </span>
            <span
              className={cn(
                "text-xs font-medium",
                active || done ? "text-slate-900" : "text-slate-400",
              )}
            >
              {label}
            </span>
            {number < 3 && (
              <span
                className={cn(
                  "h-px flex-1",
                  done ? "bg-indigo-300" : "bg-slate-200",
                )}
              />
            )}
          </span>
        );
      })}
    </div>
  );

  // ── step 1: name ──────────────────────────────────────────────────────────
  if (step === 1) {
    return (
      <Modal
        wide
        title="New database agent"
        sub="You fill in the database. Everything the platform needs after that is done for you — no services to enable, nothing to link up."
        rail={rail}
        onClose={onClose}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => setStep(2)}>
              Next — connect a database
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field
            required
            label="What should this agent be called?"
            htmlFor="wzName"
            hint="Name it after the data it answers about — “Ecommerce Orders”, “Support Tickets”. People will see this on the share link."
          >
            <Input
              id="wzName"
              value={name}
              placeholder="e.g. Ecommerce Orders"
              onChange={setName}
            />
          </Field>
          <Banner icon="bolt" title="Defaults are already chosen">
            Models, prompts, memory and chart behaviour all start on settings
            that work. You can change any of it later under Settings → Advanced,
            but you never have to.
          </Banner>
        </div>
      </Modal>
    );
  }

  // ── step 2: database ──────────────────────────────────────────────────────
  if (step === 2) {
    const modes: Array<[Mode, string, string, IconName]> = [
      [
        "manual",
        "Enter credentials",
        "Host, port, user and password for one database",
        "db",
      ],
      [
        "file",
        "Import from a file",
        "Paste CSV or JSON to add several at once",
        "file",
      ],
      [
        "rds",
        "Discover on RDS",
        "Point at an RDS host and pick databases",
        "cloud",
      ],
    ];

    const descriptionField = (
      <Field
        label="Database description"
        htmlFor="wzDesc"
        hint="This is what decides whether a question is sent to this database, so plain business language beats schema jargon. Don’t know what to write? Leave it blank — we read a sample of your tables and write it for you."
      >
        <Input
          as="textarea"
          id="wzDesc"
          rows={4}
          placeholder="e.g. Live order and product data for the online store — orders, line items, customers and stock levels."
          value={db.description}
          onChange={(value) =>
            setDb((current) => ({ ...current, description: value }))
          }
        />
        <p className="pt-1 text-xs text-slate-400">
          Leave it empty and the service starts writing one from the schema as
          soon as the database is connected. It appears under Settings →
          Configure, where Generate runs it again.
        </p>
      </Field>
    );

    return (
      <Modal
        wide
        title="New database agent"
        sub="You fill in the database. Everything the platform needs after that is done for you — no services to enable, nothing to link up."
        rail={rail}
        onClose={onClose}
        footer={
          <>
            <span className="mr-auto text-xs text-rose-600">
              {missing.length > 0 && `Still needed: ${missing.join(", ")}`}
            </span>
            <Button variant="secondary" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={handleSubmit(provision)}>
              Test &amp; create agent
            </Button>
          </>
        }
      >
        <div
          role="tablist"
          aria-label="How to add the database"
          className="mb-5 grid gap-3 sm:grid-cols-3"
        >
          {modes.map(([key, title, hint, glyph]) => {
            const active = mode === key;
            return (
              <button
                key={key}
                role="tab"
                type="button"
                aria-selected={active}
                onClick={() => {
                  setMode(key);
                  clearErrors();
                }}
                className={cn(
                  "cursor-pointer rounded-lg border p-3 text-left transition-colors",
                  active
                    ? "border-indigo-500 bg-indigo-50/60"
                    : "border-slate-200 bg-white hover:border-slate-300",
                )}
              >
                <Icon
                  name={glyph}
                  className={cn(
                    "size-4",
                    active ? "text-indigo-600" : "text-slate-400",
                  )}
                />
                <span className="mt-2 block text-sm font-semibold text-slate-900">
                  {title}
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  {hint}
                </span>
              </button>
            );
          })}
        </div>

        {mode === "manual" && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field required label="Engine" htmlFor="wzEngine">
                <Select
                  id="wzEngine"
                  value={db.engine}
                  onChange={(value) => {
                    const engine = ENGINES.find(([key]) => key === value);
                    setDb((current) => ({
                      ...current,
                      engine: value,
                      port: engine?.[2] ?? current.port,
                    }));
                  }}
                  options={ENGINES.map(([value, label]) => ({ value, label }))}
                />
              </Field>
              <Field required label="Port" htmlFor="wzPort">
                <Input
                  id="wzPort"
                  type="number"
                  value={String(db.port)}
                  onChange={(value) =>
                    setDb((current) => ({ ...current, port: Number(value) }))
                  }
                />
              </Field>
            </div>
            <Field required label="Host" htmlFor="wzHost">
              <Input
                id="wzHost"
                className={MONO_INPUT}
                value={db.host}
                placeholder="db.internal.acme.com"
                error={missing.includes("Host")}
                onChange={(value) =>
                  setDb((current) => ({ ...current, host: value }))
                }
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field required label="Database name" htmlFor="wzDb">
                <Input
                  id="wzDb"
                  className={MONO_INPUT}
                  value={db.name}
                  placeholder="orders_prod"
                  error={missing.includes("Database name")}
                  onChange={(value) =>
                    setDb((current) => ({ ...current, name: value }))
                  }
                />
              </Field>
              <Field required label="Username" htmlFor="wzUser">
                <Input
                  id="wzUser"
                  className={MONO_INPUT}
                  value={db.user}
                  placeholder="analytics_ro"
                  error={missing.includes("Username")}
                  onChange={(value) =>
                    setDb((current) => ({ ...current, user: value }))
                  }
                />
              </Field>
            </div>
            <Field required label="Password" htmlFor="wzPass">
              <Input
                id="wzPass"
                type="password"
                autoComplete="off"
                value={db.pass}
                error={missing.includes("Password")}
                onChange={(value) =>
                  setDb((current) => ({ ...current, pass: value }))
                }
              />
            </Field>
            <Banner icon="bolt" title="Use a read-only user">
              Questions only ever read. A read-only user makes that structural
              rather than a promise.
            </Banner>
            {descriptionField}
          </div>
        )}

        {mode === "file" && (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              Adding several databases at once? One connection per line. Leave
              the description column empty and we generate it after the
              connection is tested.
            </p>
            <CodeBlock
              caption="Expected format"
              action={
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => setPaste(SAMPLE_ROWS)}
                >
                  Use this sample
                </Button>
              }
            >
              {SAMPLE_ROWS}
            </CodeBlock>
            <Field label="Rows" htmlFor="wzPaste">
              <Input
                as="textarea"
                id="wzPaste"
                className={MONO_INPUT}
                rows={5}
                placeholder="paste CSV or JSON here"
                value={paste}
                error={missing.includes("Connection rows")}
                onChange={setPaste}
              />
            </Field>
            <Banner tone="warn">
              Every row is tested before anything is saved. A row that fails is
              reported and skipped, so a bad line never leaves a half-connected
              database behind.
            </Banner>
          </div>
        )}

        {mode === "rds" && (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              Point at an RDS host once and pick the databases you want. The
              same credentials are reused for each.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field required label="RDS host" htmlFor="wzRHost">
                <Input
                  id="wzRHost"
                  className={MONO_INPUT}
                  value={rds.host}
                  placeholder="mydb.abc123.us-east-1.rds.amazonaws.com"
                  error={missing.includes("RDS host")}
                  onChange={(value) =>
                    setRds((current) => ({ ...current, host: value }))
                  }
                />
              </Field>
              <Field required label="Engine" htmlFor="wzREngine">
                <Select
                  id="wzREngine"
                  value={rds.engine}
                  onChange={(value) =>
                    setRds((current) => ({ ...current, engine: value }))
                  }
                  options={[
                    { value: "postgresql", label: "PostgreSQL" },
                    { value: "mysql", label: "MySQL" },
                  ]}
                />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field required label="Username" htmlFor="wzRUser">
                <Input
                  id="wzRUser"
                  className={MONO_INPUT}
                  value={rds.user}
                  onChange={(value) =>
                    setRds((current) => ({ ...current, user: value }))
                  }
                />
              </Field>
              <Field required label="Password" htmlFor="wzRPass">
                <Input
                  id="wzRPass"
                  type="password"
                  autoComplete="off"
                  value={rds.pass}
                  error={missing.includes("Password")}
                  onChange={(value) =>
                    setRds((current) => ({ ...current, pass: value }))
                  }
                />
              </Field>
            </div>
            <Button
              variant="secondary"
              startIcon={<Icon name="search" className="size-4" />}
              loading={discovering}
              loadingText="Fetching…"
              onClick={async () => {
                setDiscovering(true);
                try {
                  const found = await listRdsDatabases({
                    db_host: rds.host,
                    db_engine: rds.engine,
                    db_user: rds.user,
                    db_password: rds.pass,
                  });
                  setRdsFound(found);
                  setRds((current) => ({ ...current, fetched: true }));
                  toast.success(
                    `${found.length} database${found.length === 1 ? "" : "s"} on this host.`,
                  );
                } catch (error) {
                  toast.error(`Could not reach the host: ${apiMessage(error)}`);
                } finally {
                  setDiscovering(false);
                }
              }}
            >
              Fetch databases on this host
            </Button>
            {rds.fetched && (
              <div className="space-y-2">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Found {rdsFound.length} databases — pick what you need
                </div>
                {rdsFound.map((dbName) => (
                  <label
                    key={dbName}
                    className="flex cursor-pointer items-start gap-2 border-b border-slate-100 py-2 last:border-0"
                  >
                    <Checkbox
                      checked={rds.picked.includes(dbName)}
                      onCheckedChange={(checked: boolean) =>
                        setRds((current) => ({
                          ...current,
                          picked: checked
                            ? [...current.picked, dbName]
                            : current.picked.filter(
                                (value) => value !== dbName,
                              ),
                        }))
                      }
                    />
                    <span>
                      <span className="block font-mono text-sm text-slate-800">
                        {dbName}
                      </span>
                    </span>
                  </label>
                ))}
                <Banner icon="spark">
                  A description is written automatically for each database you
                  pick.
                </Banner>
              </div>
            )}
          </div>
        )}
      </Modal>
    );
  }

  // ── step 3: build ─────────────────────────────────────────────────────────
  return (
    <Modal
      wide
      title="New database agent"
      sub="You fill in the database. Everything the platform needs after that is done for you — no services to enable, nothing to link up."
      rail={rail}
      onClose={onClose}
      footer={
        created ? (
          <>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button
              onClick={() =>
                router.push(agentRoute(ROUTES.conversations, created.id))
              }
            >
              Ask a question →
            </Button>
          </>
        ) : failure ? (
          // A refused connection is the common case here, and the details that
          // caused it are one step back. Without a way to return, the only exit
          // from a typo was to close the wizard and start again.
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setFailure(null);
                setStates(PROVISION_STEPS.map(() => "idle"));
                setTimings(PROVISION_STEPS.map(() => ""));
                setStep(2);
              }}
            >
              Back to the database details
            </Button>
          </>
        ) : (
          <Button variant="secondary" disabled loading loadingText="Working…">
            Working…
          </Button>
        )
      }
    >
      <div className="space-y-1">
        {PROVISION_STEPS.map(([title, detail], index) => {
          const state = states[index];
          return (
            <div
              key={title}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 transition-colors",
                state === "run" && "bg-indigo-50/60",
                state === "done" && "bg-emerald-50/50",
              )}
            >
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                  state === "done"
                    ? "bg-emerald-100 text-emerald-700"
                    : state === "run"
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-slate-100 text-slate-500",
                )}
              >
                {state === "done" ? (
                  <Icon name="chk" className="size-3.5" />
                ) : (
                  index + 1
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-slate-800">
                  {title}
                </span>
                <span className="block text-xs text-slate-400">{detail}</span>
              </span>
              <span className="font-mono text-xs text-slate-400">
                {state === "run" ? "…" : timings[index]}
              </span>
            </div>
          );
        })}
      </div>

      {failure && (
        <Banner
          tone="error"
          className="mt-4"
          title="Could not create the agent"
        >
          {failure}
        </Banner>
      )}

      {created && (
        <Banner
          tone="ok"
          className="mt-4"
          title={`${created.name} is ready — ${
            created.tables > 0
              ? `${created.tables} table${created.tables === 1 ? "" : "s"} found across `
              : ""
          }${created.dbs} database${created.dbs === 1 ? "" : "s"}${
            created.tables > 0 ? "" : " connected"
          }`}
        >
          Every table is readable by default. Review that under Settings →
          Databases whenever you like, then start asking questions.
        </Banner>
      )}
    </Modal>
  );
}
