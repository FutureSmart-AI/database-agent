"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  deleteNl2sqlAgent,
  resetNode,
  saveNodes,
  updateAgentParams,
} from "./agents";
import {
  addDatabase,
  addFewShot,
  checkAllDatabases,
  deleteDatabase,
  deleteFewShot,
  deleteTableDescriptions,
  generateDescription,
  generateTableDescription,
  generateTableDescriptions,
  saveFewShot,
  saveTables,
  setDatabaseActive,
  setDatabaseDescription,
  setTableVisibility,
  updateDatabase,
  type DbCredentials,
  type FewShotExample,
} from "./databases";
import type { Agent, NodeConfig } from "./types";

/**
 * Every write this app performs, as React Query mutations against the live API.
 *
 * Each one invalidates the queries whose data it changed, so a view re-reads
 * from the server rather than trusting a local guess about what the write did.
 */

/** Invalidates everything scoped to one agent's NL2SQL service. */
function useInvalidateService(serviceId: string | null | undefined) {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ["databases", serviceId] });
    client.invalidateQueries({ queryKey: ["tables", serviceId] });
    client.invalidateQueries({ queryKey: ["few-shot", serviceId] });
    client.invalidateQueries({ queryKey: ["nodes", serviceId] });
  };
}

export function useDatabaseMutations(serviceId: string | null | undefined) {
  const invalidate = useInvalidateService(serviceId);

  const add = useMutation({
    mutationFn: (credentials: DbCredentials) =>
      addDatabase(serviceId as string, credentials),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({
      dbId,
      credentials,
    }: {
      dbId: string;
      credentials: DbCredentials;
    }) => updateDatabase(serviceId as string, dbId, credentials),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (dbId: string) => deleteDatabase(serviceId as string, dbId),
    onSuccess: invalidate,
  });

  const setActive = useMutation({
    mutationFn: ({ dbId, isActive }: { dbId: string; isActive: boolean }) =>
      setDatabaseActive(serviceId as string, dbId, isActive),
    onSuccess: invalidate,
  });

  const checkAll = useMutation({
    mutationFn: () => checkAllDatabases(serviceId as string),
    onSuccess: invalidate,
  });

  const describe = useMutation({
    mutationFn: (dbId: string) =>
      generateDescription(serviceId as string, dbId),
    onSuccess: invalidate,
  });

  const saveDescription = useMutation({
    mutationFn: ({
      dbId,
      description,
    }: {
      dbId: string;
      description: string;
    }) => setDatabaseDescription(serviceId as string, dbId, description),
    onSuccess: invalidate,
  });

  return {
    add,
    update,
    remove,
    setActive,
    checkAll,
    describe,
    saveDescription,
  };
}

export function useTableMutations(
  serviceId: string | null | undefined,
  dbId: string | undefined,
) {
  const invalidate = useInvalidateService(serviceId);

  /**
   * `merge` picks the verb: a database that already has descriptions is updated
   * (PUT, so untouched tables keep theirs), one that has none is created (POST).
   */
  const save = useMutation({
    mutationFn: ({
      tables,
      merge,
    }: {
      tables: Array<{ table_name: string; description: string }>;
      merge: boolean;
    }) => saveTables(serviceId as string, dbId as string, tables, { merge }),
    onSuccess: invalidate,
  });

  const clearDescriptions = useMutation({
    mutationFn: (tableNames: string[]) =>
      deleteTableDescriptions(serviceId as string, dbId as string, {
        table_names: tableNames,
      }),
    onSuccess: invalidate,
  });

  const describeOne = useMutation({
    mutationFn: (tableName: string) =>
      generateTableDescription(serviceId as string, dbId as string, tableName),
  });

  const setVisibility = useMutation({
    mutationFn: ({
      tableName,
      isIncluded,
    }: {
      tableName: string;
      isIncluded: boolean;
    }) =>
      setTableVisibility(
        serviceId as string,
        dbId as string,
        tableName,
        isIncluded,
      ),
    onSuccess: invalidate,
  });

  const describeAll = useMutation({
    mutationFn: (overwrite: boolean = false) =>
      generateTableDescriptions(serviceId as string, dbId as string, {
        overwrite,
      }),
    onSuccess: invalidate,
  });

  return { save, setVisibility, describeAll, describeOne, clearDescriptions };
}

/** Few-shot saves report their own message, and may report a partial success. */
export function useFewShotMutations(
  serviceId: string | null | undefined,
  dbId: string | undefined,
) {
  const invalidate = useInvalidateService(serviceId);

  const save = useMutation({
    mutationFn: (examples: FewShotExample[]) =>
      saveFewShot(serviceId as string, dbId as string, examples),
    onSuccess: invalidate,
  });

  const add = useMutation({
    mutationFn: (examples: FewShotExample[]) =>
      addFewShot(serviceId as string, dbId as string, examples),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (questions: string[]) =>
      deleteFewShot(serviceId as string, dbId as string, {
        nl_queries: questions,
      }),
    onSuccess: invalidate,
  });

  return { save, add, remove };
}

/** Answer settings and share settings both live on the agent's params. */
export function useAgentMutations(agent: Agent | undefined) {
  const client = useQueryClient();
  const invalidateAgents = () =>
    client.invalidateQueries({ queryKey: ["agents"] });
  const invalidateNodes = () =>
    client.invalidateQueries({ queryKey: ["nodes", agent?.service_ref] });

  const saveParams = useMutation({
    mutationFn: (params: Record<string, unknown>) =>
      updateAgentParams(agent?.agent_id as string, params),
    onSuccess: invalidateAgents,
  });

  const saveNodeConfig = useMutation({
    mutationFn: (nodes: NodeConfig[]) =>
      saveNodes(agent?.service_ref as string, nodes),
    onSuccess: invalidateNodes,
  });

  const resetNodeConfig = useMutation({
    mutationFn: (nodeName: string) =>
      resetNode(agent?.service_ref as string, nodeName),
    onSuccess: invalidateNodes,
  });

  const remove = useMutation({
    mutationFn: (target: Agent) =>
      deleteNl2sqlAgent({
        agent_id: target.agent_id,
        service_ref: target.service_ref,
        service_count: target.service_count,
      }),
    onSuccess: invalidateAgents,
  });

  return { saveParams, saveNodeConfig, resetNodeConfig, remove };
}
