"use client";

import { useRef, useState } from "react";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import CodeBlock from "@/components/ui/CodeBlock";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import TabNav from "@/components/ui/TabNav";
import { parseConnections } from "@/lib/parseConnections";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Input } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import { addDatabases, nameList } from "./addDatabases";
import {
  IMPORT_CSV_TEMPLATE,
  IMPORT_JSON_TEMPLATE,
  IMPORT_TABS,
  type ImportTab,
} from "./constants";

/** Saves the template the parser accepts, so a first import cannot mis-shape it. */
function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Bulk-add: several connections from a CSV or JSON file, or from pasted rows.
 *
 * The file is read and parsed here rather than uploaded — the service takes one
 * connection per call, and parsing in the browser is what lets a bad row be
 * named before anything is saved. Same parser as the new-agent flow, so a file
 * that works there works here.
 */
export default function ImportDatabasesModal({
  serviceId,
  onClose,
  onImported,
}: {
  serviceId: string;
  onClose: () => void;
  /** Called once the import finishes, so the list can be re-read. */
  onImported: () => void;
}) {
  const { toast } = useToast();
  const [tab, setTab] = useState<ImportTab>("csv");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const parsed = text.trim() ? parseConnections(text) : null;
  const ready = Boolean(parsed?.connections.length && !parsed.errors.length);

  const readFile = async (file: File) => {
    setFileName(file.name);
    setText(await file.text());
  };

  const switchTab = (next: ImportTab) => {
    setTab(next);
    setText("");
    setFileName(null);
  };

  const importAll = async () => {
    if (!parsed) return;
    if (!parsed.connections.length) {
      toast.error(parsed.errors[0] ?? "No connections could be read.");
      return;
    }
    // A row that cannot be read is refused rather than dropped in silence — a
    // half-imported set is worse than one that was never started.
    if (parsed.errors.length) {
      toast.error(parsed.errors.join(" "));
      return;
    }

    setProgress(`Importing 1 of ${parsed.connections.length}…`);
    const { added, failed, describing } = await addDatabases(
      serviceId,
      parsed.connections,
      (done, total) =>
        setProgress(
          done < total ? `Importing ${done + 1} of ${total}…` : "Finishing…",
        ),
    );
    setProgress(null);

    if (added.length) {
      const describingNote = describing.length
        ? ` ${describing.length === 1 ? "A description is" : "Descriptions are"} being generated in the background.`
        : "";
      toast.success(
        `${nameList(added.map((db) => db.db_name))} added — schema read automatically.${describingNote}`,
      );
    }
    if (failed.length) {
      toast.error(
        `Could not add ${failed.map((row) => `${row.db_name} (${row.message})`).join(" · ")}`,
      );
    }
    onImported();
    if (added.length && !failed.length) onClose();
  };

  const templateTab = tab === "json" || tab === "paste" ? "json" : "csv";

  return (
    <Modal
      wide
      title="Import databases using CSV or JSON"
      sub="Bulk-add multiple database connections from CSV or JSON."
      onClose={onClose}
      footer={
        <>
          <span className="mr-auto text-xs text-slate-500">
            {progress ??
              (parsed?.errors.length
                ? ""
                : parsed?.connections.length
                  ? `${parsed.connections.length} connection${parsed.connections.length === 1 ? "" : "s"} read.`
                  : "")}
          </span>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            startIcon={<Icon name="file" className="size-4" />}
            onClick={() =>
              templateTab === "csv"
                ? download(
                    "databases-template.csv",
                    IMPORT_CSV_TEMPLATE,
                    "text/csv",
                  )
                : download(
                    "databases-template.json",
                    IMPORT_JSON_TEMPLATE,
                    "application/json",
                  )
            }
          >
            Download template
          </Button>
          <Button
            disabled={!ready}
            loading={Boolean(progress)}
            loadingText="Importing…"
            onClick={importAll}
          >
            Import databases
          </Button>
        </>
      }
    >
      <TabNav<ImportTab>
        className="mb-5"
        label="Import format"
        activeTab={tab}
        onChange={switchTab}
        tabs={IMPORT_TABS}
      />

      <div className="space-y-4">
        {tab === "paste" ? (
          <Field label="Paste CSV or JSON" htmlFor="impPaste">
            <Input
              as="textarea"
              id="impPaste"
              rows={7}
              className="font-mono"
              placeholder={
                '[{"engine":"postgresql","host":"db1.acme.com","port":5432,"database":"orders_prod","user":"admin","password":"secret","description":"E-commerce orders"}]'
              }
              value={text}
              onChange={setText}
            />
          </Field>
        ) : (
          <>
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                const file = event.dataTransfer.files[0];
                if (file) void readFile(file);
              }}
              className={cn(
                "rounded-lg border-[1.5px] border-dashed p-8 text-center transition-colors",
                dragging
                  ? "border-indigo-400 bg-indigo-50/60"
                  : "border-slate-300 bg-slate-50",
              )}
            >
              <div className="text-sm font-semibold text-slate-700">
                Drop {tab === "csv" ? "CSV" : "JSON"} file here
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                or{" "}
                <button
                  type="button"
                  className="cursor-pointer font-medium text-indigo-600 underline"
                  onClick={() => fileInput.current?.click()}
                >
                  click to browse
                </button>
              </div>
              {fileName && (
                <div className="mt-3 font-mono text-xs text-slate-600">
                  <Icon name="file" className="mr-1 inline size-3.5" />
                  {fileName}
                </div>
              )}
              <input
                ref={fileInput}
                type="file"
                hidden
                accept={
                  tab === "csv" ? ".csv,text/csv" : ".json,application/json"
                }
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void readFile(file);
                  // Cleared so picking the same file again still fires a change.
                  event.target.value = "";
                }}
              />
            </div>
            <CodeBlock caption="Expected format">
              {tab === "csv" ? IMPORT_CSV_TEMPLATE : IMPORT_JSON_TEMPLATE}
            </CodeBlock>
          </>
        )}

        {parsed?.errors.length ? (
          <Banner tone="error" title="These rows cannot be imported">
            {parsed.errors.join(" ")}
          </Banner>
        ) : (
          <p className="text-xs text-slate-500">
            Leave the description column blank to auto-generate it after import.
            Column order does not matter, and each connection is tested as it is
            added.
          </p>
        )}
      </div>
    </Modal>
  );
}
