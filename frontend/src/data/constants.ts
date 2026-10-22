/**
 * Static option lists the Settings form offers.
 *
 * These are choices the UI presents, not data: the values map onto the agent's
 * `config.agent_params` fields, and everything an agent actually holds is read
 * from the API.
 */

/** Answer features, keyed by their `agent_params` field. */
export const FEATURES: Array<[key: string, title: string, hint: string]> = [
  [
    "show_sources",
    "Show sources",
    "Adds the executed SQL and the rows it read under each answer.",
  ],
  [
    "follow_up",
    "Follow-up questions",
    "Suggests the next questions worth asking.",
  ],
  [
    "chart_output",
    "Charts",
    "Draws a chart when the answer is easier to read as one.",
  ],
  // Absent on purpose, because `AgentParamsRequest` on the NL2SQL service has no
  // field for them: "Remember context" (`memory_enabled`), "Remember across
  // conversations" (`global_memory`) and "Raw response" (`raw_response`). They
  // only ever described orchestration behaviour this product no longer routes
  // through. Whatever an agent still has stored is left untouched — Settings
  // sends only the fields the service defines — so they can come back unchanged
  // once the service exposes them.
];
