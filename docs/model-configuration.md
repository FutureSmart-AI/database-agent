# Model configuration

The default installation needs only `OPENAI_API_KEY`. No node configuration is
required. `backend/model_config.json` selects `futuresmart-recommended-v1`, whose
assignments live in `backend/model_profiles/futuresmart-recommended-v1.json`.
The profile version fixes our assignments and options, not the provider's model
weights: these model IDs are aliases, not invented dated snapshots.

| Operation | Recommended model |
| --- | --- |
| Database routing, table selection, SQL generation, pandas planning | gpt-6.1-sol |
| Query routing, descriptions, answer presentation, pandas routing | gpt-6-luna |
| HC entity extraction, batch expansion and candidate refinement | gpt-6-luna |
| Chart routing, chart suggestion and graph mapping | gpt-6-luna |
| Follow-up suggestions, CSV presentation, optional report analysis | gpt-6-luna |
| New few-shot and high-cardinality embeddings | text-embedding-3-small, 1536 dimensions |

Sol uses Responses with `reasoning_effort=low`, no temperature, and stateless
requests. Luna uses Chat Completions with explicit `reasoning_effort=none`.
These tool-calling requirements are documented in the
[OpenAI model guide](https://developers.openai.com/api/docs/guides/latest-model).
The existing prompts, schemas, additional instructions and SQL guards remain.
Default request limits are timeout45 seconds, retries0, and max output8192 tokens
for Sol or2048 for other models; existing tighter call limits remain effective.

## Advanced operation overrides

Edit `backend/model_config.json`. Compose mounts that file read-only into the
backend; it is never a frontend configuration file. For a direct Python process,
`MODEL_CONFIG_PATH` can select another file. All compatibility loaders use that
same resolver. A file mounted elsewhere in a container must also be exposed with
your own Compose override.

```json
{
  "profile": "futuresmart-recommended-v1",
  "overrides": {
    "sql_agent.rephrase_answer": {
      "provider": "openai",
      "model": "gpt-6.1-sol",
      "endpoint": "responses",
      "reasoning_effort": "high"
    },
    "chart_agent.mapping": {
      "provider": "google",
      "model": "YOUR_SUPPORTED_GOOGLE_MODEL"
    }
  }
}
```

The Google override requires `GOOGLE_API_KEY`; no Google key is needed when it
is absent. Use provider model IDs supported by your account and by the existing
operation's structured-output contract. Unknown providers, partial bindings,
unavailable SDKs, missing keys and known incompatible options fail explicitly.
There is no automatic switch to another provider/model after a failure.

Resolution order is shipped profile → single-provider chat binding → file
operation override → existing stored agent node override. When changing a
provider/model binding, inherited endpoint/reasoning/temperature options reset
to capabilities for the selected model. Explicit valid options take precedence.
Sol temperature and Sol Chat tools are rejected; remove temperature or use null.
Luna Responses with reasoning above `none` also requires `temperature: null`;
keeping an inherited temperature for that combination is rejected explicitly.
Stored node overrides retain provider/model/nullable temperature. Endpoint and
reasoning options belong in the file, without a database migration. The API's
default node settings come from this resolver, while prompts retain their
existing behavior. A failed stored-configuration read does not select defaults.

Operation names are listed in the shipped profile. Existing node names map as
follows: `sql_gen`→`sql_agent.sql_generation`, `final_answer_node`→
`sql_agent.rephrase_answer`, and `chart_agent`→chart suggestion, routing and
mapping. The existing stored chart override applies to all three; separate file
overrides can assign their defaults independently. Legacy nested JSON remains
readable; its `fallback` binding is only the old CSV presentation setting and
does not authorize a fallback call. Invalid legacy options must be corrected.

## Evaluating a configuration before changing it

Put the candidate in `tests/evaluation/model_eval/configs/<name>.json` (the same format as
this file) and run the **Model evaluation** workflow with it beside `recommended-v1`. It asks
18 questions over two synthetic databases through the real API and reports accuracy against
ground truth, SQL validity, latency and estimated cost per configuration; see
[the evaluation README](../tests/evaluation/model_eval/README.md). Change the shipped profile
only after repeated runs and a review of the failures.

## Another chat provider

```json
{
  "profile": "futuresmart-recommended-v1",
  "single_provider": {
    "provider": "groq",
    "model": "openai/gpt-oss-120b"
  },
  "overrides": {}
}
```

This changes chat operations that support the provider and schema. Existing
OpenAI, Google (`gemini` alias), Groq, Anthropic, DeepSeek and MiniMax clients
remain available. Keys are `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`,
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, and `MINIMAX_API_KEY` respectively.
No live capability matrix for alternative models is claimed.

Embeddings remain a separately configured OpenAI operation. Choosing another
chat provider does not supply an embedding backend, so this mode also requires
an OpenAI embedding key. Only the recommended OpenAI profile is a one-key
installation. No new embedding-provider framework is included.

## Preserve existing vectors

Fresh empty stores use small/1536. Existing collections must keep the model
that actually produced their vectors. A matching vector width alone does not
identify the model. Verify the original deployment configuration and pin it:

```json
{
  "profile": "futuresmart-recommended-v1",
  "embeddings": {
    "high_cardinality": {
      "provider": "openai",
      "model": "text-embedding-3-large",
      "dimensions": 3072
    }
  }
}
```

Pin `fewshot` independently if that collection also used large/3072. Existing
`FEWSHOT_EMBEDDING_MODEL`/`FEWSHOT_EMBEDDING_SIZE` and
`HC_EMBEDDING_MODEL`/`HC_DENSE_VECTOR_SIZE` remain explicit deployment overrides;
`HC_EMBEDDING_SIZE` is an alias and conflicting sizes are rejected. Environment
bindings override file embedding bindings. Configured model and dimensions must
agree. Unknown models are rejected rather than assigned an assumed width.

Incompatible existing schemas or dimensions fail before embedding/search/write.
The application does not delete, resize, rebuild or silently re-embed an existing
collection. A legacy unnamed HC collection remains preserved and requires an
explicit migration or separately provisioned compatible collection. No migration
is performed by installation or this profile change. Both few-shot retrieval
and feedback writes use the same model/dimension binding.

Restart the backend after changing an embedding binding; those stores initialize
their embedding clients at process startup. Changing a chat operation file is
resolved by subsequent model construction. Preserve original stores in either case.


New business templates inherit the current model profile and file overrides;
they supply instructions without selecting another provider. Existing explicit
stored node bindings retain precedence and are not automatically rewritten.
A template instruction change does not require a different provider key.


## Verified first-run scope

The recommended profile passed a clean, one-OpenAI-key installation on 22 October
2026: default UI setup, a four-row sample query/chart, full stack restart and
saved reopen, then one direct API request with a final-answer file override.
This limited installation check does not establish general accuracy, every
provider/model combination, or an embedding migration. See the
[qualification receipt](improvements/evidence/2026-10-22-one-key-qualification.json).
