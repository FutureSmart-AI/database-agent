"use client";

import { useState } from "react";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import { listRdsDatabaseRows, type RdsDatabaseRow } from "@/data/agents";
import type { DbCredentials } from "@/data/databases";
import { apiMessage } from "@/lib/apiError";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Checkbox, Input, Select } from "@/platform/components/ui";

import { addDatabases, nameList } from "./addDatabases";
import { ENGINES, RDS_ENGINES } from "./constants";

/**
 * Connect several databases from one RDS host: credentials once, pick what you
 * want, then an optional description pass.
 *
 * Two steps rather than one form, because the pick list does not exist until the
 * host has been read — and because descriptions are worth a screen of their own
 * when a host hands back a dozen databases. Descriptions are optional here
 * (unlike the new-agent wizard, where one is asked for up front): a database
 * added without one is connected but stays inactive until the generated
 * description lands.
 */
export default function RdsDatabasesModal({
  serviceId,
  existingNames,
  onClose,
  onAdded,
}: {
  serviceId: string;
  /** Databases already on this agent — offered as checked and locked. */
  existingNames: string[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const { toast } = useToast();
  const [step, setStep] = useState<1 | 2>(1);
  const [engine, setEngine] = useState("postgresql");
  const [host, setHost] = useState("");
  const [user, setUser] = useState("postgres");
  const [password, setPassword] = useState("");
  const [found, setFound] = useState<RdsDatabaseRow[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);

  const already = new Set(existingNames);
  /** Only the picks that are not already connected are actually added. */
  const newOnes = picked.filter((name) => !already.has(name));
  const newFound = (found ?? []).filter((row) => !already.has(row.db_name));

  const fetchDatabases = async () => {
    const gaps: string[] = [];
    if (!host.trim()) gaps.push("RDS host");
    if (!user.trim()) gaps.push("Username");
    if (!password) gaps.push("Password");
    setMissing(gaps);
    if (gaps.length) return;

    setDiscovering(true);
    try {
      const rows = await listRdsDatabaseRows({
        db_host: host.trim(),
        db_engine: engine,
        db_user: user.trim(),
        db_password: password,
      });
      setFound(rows);
      // Pre-picked: everything with tables that is not connected already. A
      // system database (no tables) has nothing to answer questions about.
      setPicked(
        rows
          .filter(
            (row) =>
              !already.has(row.db_name) &&
              (row.table_count === null || row.table_count > 0),
          )
          .map((row) => row.db_name),
      );
      toast.success(
        `${rows.length} database${rows.length === 1 ? "" : "s"} on this host.`,
      );
    } catch (error) {
      toast.error(`Could not reach the host: ${apiMessage(error)}`);
    } finally {
      setDiscovering(false);
    }
  };

  const add = async () => {
    const port = ENGINES.find(([key]) => key === engine)?.[2] ?? 5432;
    const connections: DbCredentials[] = newOnes.map((name) => ({
      db_name: name,
      db_engine: engine,
      db_host: host.trim(),
      db_port: port,
      db_user: user.trim(),
      db_password: password,
      ...(descriptions[name]?.trim()
        ? { description: descriptions[name].trim() }
        : {}),
    }));

    setProgress(`Adding 1 of ${connections.length}…`);
    const { added, failed, describing } = await addDatabases(
      serviceId,
      connections,
      (done, total) =>
        setProgress(
          done < total ? `Adding ${done + 1} of ${total}…` : "Finishing…",
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
    onAdded();
    if (added.length && !failed.length) onClose();
  };

  if (step === 1) {
    return (
      <Modal
        wide
        title="Connect from RDS"
        sub="Enter RDS credentials, then select databases to add."
        onClose={onClose}
        footer={
          <>
            <span className="mr-auto text-xs text-rose-600">
              {missing.length > 0 && `Still needed: ${missing.join(", ")}`}
            </span>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={!newOnes.length} onClick={() => setStep(2)}>
              Next — add descriptions
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field required label="Engine" htmlFor="rdsEngine">
              <Select
                id="rdsEngine"
                value={engine}
                onChange={setEngine}
                options={RDS_ENGINES}
              />
            </Field>
            <Field required label="RDS host" htmlFor="rdsHost">
              <Input
                id="rdsHost"
                className="font-mono"
                placeholder="mydb.abc123.us-east-1.rds.amazonaws.com"
                value={host}
                error={missing.includes("RDS host")}
                onChange={setHost}
              />
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field required label="Username" htmlFor="rdsUser">
              <Input
                id="rdsUser"
                className="font-mono"
                value={user}
                error={missing.includes("Username")}
                onChange={setUser}
              />
            </Field>
            <Field required label="Password" htmlFor="rdsPass">
              <Input
                id="rdsPass"
                type="password"
                autoComplete="off"
                value={password}
                error={missing.includes("Password")}
                onChange={setPassword}
              />
            </Field>
          </div>
          <Button
            variant="secondary"
            startIcon={<Icon name="search" className="size-4" />}
            loading={discovering}
            loadingText="Fetching…"
            onClick={fetchDatabases}
          >
            {found
              ? `${found.length} database${found.length === 1 ? "" : "s"} found`
              : "Fetch databases"}
          </Button>

          {found && (
            <>
              <div className="overflow-hidden rounded-lg border border-slate-200">
                {found.map((row) => {
                  const locked = already.has(row.db_name);
                  return (
                    <label
                      key={row.db_name}
                      className="flex cursor-pointer items-start gap-2.5 border-b border-slate-100 px-3.5 py-2.5 last:border-0"
                    >
                      <Checkbox
                        checked={locked || picked.includes(row.db_name)}
                        disabled={locked}
                        onCheckedChange={(checked: boolean) =>
                          setPicked((current) =>
                            checked
                              ? [...current, row.db_name]
                              : current.filter((name) => name !== row.db_name),
                          )
                        }
                      />
                      <span className="flex-1">
                        <span className="block font-mono text-xs text-slate-800">
                          {row.db_name}
                        </span>
                        <span className="block text-xs text-slate-500">
                          {locked
                            ? "Already connected"
                            : row.table_count === null
                              ? "Schema read after it is added"
                              : row.table_count > 0
                                ? `${row.table_count} table${row.table_count === 1 ? "" : "s"}`
                                : "System database"}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
              <p className="text-xs text-slate-500">
                {newOnes.length} of {newFound.length} new database
                {newFound.length === 1 ? "" : "s"} selected.
              </p>
            </>
          )}
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      wide
      title="Add database descriptions"
      sub="Optional — or leave blank to auto-generate in the background."
      onClose={onClose}
      footer={
        <>
          <span className="mr-auto text-xs text-slate-500">{progress}</span>
          <Button variant="secondary" onClick={() => setStep(1)}>
            Back
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={Boolean(progress)}
            loadingText="Adding…"
            onClick={add}
          >
            Add {newOnes.length} database{newOnes.length === 1 ? "" : "s"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Banner icon="spark">
          Add a description or leave it blank to auto-generate one. A database
          without one is connected but stays inactive until a description is
          set.
        </Banner>
        {newOnes.map((name) => (
          <Field
            key={name}
            label={<span className="font-mono text-xs">{name}</span>}
            htmlFor={`rdsDesc-${name}`}
          >
            <Input
              as="textarea"
              id={`rdsDesc-${name}`}
              rows={2}
              placeholder="Describe what this database contains (optional)…"
              value={descriptions[name] ?? ""}
              onChange={(value) =>
                setDescriptions((current) => ({ ...current, [name]: value }))
              }
            />
          </Field>
        ))}
      </div>
    </Modal>
  );
}
