"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { isAxiosError } from "axios";

import Icon from "@/components/Icon";
import Banner from "@/components/ui/Banner";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import Modal from "@/components/ui/Modal";
import PageHeader from "@/components/ui/PageHeader";
import { RowsSkeleton } from "@/components/ui/Skeletons";
import {
  useCredentialProviders,
  useDeleteCredential,
  useOwnerCredentials,
} from "@/data/credentials";
import { ago } from "@/lib/format";
import { ROUTES } from "@/lib/routes";
import { TABLE } from "@/lib/tableStyles";
import { useToast } from "@/platform/components/ToastContext";
import { Button } from "@/platform/components/ui";
import { credentialErrorMessage } from "@/platform/lib/api-keys/api";
import { cn } from "@/platform/utils";

import { PROVIDER_NOTE, providerLabel } from "./constants";
import ProviderCredentialModal from "./ProviderCredentialModal";

/**
 * The workspace's provider keys — a board, the way the design artifact draws it:
 * three counts, then every stored key in one table.
 *
 * Laid out to match Document Intelligence's board, so the two products' key
 * screens read as one product: the same three tiles, the same masked cell with
 * an eye, the same icon actions.
 *
 * Keys are write-only. The service returns a mask and never the key — the one
 * endpoint that answers with plaintext is master-key only and 403s a browser
 * session even for its own key. So the eye uncovers the **mask**, and its
 * tooltip says exactly that rather than implying a key is behind it. Replacing a
 * key means typing the whole thing again, which is also the only way to be sure
 * what was stored.
 *
 * The column is "Updated", not the artifact's "Created": the row carries
 * `updated_at` alone.
 *
 * One thing this service does that its knowledge-side sibling does not: it
 * **checks the key with the provider before storing it**. A rejected key is a
 * 422 and nothing is saved (verified live: a junk Groq key answered "Key
 * validation failed: Invalid API key or authentication failed"). That is why a
 * stored key can be shown as verified without overstating anything.
 */

/**
 * `.iconbtn` from the design: 32 square, hairline border, sunken fill, 9px
 * radius. Shared by the eye and both row actions so they sit on one baseline.
 */
/**
 * The design's table cells: a 10px tracked header on the sunken fill, and 11/13
 * padding on both. `TABLE` covers the rest of this app's grids; only these two
 * measurements differ from it, so they are stated rather than the whole set
 * re-declared.
 */
const TH = cn(TABLE.th, "px-[13px] py-[10px] text-[10px]");
const TD = cn(TABLE.td, "px-[13px] py-[11px]");

const ICON_BTN =
  "inline-flex size-8 cursor-pointer items-center justify-center rounded-[9px] border border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-700";

/** "07 Jul 2026, 21:59" — the artifact's own stamp. */
const stampedOn = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

type Dialog =
  | { kind: "add" }
  | { kind: "replace"; provider: string }
  | { kind: "delete"; provider: string }
  | null;

/**
 * One headline count, at the design's own measurements.
 *
 * `.stat` there is a bordered card with no shadow — 13px/15px of padding, a
 * 10.5px uppercase label tracked at .06em, and a 22px display-face number. Label
 * over number and nothing else, so the `title` carries what the number means
 * rather than a caption line the design does not have.
 */
function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div
      className="rounded-lg border border-slate-200 bg-white px-[15px] py-[13px]"
      title={hint}
    >
      <span className="text-[10.5px] font-bold tracking-[0.06em] text-slate-400 uppercase">
        {label}
      </span>
      <div className="n2s-display mt-[3px] text-[22px] leading-none font-extrabold tracking-[-0.01em] tabular-nums text-slate-900">
        {value}
      </div>
    </div>
  );
}

export default function CredentialsView() {
  const { toast } = useToast();
  const credentials = useOwnerCredentials();
  const providers = useCredentialProviders();
  const remove = useDeleteCredential();

  const [dialog, setDialog] = useState<Dialog>(null);
  /**
   * Which rows have had their mask uncovered.
   *
   * The eye uncovers the mask, not the key: a key is encrypted on the way in and
   * the service never sends one back, so there is nothing else to reveal. Dots
   * by default, so a shoulder-surfer does not get even the last four.
   */
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [descending, setDescending] = useState(true);

  const rows = credentials.data;
  const now = Date.now();

  /**
   * The design's table orders by its date column and nothing else — Provider is
   * a plain label there — so that is the one header that carries a control.
   * Newest first; a row with no timestamp sorts last either way.
   */
  const sorted = useMemo(() => {
    const list = [...(rows ?? [])];
    list.sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    return descending ? list : list.reverse();
  }, [rows, descending]);

  const closeDialog = () => setDialog(null);
  const openAdd = () => setDialog({ kind: "add" });

  const confirmDelete = () => {
    if (dialog?.kind !== "delete") return;
    const target = dialog.provider;
    remove.mutate(target, {
      onSuccess: () => {
        toast.success(`Removed your ${providerLabel(target)} key`);
        closeDialog();
      },
      // A 404 here means the key is already gone — the service answers "No
      // credential stored for that provider" — so the message is the service's
      // own rather than a claim about what happened, and the dialog closes with
      // it: the row it was asking about does not exist, and the list is re-read
      // behind it. Any other failure keeps the dialog open, where the reason
      // sits next to the button that failed.
      onError: (error: unknown) => {
        toast.error(credentialErrorMessage(error, "Couldn't remove the key."));
        if (isAxiosError(error) && error.response?.status === 404)
          closeDialog();
      },
    });
  };

  // "Answer provider" is whatever the service lists as one, not a list here.
  const offered = new Set(providers.data ?? []);
  const answerKeys = (rows ?? []).filter((row) =>
    offered.has(row.provider),
  ).length;

  return (
    <>
      <Link
        href={ROUTES.home}
        className="mb-4 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-indigo-600"
      >
        <Icon name="back" className="size-4" /> Back to Dashboard
      </Link>

      <PageHeader
        title="Add Credentials"
        subtitle="Manage secure access keys for your AI providers and services."
        action={
          <Button
            startIcon={<Icon name="plus" className="size-4" />}
            onClick={openAdd}
          >
            Add New Credentials
          </Button>
        }
      />

      <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        <Stat
          label="Active keys"
          value={credentials.isLoading ? "—" : String((rows ?? []).length)}
          hint="Keys of your own in this workspace"
        />
        <Stat
          label="LLM providers"
          value={credentials.isLoading ? "—" : String(answerKeys)}
          hint="Providers that answer your questions"
        />
        {/*
         * Counted the way Document Intelligence counts it — everything that is
         * not an answer provider — rather than from a list written here. On this
         * service that is 0 today: `GET /owners/providers` answers
         * `llm_providers` alone, so there is no tooling to hold a key for, and
         * the foot line says so instead of leaving a bare zero to be read as a
         * setup someone forgot.
         */}
        <Stat
          label="Tools configured"
          value={
            credentials.isLoading
              ? "—"
              : String((rows ?? []).length - answerKeys)
          }
          hint="Anything that is not an answer provider — this service stores answer-model keys only, so it reads zero until that changes"
        />
      </div>

      <Banner tone="info" className="mb-4">
        A key is checked with its provider before it is stored, then held
        encrypted — only a mask of it ever comes back. Without a key of your
        own, agents run on the platform key.
      </Banner>

      <Card className="overflow-hidden">
        <CardHeader
          title="Configured Providers"
          note="every key on this account"
        />

        {credentials.isLoading ? (
          <CardBody>
            <RowsSkeleton rows={3} />
          </CardBody>
        ) : credentials.error ? (
          <CardBody className="text-sm text-rose-600">
            {credentialErrorMessage(
              credentials.error,
              "Couldn't load your keys.",
            )}
          </CardBody>
        ) : !rows?.length ? (
          /* The design's empty state is an icon, a line and a pointer at the
             header control — it does not repeat the button inside the card. */
          <EmptyState
            icon="key"
            title="No API keys configured yet"
            note='Click "Add New Credentials" to get started — until then, agents run on the platform key.'
          />
        ) : (
          <div className={TABLE.wrap}>
            <table className={TABLE.table}>
              <thead>
                <tr className={TABLE.headRow}>
                  <th className={TH}>Provider</th>
                  <th className={TH}>API key</th>
                  <th
                    className={cn(TH, "cursor-pointer select-none")}
                    aria-sort={descending ? "descending" : "ascending"}
                  >
                    <button
                      type="button"
                      className="inline-flex cursor-pointer items-center gap-1 uppercase"
                      onClick={() => setDescending((current) => !current)}
                      title="Sort by Updated"
                    >
                      Updated
                      <Icon
                        name="caret"
                        className={cn(
                          "size-3 text-slate-600 transition-transform",
                          !descending && "rotate-180",
                        )}
                      />
                    </button>
                  </th>
                  <th className={TH}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <tr key={row.provider} className={TABLE.row}>
                    <td className={TD}>
                      <span className="flex items-center gap-2.5">
                        <span className="flex size-[26px] shrink-0 items-center justify-center rounded-[7px] bg-indigo-50 text-indigo-600">
                          <Icon name="key" className="size-3.5" />
                        </span>
                        <span
                          className="font-semibold text-slate-900"
                          title={PROVIDER_NOTE}
                        >
                          {providerLabel(row.provider)}
                        </span>
                        {/*
                         * Only when the provider has stopped accepting the key.
                         * The artifact has no state column, and a "Verified"
                         * badge on every row says nothing — this service refuses
                         * to store a key the provider rejects, so verified is
                         * the only state a stored key normally has.
                         */}
                        {row.is_valid === false && (
                          <Chip tone="amber" size="sm">
                            <Icon name="warn" className="size-3" />
                            Provider rejected it
                          </Chip>
                        )}
                      </span>
                    </td>
                    <td className={TD}>
                      <span className="flex items-center gap-2">
                        <code className="font-mono text-[11.5px] tracking-[0.02em] text-slate-600">
                          {revealed[row.provider]
                            ? row.mask || "—"
                            : "•".repeat(Math.max(12, (row.mask ?? "").length))}
                        </code>
                        <button
                          type="button"
                          aria-pressed={Boolean(revealed[row.provider])}
                          aria-label={
                            revealed[row.provider]
                              ? `Hide the ${providerLabel(row.provider)} key`
                              : `Show the ${providerLabel(row.provider)} key`
                          }
                          title={
                            revealed[row.provider]
                              ? `Hide what is stored for ${providerLabel(row.provider)}`
                              : `Show what the service stored for ${providerLabel(row.provider)} — the key itself is never sent back`
                          }
                          onClick={() =>
                            setRevealed((current) => ({
                              ...current,
                              [row.provider]: !current[row.provider],
                            }))
                          }
                          className={ICON_BTN}
                        >
                          <Icon
                            name={revealed[row.provider] ? "eyeOff" : "eye"}
                            className="size-4"
                          />
                        </button>
                      </span>
                    </td>
                    <td
                      className={cn(TD, "whitespace-nowrap text-slate-500")}
                      title={
                        row.updated_at
                          ? `${ago(new Date(row.updated_at).getTime(), now)} ago`
                          : undefined
                      }
                    >
                      {row.updated_at ? stampedOn(row.updated_at) : "—"}
                    </td>
                    <td className={TD}>
                      {/*
                       * Icon-only, as the artifact and Document Intelligence
                       * draw them — the label lives in `aria-label` and the
                       * tooltip, so the row stays scannable without giving up
                       * the name of the action.
                       */}
                      <span className="flex items-center gap-1.5">
                        <button
                          type="button"
                          aria-label={`Edit the ${providerLabel(row.provider)} credential`}
                          title={`Edit the ${providerLabel(row.provider)} credential`}
                          onClick={() =>
                            setDialog({
                              kind: "replace",
                              provider: row.provider,
                            })
                          }
                          className={ICON_BTN}
                        >
                          <Icon name="cog" className="size-4" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete the ${providerLabel(row.provider)} credential`}
                          title={`Delete the ${providerLabel(row.provider)} credential`}
                          onClick={() =>
                            setDialog({
                              kind: "delete",
                              provider: row.provider,
                            })
                          }
                          className={cn(
                            ICON_BTN,
                            "text-rose-600 hover:bg-rose-50",
                          )}
                        >
                          <Icon name="trash" className="size-4" />
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {(dialog?.kind === "add" || dialog?.kind === "replace") && (
        <ProviderCredentialModal
          replaceProvider={
            dialog.kind === "replace" ? dialog.provider : undefined
          }
          onClose={closeDialog}
        />
      )}

      {dialog?.kind === "delete" && (
        <Modal
          title={`Delete your ${providerLabel(dialog.provider)} key?`}
          onClose={closeDialog}
          footer={
            <>
              <Button variant="outline" onClick={closeDialog}>
                Keep it
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={confirmDelete}
              >
                Delete credential
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-slate-600">
            The stored key is deleted outright — it cannot be recovered. From
            the next question onward, {providerLabel(dialog.provider)} usage in
            this workspace falls back to the platform key.
          </p>
        </Modal>
      )}
    </>
  );
}
