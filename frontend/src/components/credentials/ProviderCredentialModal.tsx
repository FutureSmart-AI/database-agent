"use client";

import { useMemo } from "react";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import Banner from "@/components/ui/Banner";
import Field from "@/components/ui/Field";
import Modal from "@/components/ui/Modal";
import {
  useCredentialProviders,
  useOwnerCredentials,
  useSaveCredential,
} from "@/data/credentials";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Input, Select } from "@/platform/components/ui";
import { credentialErrorMessage } from "@/platform/lib/api-keys/api";

import { MIN_API_KEY_LENGTH, providerLabel } from "./constants";

const credentialSchema = z.object({
  provider: z.string().trim().min(1, "Pick a provider."),
  api_key: z
    .string()
    .trim()
    .min(
      MIN_API_KEY_LENGTH,
      `Enter the provider's API key — at least ${MIN_API_KEY_LENGTH} characters.`,
    ),
});

type CredentialForm = z.infer<typeof credentialSchema>;

interface ProviderCredentialModalProps {
  onClose: () => void;
  /** When present, the provider is fixed and saving replaces its current key. */
  replaceProvider?: string;
}

/** Add or replace a provider key without leaving the current dashboard view. */
export default function ProviderCredentialModal({
  onClose,
  replaceProvider,
}: ProviderCredentialModalProps) {
  const { toast } = useToast();
  const providers = useCredentialProviders();
  const credentials = useOwnerCredentials();
  const save = useSaveCredential();
  const {
    control,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<CredentialForm>({
    resolver: zodResolver(credentialSchema),
    defaultValues: {
      provider: replaceProvider ?? "",
      api_key: "",
    },
  });

  const stored = useMemo(
    () => new Set((credentials.data ?? []).map((row) => row.provider)),
    [credentials.data],
  );
  /**
   * One key per provider on this account, so a provider that already has one is
   * shown disabled rather than dropped — as the design lists it. Dropping it
   * leaves a reader wondering where their provider went; this says where the
   * existing key lives instead.
   */
  const providerOptions = (providers.data ?? []).map((name) => ({
    value: name,
    label: stored.has(name)
      ? `${providerLabel(name)} — already added, edit it in the board`
      : providerLabel(name),
    disabled: stored.has(name),
  }));

  const submit = handleSubmit((values) => {
    // The taken option is disabled, but a keyboard or a stale render can still
    // reach it — and this service's save endpoint replaces a stored key without
    // asking, so the invariant is held here rather than by the option alone.
    if (!replaceProvider && stored.has(values.provider)) {
      setError("root.server", {
        message: `${providerLabel(values.provider)} already has a key here — edit that one instead.`,
      });
      return;
    }

    save.mutate(
      { provider: values.provider, api_key: values.api_key },
      {
        onSuccess: () => {
          toast.success(
            replaceProvider
              ? `Replaced your ${providerLabel(values.provider)} key`
              : `Saved your ${providerLabel(values.provider)} key`,
          );
          onClose();
        },
        onError: (error: unknown) =>
          setError("root.server", {
            message: credentialErrorMessage(error, "Couldn't save the key."),
          }),
      },
    );
  });

  return (
    <Modal
      title={
        replaceProvider
          ? `Edit credential — ${providerLabel(replaceProvider)}`
          : "Add New Credential"
      }
      sub="Enter your provider credentials securely below."
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="provider-credential-form"
            loading={save.isPending}
          >
            {replaceProvider ? "Save changes" : "Add Credential"}
          </Button>
        </>
      }
    >
      <form
        id="provider-credential-form"
        className="space-y-4"
        onSubmit={submit}
        noValidate
      >
        {errors.root?.server?.message && (
          <Banner tone="error">{errors.root.server.message}</Banner>
        )}

        <Field label="Provider Service" htmlFor="credential-provider" required>
          {replaceProvider ? (
            <>
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
                {providerLabel(replaceProvider)}
              </div>
              <span className="mt-1 block text-xs text-slate-500">
                The provider identifies the credential and cannot be changed
                here.
              </span>
            </>
          ) : (
            <Controller
              control={control}
              name="provider"
              render={({ field }) => (
                <Select
                  {...field}
                  id="credential-provider"
                  placeholder={
                    providers.isLoading
                      ? "Loading providers…"
                      : "Select a provider"
                  }
                  disabled={providers.isLoading}
                  options={providerOptions}
                  error={Boolean(errors.provider)}
                  errorMessage={errors.provider?.message}
                />
              )}
            />
          )}
        </Field>

        <Field
          label="API key"
          htmlFor="credential-api-key"
          required
          hint="Checked with the provider before it is stored — one it rejects is not saved. Stored encrypted and never read back, so changing it means pasting a new one in full."
        >
          <Controller
            control={control}
            name="api_key"
            render={({ field }) => (
              <Input
                {...field}
                id="credential-api-key"
                type="password"
                placeholder="sk-…"
                autoComplete="off"
                error={Boolean(errors.api_key)}
                errorMessage={errors.api_key?.message}
              />
            )}
          />
        </Field>
      </form>
    </Modal>
  );
}
