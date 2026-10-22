"use client";

import { useEffect, useRef, useState } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import { Card } from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import TabNav from "@/components/ui/TabNav";
import { fetchFewShot } from "@/data/databases";
import {
  useDatabaseMutations,
  useFewShotMutations,
  useTableMutations,
} from "@/data/mutations";
import type { AgentDatabase } from "@/data/types";
import { useTables } from "@/data/useAgents";
import { apiMessage } from "@/lib/apiError";
import { TABLE } from "@/lib/tableStyles";
// The same file parser the main dashboard's NL2SQL panels use: the service's own
// multipart upload rejects CSV and mis-maps JSON, so files are parsed here and
// sent as the structured array it does accept.
import {
  parseFewShotExamples,
  parseTableDescriptions,
} from "@/platform/components/nl2sql/dashboard/databases/parseNl2sqlImport";
import { useToast } from "@/platform/components/ToastContext";
import {
  Button,
  Checkbox,
  Modal as ConfirmModal,
  Input,
} from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import { CONFIG_TABS } from "./constants";

interface DatabaseConfigPanelProps {
  /** NL2SQL service id — every database route is keyed by it. */
  serviceId: string;
  db: AgentDatabase;
  onClose: () => void;
  onRetry: (db: AgentDatabase) => void;
  onEditCredentials: (db: AgentDatabase) => void;
}

type ConfigTab = "description" | "tables" | "examples";

const databaseConfigSchema = z.object({
  description: z.string(),
  tables: z.array(
    z.object({
      table_name: z.string(),
      description: z.string(),
      is_included: z.boolean(),
      column_count: z.number(),
    }),
  ),
  examples: z.array(
    z.object({
      q: z.string(),
      sql: z.string(),
      src: z.enum(["manual", "correction"]),
    }),
  ),
});
type DatabaseConfigForm = z.infer<typeof databaseConfigSchema>;

/** "18 Jun 2026, 14:30". */
const absT = (at: number) =>
  new Date(at).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

function PanelHeader({
  dbName,
  onClose,
}: {
  dbName: string;
  onClose: () => void;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-2.5 text-sm font-medium text-slate-700">
      <Icon name="cog" className="size-4 text-slate-400" />
      Configure — <span className="font-mono">{dbName}</span>
      <Button
        variant="secondary"
        size="sm"
        className="ml-auto"
        onClick={onClose}
      >
        Close
      </Button>
    </div>
  );
}

/** Downloadable samples, so the expected columns never have to be guessed. */
function SampleLinks({
  kind,
}: {
  kind: "table-descriptions" | "few-shot-examples";
}) {
  return (
    <span className="ml-auto text-xs text-slate-400">
      Sample:{" "}
      <a
        href={`/templates/nl2sql/${kind}.csv`}
        download
        className="text-indigo-600 hover:underline"
      >
        CSV
      </a>{" "}
      ·{" "}
      <a
        href={`/templates/nl2sql/${kind}.json`}
        download
        className="text-indigo-600 hover:underline"
      >
        JSON
      </a>
    </span>
  );
}

/**
 * The per-database Configure panel: its description (which the router reads to
 * decide where a question goes), which tables the agent may read, and the
 * few-shot examples that teach it this database's conventions.
 */
export default function DatabaseConfigPanel({
  serviceId,
  db,
  onClose,
  onRetry,
  onEditCredentials,
}: DatabaseConfigPanelProps) {
  const { toast } = useToast();
  const [tab, setTab] = useState<ConfigTab>("description");
  const { control, getValues, reset, setValue, watch } =
    useForm<DatabaseConfigForm>({
      resolver: zodResolver(databaseConfigSchema),
      defaultValues: {
        description: db.description ?? "",
        tables: [],
        examples: [],
      },
    });
  const { fields: tableFields, replace: replaceTables } = useFieldArray({
    control,
    name: "tables",
    keyName: "fieldId",
  });
  const {
    fields: exampleFields,
    append: appendExample,
    remove: removeExampleField,
    replace: replaceExamples,
  } = useFieldArray({ control, name: "examples", keyName: "fieldId" });
  const description = watch("description");
  const tables = watch("tables");
  const examples = watch("examples");

  const tableQuery = useTables(serviceId, db.db_id);
  const exampleQuery = useQuery({
    queryKey: ["few-shot", serviceId, db.db_id],
    queryFn: () => fetchFewShot(serviceId, db.db_id),
    enabled: Boolean(serviceId && db.db_id),
  });

  useEffect(() => {
    reset({
      description: db.description ?? "",
      tables: [],
      examples: [],
    });
  }, [db.db_id, db.description, reset]);
  useEffect(() => {
    if (tableQuery.data) replaceTables(tableQuery.data);
  }, [replaceTables, tableQuery.data]);
  useEffect(() => {
    if (exampleQuery.data) replaceExamples(exampleQuery.data);
  }, [exampleQuery.data, replaceExamples]);

  const databaseMutations = useDatabaseMutations(serviceId);
  const tableMutations = useTableMutations(serviceId, db.db_id);
  const fewShotMutations = useFewShotMutations(serviceId, db.db_id);
  const [selected, setSelected] = useState<string[]>([]);
  /** Examples selected for deletion, by row index. */
  const [selectedExamples, setSelectedExamples] = useState<number[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generatingTables, setGeneratingTables] = useState(false);
  /** Tables whose single-table description is being written right now. */
  const [rowGenerating, setRowGenerating] = useState<string[]>([]);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmDeleteExamples, setConfirmDeleteExamples] = useState(false);
  /** Which list the JSON paste box is filling, if it is open. */
  const [pasting, setPasting] = useState<"tables" | "examples" | null>(null);
  const [paste, setPaste] = useState("");
  const [pasteError, setPasteError] = useState<string | null>(null);
  const tableFile = useRef<HTMLInputElement>(null);
  const exampleFile = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  /**
   * Whether the stored set already has descriptions. The save verb and the
   * button label both follow it: a set with descriptions is updated (merge), an
   * empty one is created.
   */
  const storedTableDescriptions = (tableQuery.data ?? []).some((table) =>
    table.description.trim(),
  );
  const storedExamples = (exampleQuery.data ?? []).length > 0;

  /**
   * Starts the service's description job and polls it — the call reads a sample
   * of the schema, so it is asynchronous on the backend too.
   */
  const generate = async () => {
    setGenerating(true);
    try {
      const written = await databaseMutations.describe.mutateAsync(db.db_id);
      setValue("description", written);
      toast.success(
        "Description written from your schema. Review and save it.",
      );
    } catch (error) {
      toast.error(`Could not describe ${db.db_name}: ${apiMessage(error)}`);
    } finally {
      setGenerating(false);
    }
  };

  const saveDescription = async () => {
    try {
      await databaseMutations.saveDescription.mutateAsync({
        dbId: db.db_id,
        description,
      });
      toast.success(`Description saved for ${db.db_name}.`);
    } catch (error) {
      toast.error(`Could not save the description: ${apiMessage(error)}`);
    }
  };

  /**
   * `POST …/tables/generate` — the service describes the schema, then polls.
   * `overwrite` false fills only the blanks, so edited descriptions survive.
   */
  const generateTableDescriptions = async (overwrite: boolean) => {
    setConfirmRegenerate(false);
    setGeneratingTables(true);
    try {
      const described = await tableMutations.describeAll.mutateAsync(overwrite);
      replaceTables(described);
      toast.success(`Described ${described.length} tables.`);
    } catch (error) {
      toast.error(`Could not describe the tables: ${apiMessage(error)}`);
    } finally {
      setGeneratingTables(false);
    }
  };

  /** One table's description, written synchronously and dropped into the row. */
  const generateOne = async (tableName: string) => {
    if (rowGenerating.includes(tableName) || generatingTables) return;
    setRowGenerating((current) => [...current, tableName]);
    try {
      const written = await tableMutations.describeOne.mutateAsync(tableName);
      const index = getValues("tables").findIndex(
        (row) => row.table_name === tableName,
      );
      if (index >= 0) setValue(`tables.${index}.description`, written);
    } catch (error) {
      toast.error(`Could not describe ${tableName}: ${apiMessage(error)}`);
    } finally {
      setRowGenerating((current) =>
        current.filter((name) => name !== tableName),
      );
    }
  };

  const applyPaste = () => {
    try {
      const parsed = JSON.parse(paste);
      if (!Array.isArray(parsed)) throw new Error("Expected a JSON array.");

      if (pasting === "tables") {
        const byName = new Map(
          (parsed as Array<{ table_name?: string; description?: string }>)
            .filter((row) => row?.table_name)
            .map((row) => [row.table_name as string, row.description ?? ""]),
        );
        if (!byName.size) throw new Error("No table_name field found.");
        getValues("tables").forEach((table, index) => {
          if (byName.has(table.table_name)) {
            setValue(
              `tables.${index}.description`,
              byName.get(table.table_name) as string,
            );
          }
        });
        toast.success(`Applied ${byName.size} table description(s).`);
      } else {
        const rows = (
          parsed as Array<{
            q?: string;
            natural_query?: string;
            question?: string;
            sql?: string;
            sql_query?: string;
          }>
        )
          .map((row) => ({
            q: row.q ?? row.natural_query ?? row.question ?? "",
            sql: row.sql ?? row.sql_query ?? "",
            src: "manual" as const,
          }))
          .filter((row) => row.q && row.sql);
        if (!rows.length)
          throw new Error("Each row needs a question and its SQL.");
        appendExample(rows);
        toast.success(`Added ${rows.length} example(s). Review and Save.`);
      }
      setPasting(null);
      setPaste("");
      setPasteError(null);
    } catch (error) {
      setPasteError(
        error instanceof Error ? error.message : "That is not valid JSON.",
      );
    }
  };

  /**
   * Imports a CSV or JSON file.
   *
   * The file is parsed in the browser and sent as the structured array the
   * service accepts: its own multipart upload rejects CSV outright and mis-maps
   * JSON columns, which is why "upload" never worked here.
   */
  const importFile = async (file: File, kind: "tables" | "examples") => {
    setImporting(true);
    try {
      const text = await file.text();
      if (kind === "tables") {
        const { rows, error } = parseTableDescriptions(text, file.name);
        if (error) throw new Error(error);
        const result = await tableMutations.save.mutateAsync({
          tables: rows,
          merge: storedTableDescriptions,
        });
        toast.success(
          result.message ??
            `${storedTableDescriptions ? "Updated" : "Uploaded"} ${rows.length} table description${rows.length === 1 ? "" : "s"}.`,
        );
      } else {
        const { rows, error } = parseFewShotExamples(text, file.name);
        if (error) throw new Error(error);
        const result = await fewShotMutations.add.mutateAsync(
          rows.map((row) => ({
            q: row.natural_query,
            sql: row.sql_query,
            src: "manual" as const,
          })),
        );
        if (result.vector_store_error) {
          toast.warning(
            result.message ??
              "Saved, but the examples could not be indexed for retrieval yet.",
          );
        } else {
          toast.success(
            result.message ??
              `${storedExamples ? "Updated" : "Uploaded"} ${rows.length} example${rows.length === 1 ? "" : "s"}.`,
          );
        }
      }
    } catch (error) {
      toast.error(`Import failed: ${apiMessage(error)}`);
    } finally {
      setImporting(false);
    }
  };

  const persistTables = async () => {
    try {
      const result = await tableMutations.save.mutateAsync({
        tables: tables.map((table) => ({
          table_name: table.table_name,
          description: table.description,
        })),
        merge: storedTableDescriptions,
      });
      toast.success(
        result.message ??
          `Saved descriptions for ${tables.length} table${tables.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      toast.error(`Could not save the tables: ${apiMessage(error)}`);
    }
  };

  /** Clears the selected descriptions server-side; the tables themselves stay. */
  const clearSelectedDescriptions = async () => {
    setConfirmClear(false);
    try {
      const result =
        await tableMutations.clearDescriptions.mutateAsync(selected);
      getValues("tables").forEach((table, index) => {
        if (selected.includes(table.table_name)) {
          setValue(`tables.${index}.description`, "");
        }
      });
      setSelected([]);
      toast.success(
        result.message ??
          `Cleared ${selected.length} description${selected.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      toast.error(`Could not clear the descriptions: ${apiMessage(error)}`);
    }
  };

  /** Regenerates just the selected tables, one call each, for review. */
  const regenerateSelected = async () => {
    const names = [...selected];
    if (!names.length || generatingTables) return;
    setRowGenerating((current) => [...current, ...names]);
    const results = await Promise.allSettled(
      names.map(async (name) => {
        const written = await tableMutations.describeOne.mutateAsync(name);
        const index = getValues("tables").findIndex(
          (row) => row.table_name === name,
        );
        if (index >= 0) setValue(`tables.${index}.description`, written);
      }),
    );
    setRowGenerating((current) =>
      current.filter((name) => !names.includes(name)),
    );
    const failed = results.filter((row) => row.status === "rejected").length;
    if (failed) {
      toast.error(
        `Regenerated ${names.length - failed} of ${names.length}; ${failed} failed.`,
      );
    } else {
      toast.success(
        `Regenerated ${names.length} description${names.length === 1 ? "" : "s"} — review and Save.`,
      );
    }
  };

  const persistExamples = async () => {
    try {
      // POST merges into what is stored, which is the write the service
      // implements for both adding and editing.
      const result = await fewShotMutations.add.mutateAsync(examples);
      if (result.vector_store_error) {
        toast.warning(
          result.message ??
            "Saved, but the examples could not be indexed for retrieval yet.",
        );
      } else {
        toast.success(
          result.message ??
            `Saved ${examples.length} few-shot example${examples.length === 1 ? "" : "s"}.`,
        );
      }
    } catch (error) {
      toast.error(`Could not save the examples: ${apiMessage(error)}`);
    }
  };

  /** Deletes the selected examples server-side, then drops them from the list. */
  const deleteSelectedExamples = async () => {
    setConfirmDeleteExamples(false);
    const rows = selectedExamples
      .map((index) => examples[index])
      .filter(Boolean);
    const stored = new Set(
      (exampleQuery.data ?? []).map((row) => row.q.trim()),
    );
    const questions = rows
      .map((row) => row.q.trim())
      .filter((question) => stored.has(question));
    try {
      const result = questions.length
        ? await fewShotMutations.remove.mutateAsync(questions)
        : {};
      removeExampleField(selectedExamples);
      setSelectedExamples([]);
      toast.success(
        result.message ??
          `${rows.length} example${rows.length === 1 ? "" : "s"} deleted.`,
      );
    } catch (error) {
      toast.error(`Could not delete the examples: ${apiMessage(error)}`);
    }
  };

  /** Removes one example — from the server too when it was already stored. */
  const removeExample = async (index: number) => {
    const row = examples[index];
    const stored = (exampleQuery.data ?? []).some(
      (entry) => entry.q.trim() === row.q.trim(),
    );
    removeExampleField(index);
    setSelectedExamples([]);
    if (!stored || !row.q.trim()) return;
    try {
      const result = await fewShotMutations.remove.mutateAsync([row.q.trim()]);
      toast.success(result.message ?? "Example deleted.");
    } catch (error) {
      toast.error(`Could not delete the example: ${apiMessage(error)}`);
    }
  };

  // A database that cannot be reached gets a tab-free panel: nothing about
  // descriptions, tables or examples matters until the connection works.
  if (!db.reachable) {
    return (
      <div className="border-t border-gray-100 bg-slate-50/60">
        <PanelHeader dbName={db.db_name} onClose={onClose} />
        <div className="space-y-3 p-4">
          <Banner tone="error" title={`Can’t reach ${db.db_name}`}>
            Check the host, port and credentials, then retry the connection.
            Descriptions, tables and examples aren’t available until this
            database connects.
          </Banner>
          <div className="flex flex-wrap gap-2">
            <Button
              startIcon={<Icon name="ref" className="size-4" />}
              onClick={() => onRetry(db)}
            >
              Retry connection
            </Button>
            <Button
              variant="secondary"
              startIcon={<Icon name="key" className="size-4" />}
              onClick={() => onEditCredentials(db)}
            >
              Edit credentials
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const toggleVisibility = async (name: string) => {
    const table = tables.find((row) => row.table_name === name);
    if (!table) return;
    const isIncluded = !table.is_included;
    const index = tables.findIndex((row) => row.table_name === name);
    if (index < 0) return;
    setValue(`tables.${index}.is_included`, isIncluded);
    try {
      await tableMutations.setVisibility.mutateAsync({
        tableName: name,
        isIncluded,
      });
    } catch (error) {
      // Put the row back: the agent's view of the schema is the server's.
      setValue(`tables.${index}.is_included`, !isIncluded);
      toast.error(`Could not update ${name}: ${apiMessage(error)}`);
    }
  };

  return (
    <div className="border-t border-gray-100 bg-slate-50/60">
      <PanelHeader dbName={db.db_name} onClose={onClose} />

      <div className="p-4">
        <TabNav<ConfigTab>
          className="mb-4"
          label="Database configuration"
          activeTab={tab}
          onChange={setTab}
          tabs={CONFIG_TABS as Array<{ key: ConfigTab; label: string }>}
        />

        {tab === "description" && (
          <div className="space-y-3">
            {!description && (
              <Banner icon="spark" title="No description yet">
                The router reads it to decide when to use this database, so an
                agent answers better with one — but it is not required to save.
                Click Generate and the service writes it from your schema.
              </Banner>
            )}
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
              <Icon name="spark" className="size-4 shrink-0 text-blue-600" />
              <div className="min-w-56 flex-1 text-sm text-blue-900">
                <div className="font-semibold">Auto-generate description</div>
                <div className="text-[13px] opacity-90">
                  Samples tables, columns and a few rows to write it for you.
                </div>
              </div>
              <Button
                size="sm"
                loading={generating}
                loadingText="Reading schema…"
                startIcon={<Icon name="spark" className="size-4" />}
                onClick={generate}
              >
                Generate
              </Button>
            </div>
            <Field
              label="Database description"
              htmlFor={`desc-${db.db_id}`}
              hint={
                db.description_source
                  ? `${db.description_source === "auto" ? "Auto-generated" : "Written by hand"} · last updated ${
                      db.description_updated_at
                        ? absT(db.description_updated_at)
                        : "—"
                    }`
                  : "Not set yet."
              }
            >
              <Input
                as="textarea"
                id={`desc-${db.db_id}`}
                rows={6}
                value={description}
                onChange={(value) => setValue("description", value)}
              />
            </Field>
            <div className="flex justify-end">
              <Button
                loading={databaseMutations.saveDescription.isPending}
                loadingText="Saving…"
                onClick={saveDescription}
              >
                Save description
              </Button>
            </div>
          </div>
        )}

        {tab === "tables" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
              <Icon name="spark" className="size-4 shrink-0 text-blue-600" />
              <p className="min-w-56 flex-1 text-[13px] text-blue-900">
                Tables appear here automatically when the database connects.
                Switch one off and it is never read — not even for a question
                that names it.
              </p>
              <Button
                variant="secondary"
                size="sm"
                loading={generatingTables}
                loadingText="Describing…"
                startIcon={<Icon name="spark" className="size-4" />}
                onClick={() => generateTableDescriptions(false)}
              >
                Generate descriptions
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={generatingTables}
                onClick={() => setConfirmRegenerate(true)}
              >
                Regenerate all
              </Button>
            </div>

            <Card className="overflow-hidden shadow-none">
              <div className={TABLE.wrap}>
                <table className={TABLE.table}>
                  <thead>
                    <tr className={TABLE.headRow}>
                      <th className={cn(TABLE.th, "w-10")}>
                        <Checkbox
                          checked={
                            selected.length === tables.length &&
                            tables.length > 0
                          }
                          aria-label="Select every table"
                          onCheckedChange={(checked: boolean) =>
                            setSelected(
                              checked
                                ? tables.map((table) => table.table_name)
                                : [],
                            )
                          }
                        />
                      </th>
                      <th className={cn(TABLE.th, "w-44")}>Table</th>
                      <th className={TABLE.th}>
                        Description{" "}
                        <span className="font-normal normal-case tracking-normal">
                          (optional)
                        </span>
                      </th>

                      <th className={cn(TABLE.th, "w-28")}>Visibility</th>
                      <th className={cn(TABLE.th, "w-24")} />
                    </tr>
                  </thead>
                  <tbody>
                    {tableFields.map((field, index) => {
                      const table = tables[index] ?? field;
                      return (
                        <tr key={field.fieldId} className={TABLE.row}>
                          <td className={TABLE.td}>
                            <Checkbox
                              checked={selected.includes(table.table_name)}
                              aria-label={`Select ${table.table_name}`}
                              onCheckedChange={(checked: boolean) =>
                                setSelected((current) =>
                                  checked
                                    ? [...current, table.table_name]
                                    : current.filter(
                                        (name) => name !== table.table_name,
                                      ),
                                )
                              }
                            />
                          </td>
                          <td className={TABLE.td}>
                            <span className="block font-mono text-sm font-medium text-slate-800">
                              {table.table_name}
                            </span>
                            <span className="block text-[11px] text-slate-400">
                              {table.column_count} columns
                            </span>
                          </td>
                          <td className={TABLE.td}>
                            <Input
                              size="sm"
                              value={table.description}
                              placeholder="What does this table hold?"
                              aria-label={`Description for ${table.table_name}`}
                              onChange={(value) =>
                                setValue(`tables.${index}.description`, value)
                              }
                            />
                          </td>

                          <td className={TABLE.td}>
                            <button
                              type="button"
                              onClick={() => toggleVisibility(table.table_name)}
                              className={cn(
                                "inline-flex cursor-pointer items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                                table.is_included
                                  ? "bg-green-100 text-green-700"
                                  : "bg-rose-100 text-rose-700",
                              )}
                            >
                              {table.is_included ? (
                                <Icon name="chk" className="size-3" />
                              ) : (
                                <Icon name="x" className="size-3" />
                              )}
                              {table.is_included ? "Included" : "Excluded"}
                            </button>
                          </td>
                          <td className={TABLE.td}>
                            <span className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={`Describe ${table.table_name}`}
                                title="Write this table's description from its schema"
                                disabled={
                                  rowGenerating.includes(table.table_name) ||
                                  generatingTables
                                }
                                startIcon={
                                  rowGenerating.includes(table.table_name) ? (
                                    <Icon
                                      name="spinner"
                                      className="size-4 animate-spin"
                                    />
                                  ) : (
                                    <Icon name="spark" className="size-4" />
                                  )
                                }
                                onClick={() => generateOne(table.table_name)}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={`Clear the description for ${table.table_name}`}
                                title="Clear this description — the table itself stays"
                                disabled={!table.description}
                                startIcon={
                                  <Icon name="eraser" className="size-4" />
                                }
                                onClick={() =>
                                  setValue(`tables.${index}.description`, "")
                                }
                              />
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>

            {selected.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
                <Icon name="chk" className="size-4 text-slate-400" />
                {selected.length} table{selected.length === 1 ? "" : "s"}{" "}
                selected
                <span className="ml-auto flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={generatingTables}
                    startIcon={<Icon name="spark" className="size-4" />}
                    onClick={regenerateSelected}
                  >
                    Regenerate selected
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={tableMutations.clearDescriptions.isPending}
                    startIcon={<Icon name="trash" className="size-4" />}
                    onClick={() => setConfirmClear(true)}
                  >
                    Delete descriptions
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelected([])}
                  >
                    Deselect all
                  </Button>
                </span>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={tableFile}
                type="file"
                accept=".csv,.json,.txt"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void importFile(file, "tables");
                  event.target.value = "";
                }}
              />
              <Button
                variant="secondary"
                size="sm"
                loading={importing}
                loadingText={
                  storedTableDescriptions ? "Updating…" : "Uploading…"
                }
                startIcon={<Icon name="up2" className="size-4" />}
                onClick={() => tableFile.current?.click()}
              >
                {storedTableDescriptions
                  ? "Update descriptions"
                  : "Upload descriptions"}{" "}
                (CSV / JSON)
              </Button>
              <Button
                variant="secondary"
                size="sm"
                startIcon={<Icon name="up2" className="size-4" />}
                onClick={() => setPasting("tables")}
              >
                Paste JSON
              </Button>
              <Button
                loading={tableMutations.save.isPending}
                loadingText="Saving…"
                onClick={persistTables}
              >
                Save
              </Button>
              <SampleLinks kind="table-descriptions" />
            </div>
          </div>
        )}

        {tab === "examples" && (
          <div className="space-y-3">
            <Banner icon="spark">
              These examples belong to{" "}
              <span className="font-mono">{db.db_name}</span>. Once the router
              picks this database, the closest examples are used to write the
              SQL — and a correction on any answer lands here automatically.
            </Banner>

            {selectedExamples.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm">
                <span className="font-medium text-rose-700">
                  {selectedExamples.length} selected
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedExamples([])}
                  >
                    Clear
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={fewShotMutations.remove.isPending}
                    startIcon={<Icon name="trash" className="size-4" />}
                    onClick={() => setConfirmDeleteExamples(true)}
                  >
                    Delete selected
                  </Button>
                </span>
              </div>
            )}

            <Card className="overflow-hidden shadow-none">
              {examples.length > 0 ? (
                <div className={TABLE.wrap}>
                  <table className={TABLE.table}>
                    <thead>
                      <tr className={TABLE.headRow}>
                        <th className={cn(TABLE.th, "w-10")}>
                          <Checkbox
                            checked={
                              selectedExamples.length === examples.length &&
                              examples.length > 0
                            }
                            aria-label="Select every example"
                            onCheckedChange={(checked: boolean) =>
                              setSelectedExamples(
                                checked
                                  ? examples.map((_, index) => index)
                                  : [],
                              )
                            }
                          />
                        </th>
                        <th className={cn(TABLE.th, "w-[36%]")}>Question</th>
                        <th className={TABLE.th}>SQL</th>
                        <th className={cn(TABLE.th, "w-12")} />
                      </tr>
                    </thead>
                    <tbody>
                      {exampleFields.map((field, index) => {
                        const example = examples[index] ?? field;
                        return (
                          <tr key={field.fieldId} className={TABLE.row}>
                            <td className={TABLE.td}>
                              <Checkbox
                                checked={selectedExamples.includes(index)}
                                aria-label={`Select example ${index + 1}`}
                                onCheckedChange={(checked: boolean) =>
                                  setSelectedExamples((current) =>
                                    checked
                                      ? [...current, index]
                                      : current.filter((row) => row !== index),
                                  )
                                }
                              />
                            </td>
                            <td className={TABLE.td}>
                              <Input
                                size="sm"
                                value={example.q}
                                aria-label={`Question for example ${index + 1}`}
                                onChange={(value) =>
                                  setValue(`examples.${index}.q`, value)
                                }
                              />
                            </td>
                            <td className={TABLE.td}>
                              <Input
                                size="sm"
                                className="font-mono"
                                value={example.sql}
                                aria-label={`SQL for example ${index + 1}`}
                                onChange={(value) =>
                                  setValue(`examples.${index}.sql`, value)
                                }
                              />
                            </td>
                            <td className={TABLE.td}>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label="Remove example"
                                startIcon={
                                  <Icon name="trash" className="size-4" />
                                }
                                onClick={() => void removeExample(index)}
                              />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  icon="spark"
                  title="No examples yet"
                  note="Two or three good examples teach the conventions your business uses — which date column counts, how revenue is defined, which rows to leave out."
                />
              )}
            </Card>

            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={exampleFile}
                type="file"
                accept=".csv,.json,.txt"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void importFile(file, "examples");
                  event.target.value = "";
                }}
              />
              <Button
                variant="secondary"
                size="sm"
                startIcon={<Icon name="plus" className="size-4" />}
                onClick={() => appendExample({ q: "", sql: "", src: "manual" })}
              >
                Add example
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={importing}
                loadingText={storedExamples ? "Updating…" : "Uploading…"}
                startIcon={<Icon name="up2" className="size-4" />}
                onClick={() => exampleFile.current?.click()}
              >
                {storedExamples ? "Update examples" : "Upload examples"} (CSV /
                JSON)
              </Button>
              <Button
                variant="secondary"
                size="sm"
                startIcon={<Icon name="up2" className="size-4" />}
                onClick={() => setPasting("examples")}
              >
                Paste JSON
              </Button>
              <Button
                loading={fewShotMutations.add.isPending}
                loadingText="Saving…"
                onClick={persistExamples}
              >
                {storedExamples ? "Update" : "Save"}
              </Button>
              <SampleLinks kind="few-shot-examples" />
            </div>
          </div>
        )}
      </div>

      {pasting && (
        <Modal
          title={
            pasting === "tables"
              ? "Paste table descriptions"
              : "Paste few-shot examples"
          }
          sub={
            pasting === "tables"
              ? "A JSON array of { table_name, description }. Tables not in the list are left alone."
              : "A JSON array of { natural_query, sql_query }. Each row is added to this database's examples."
          }
          onClose={() => {
            setPasting(null);
            setPasteError(null);
          }}
          footer={
            <>
              <span className="mr-auto text-xs text-rose-600">
                {pasteError}
              </span>
              <Button
                variant="secondary"
                onClick={() => {
                  setPasting(null);
                  setPasteError(null);
                }}
              >
                Cancel
              </Button>
              <Button onClick={applyPaste}>Apply</Button>
            </>
          }
        >
          <Input
            as="textarea"
            rows={10}
            className="font-mono"
            aria-label="JSON to import"
            placeholder={
              pasting === "tables"
                ? '[{ "table_name": "orders", "description": "One row per order" }]'
                : '[{ "natural_query": "revenue last month", "sql_query": "SELECT …" }]'
            }
            value={paste}
            error={Boolean(pasteError)}
            onChange={(value) => {
              setPaste(value);
              setPasteError(null);
            }}
          />
        </Modal>
      )}

      <ConfirmModal
        open={confirmRegenerate}
        variant="danger"
        maxWidth="md"
        title="Regenerate every description?"
        confirmText="Regenerate all"
        confirmLoading={generatingTables}
        onConfirm={() => generateTableDescriptions(true)}
        onCancel={() => setConfirmRegenerate(false)}
      >
        <p className="text-sm text-slate-600">
          Every table's description is written again from the schema, replacing
          the ones you edited. This cannot be undone.
        </p>
      </ConfirmModal>

      <ConfirmModal
        open={confirmClear}
        variant="danger"
        maxWidth="md"
        title={`Delete ${selected.length} description${selected.length === 1 ? "" : "s"}?`}
        confirmText="Delete"
        confirmLoading={tableMutations.clearDescriptions.isPending}
        onConfirm={clearSelectedDescriptions}
        onCancel={() => setConfirmClear(false)}
      >
        <p className="text-sm text-slate-600">
          The descriptions are cleared. The tables themselves stay listed and
          keep their visibility.
        </p>
      </ConfirmModal>

      <ConfirmModal
        open={confirmDeleteExamples}
        variant="danger"
        maxWidth="md"
        title={`Delete ${selectedExamples.length} example${selectedExamples.length === 1 ? "" : "s"}?`}
        confirmText="Delete"
        confirmLoading={fewShotMutations.remove.isPending}
        onConfirm={deleteSelectedExamples}
        onCancel={() => setConfirmDeleteExamples(false)}
      >
        <p className="text-sm text-slate-600">
          The agent stops being shown these examples when it writes SQL for this
          database.
        </p>
      </ConfirmModal>
    </div>
  );
}
