"use client";

import { useState } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import { testConnection, type DbCredentials } from "@/data/databases";
import type { AgentDatabase } from "@/data/types";
import { apiMessage } from "@/lib/apiError";
import { Button, Input, Select } from "@/platform/components/ui";

import { ENGINES } from "./constants";

interface DatabaseCredentialsModalProps {
  /** Omitted when adding — the form then starts empty. */
  db?: AgentDatabase;
  onClose: () => void;
  onSave: (credentials: DbCredentials) => void;
}

const credentialsSchema = z.object({
  db_name: z.string().trim().min(1),
  db_engine: z.string().min(1),
  db_host: z.string().trim().min(1),
  db_port: z.number().int().min(0),
  db_user: z.string().trim().min(1),
  db_password: z.string().min(1),
  description: z.string(),
});

type CredentialsForm = z.infer<typeof credentialsSchema>;

/**
 * Connection details for one database, used by both "Add database" and "Edit
 * credentials". Saving re-tests the connection, so the password is required on
 * edit too: it is never read back from the API.
 */
export default function DatabaseCredentialsModal({
  db,
  onClose,
  onSave,
}: DatabaseCredentialsModalProps) {
  const editing = Boolean(db);
  const { getValues, setValue, trigger, watch } = useForm<CredentialsForm>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: {
      db_name: db?.db_name ?? "",
      db_engine: db?.db_engine ?? "postgresql",
      db_host: db?.db_host ?? "",
      db_port: db?.db_port ?? 5432,
      db_user: db?.db_user ?? "",
      db_password: "",
      description: "",
    },
  });
  const [missing, setMissing] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
  /** Result of the last standalone test, shown in the modal. */
  const [tested, setTested] = useState<{ ok: boolean; message: string } | null>(
    null,
  );

  const form = watch();
  const update = (next: Partial<CredentialsForm>) => {
    setTested(null);
    Object.entries(next).forEach(([key, value]) =>
      setValue(key as keyof CredentialsForm, value as never),
    );
  };

  /** Fields the connection cannot be tested or saved without. */
  const gapsIn = () => {
    const gaps: string[] = [];
    if (!form.db_name.trim()) gaps.push("Database name");
    if (!form.db_host.trim()) gaps.push("Host");
    if (!form.db_user.trim()) gaps.push("Username");
    if (!form.db_password) gaps.push("Password");
    return gaps;
  };

  const submit = async () => {
    if (!(await trigger())) {
      setMissing(gapsIn());
      return;
    }
    const gaps = gapsIn();
    setMissing(gaps);
    if (gaps.length) return;
    onSave(getValues());
  };

  /**
   * `POST /nl2sql/api/v1/databases/test` — checks the credentials without
   * saving them, so a typo can be found before anything is stored.
   */
  const test = async () => {
    if (!(await trigger())) {
      setMissing(gapsIn());
      return;
    }
    const gaps = gapsIn();
    setMissing(gaps);
    if (gaps.length) return;
    setTesting(true);
    setTested(null);
    try {
      // Connection fields only — the description is not part of what /test reads.
      const { description: _description, ...credentials } = getValues();
      const result = await testConnection(credentials);
      setTested({
        ok: result.status === "connected",
        message: result.message || "Connected.",
      });
    } catch (error) {
      setTested({ ok: false, message: apiMessage(error) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Modal
      wide={!editing}
      title={
        editing
          ? `Edit credentials — ${db?.db_name}`
          : "Add database connection"
      }
      sub={
        editing
          ? "Saving tests the connection again with the new details."
          : "Configure engine, host, and credentials. The connection is tested, then its schema is read."
      }
      onClose={onClose}
      footer={
        <>
          <span className="mr-auto text-xs text-rose-600">
            {missing.length > 0 && `Still needed: ${missing.join(", ")}`}
          </span>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            loading={testing}
            loadingText="Testing…"
            startIcon={<Icon name="plug" className="size-4" />}
            onClick={test}
          >
            Test connection
          </Button>
          <Button onClick={submit}>
            {editing ? "Save & test" : "Add database"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field required label="Engine" htmlFor="credEngine">
            <Select
              id="credEngine"
              value={form.db_engine}
              onChange={(value) => {
                const engine = ENGINES.find(([key]) => key === value);
                update({
                  db_engine: value,
                  db_port: engine?.[2] ?? form.db_port,
                });
              }}
              options={ENGINES.map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field required label="Port" htmlFor="credPort">
            <Input
              id="credPort"
              type="number"
              value={String(form.db_port)}
              onChange={(value) => update({ db_port: Number(value) })}
            />
          </Field>
        </div>
        <Field required label="Host" htmlFor="credHost">
          <Input
            id="credHost"
            className="font-mono"
            placeholder="db.internal.acme.com"
            value={form.db_host}
            error={missing.includes("Host")}
            onChange={(value) => update({ db_host: value })}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field required label="Database name" htmlFor="credDb">
            <Input
              id="credDb"
              className="font-mono"
              placeholder="orders_prod"
              value={form.db_name}
              error={missing.includes("Database name")}
              onChange={(value) => update({ db_name: value })}
            />
          </Field>
          <Field required label="Username" htmlFor="credUser">
            <Input
              id="credUser"
              className="font-mono"
              placeholder="analytics_ro"
              value={form.db_user}
              error={missing.includes("Username")}
              onChange={(value) => update({ db_user: value })}
            />
          </Field>
        </div>
        <Field
          required
          label="Password"
          htmlFor="credPass"
          hint={
            editing
              ? "Stored encrypted and never returned, so it has to be entered again."
              : undefined
          }
        >
          <Input
            id="credPass"
            type="password"
            autoComplete="off"
            value={form.db_password}
            error={missing.includes("Password")}
            onChange={(value) => update({ db_password: value })}
          />
        </Field>
        {!editing && (
          <>
            <Field
              label="Database description"
              htmlFor="credDesc"
              hint="The router reads this to decide when to query this database, so plain business language beats schema jargon. Leave it blank and one is generated from the schema after the database is added."
            >
              <Input
                as="textarea"
                id="credDesc"
                rows={3}
                placeholder="Describe what this database contains. Or leave blank — auto-generate runs in the background after the database is added."
                value={form.description}
                onChange={(value) => update({ description: value })}
              />
            </Field>
            <Banner icon="spark">
              With no description, the database is added inactive and a
              description is auto-generated in the background.
            </Banner>
          </>
        )}
        {tested && (
          <Banner
            tone={tested.ok ? "ok" : "error"}
            title={tested.ok ? "Connection works" : "Could not connect"}
          >
            {tested.message}
          </Banner>
        )}
        <Banner icon="bolt" title="Use a read-only user">
          Questions only ever read. A read-only user makes that structural
          rather than a promise.
        </Banner>
      </div>
    </Modal>
  );
}
