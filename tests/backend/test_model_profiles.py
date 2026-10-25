"""Configuration and real SDK request contracts, using synthetic transport only."""
import ast
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import types
import typing
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from pydantic import BaseModel, Field
from access_policy_harness import BACKEND

sys.path.insert(0, str(BACKEND))
from agent.utils.model_profiles import (
    load_profile, operation_config, merge_binding, validate_binding, build_chat_model,
    configured_model_factory, ModelConfigurationError,
    response_text,
)
from agent.utils.answerability import SQLQuerySchema
from agent.utils.embedding_config import verify_vector_size


def source_classes(relative, names):
    tree = ast.parse((BACKEND / relative).read_text(encoding="utf-8"))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
    namespace = {**vars(typing), "BaseModel": BaseModel, "Field": Field}
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(relative), "exec"), namespace)
    return namespace


class ProfileTests(unittest.TestCase):
    def setUp(self):
        system = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
        self.env = patch.dict(os.environ, system, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, data):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "models.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_one_key_defaults_and_shared_loader_precedence(self):
        path = self.config({"profile": "futuresmart-recommended-v1", "overrides": {
            "sql_agent.rephrase_answer": {"provider": "openai", "model": "gpt-6.1-sol", "reasoning_effort": "high"}}})
        with patch.dict(os.environ, {"MODEL_CONFIG_PATH": str(path)}):
            from agent.utils.model_config_loader import load_model_config as sql
            from chart_agent.utils.model_config_loader import load_model_config as chart
            from pandas_agent.utils.model_config_loader import load_model_config as pandas
            from csv_agent.utils.model_config_loader import load_model_config as csv
            for loader in (sql, chart, pandas, csv):
                self.assertIs(loader, load_profile)
                self.assertEqual(loader()["sql_agent"]["rephrase_answer"]["reasoning_effort"], "high")
            self.assertEqual(operation_config("final_answer_node")["endpoint"], "responses")
            self.assertEqual(operation_config("final_answer_node", {"provider": "openai", "model": "gpt-6-luna"})["endpoint"], "chat_completions")
        fresh = load_profile()
        self.assertEqual(fresh["embeddings"]["high_cardinality"]["dimensions"], 1536)
        self.assertEqual(fresh["chart_agent"]["suggest"]["model"], "gpt-6-luna")

    def test_single_provider_preserves_groq_oss_and_operation_override(self):
        profile = load_profile(self.config({"single_provider": {"provider": "groq", "model": "openai/gpt-oss-120b"},
            "overrides": {"sql_agent.sql_generation": {"provider": "google", "model": "gemini-test"}}}))
        self.assertEqual(profile["sql_agent"]["router"]["provider"], "groq")
        self.assertNotIn("reasoning_effort", profile["sql_agent"]["router"])
        self.assertEqual(profile["sql_agent"]["sql_generation"]["provider"], "google")
        self.assertEqual(profile["embeddings"]["fewshot"]["provider"], "openai")

    def test_invalid_configuration_fails_before_sdk(self):
        for bad in ({"profile": "missing"}, {"overrides": {"missing.node": {}}},
                    {"single_provider": {"provider": "groq"}},
                    {"overrides": {"sql_agent.router": {"model": "gpt-6-luna"}}},
                    {"overrides": {"sql_agent.router": {"secret": "never-an-option"}}}):
            with self.subTest(bad=bad), self.assertRaises(ModelConfigurationError):
                load_profile(self.config(bad))
        with self.assertRaises(ModelConfigurationError):
            build_chat_model(operation_config("router"))
        with patch("agent.utils.model_profiles.importlib.import_module", side_effect=ImportError), self.assertRaises(ModelConfigurationError):
            build_chat_model({"provider": "groq", "model": "openai/gpt-oss-120b"}, api_key="offline")

    def test_capabilities_and_finite_bounds(self):
        for options in ({"endpoint": "chat_completions"}, {"temperature": 0}, {"reasoning_effort": "none"},
                        {"timeout": math.nan}, {"timeout": math.inf}, {"max_tokens": 1.5}, {"max_tokens": True}):
            with self.subTest(options=options), self.assertRaises(ModelConfigurationError):
                validate_binding({"provider": "openai", "model": "gpt-6.1-sol", **options})
        conf = validate_binding({"provider": "openai", "model": "gpt-6-luna", "endpoint": "responses", "reasoning_effort": "max"})
        self.assertEqual(conf["reasoning_effort"], "max")
        with self.assertRaises(ModelConfigurationError):
            merge_binding(operation_config("router"), {"endpoint": "responses", "reasoning_effort": "high"})
        self.assertEqual(validate_binding({"provider": "openai", "model": "gpt-5.6-luna"})["reasoning_effort"], "none")

    def test_factory_retains_stricter_call_bounds_and_transport(self):
        transport = object()
        with patch("agent.utils.model_profiles.build_chat_model") as construct:
            configured_model_factory(operation_config("router"))(api_key="offline", max_tokens=7, timeout=1,
                max_retries=0, http_client=transport)
        conf = construct.call_args.args[0]
        self.assertEqual((conf["max_tokens"], conf["timeout"]), (7, 1))
        self.assertIs(construct.call_args.kwargs["http_client"], transport)

    def test_actual_sdk_serializes_real_router_sql_and_mapping_contracts(self):
        router = source_classes("agent/nodes/router.py", {"RouterOutput"})["RouterOutput"]
        final = source_classes("agent/nodes/final_answer.py", {"FinalAnswerOutput"})["FinalAnswerOutput"]
        mapping = source_classes("chart_agent/utils/graph_mapper.py", {"FieldMapping", "MetadataConfig", "GraphMappingSpec"})["GraphMappingSpec"]
        cases = [("sql_agent.router", router, {"action": "sql_gen_node", "refined_query": "totals", "visualization_query": "bar", "response": ""}),
                 ("sql_agent.sql_generation", SQLQuerySchema, {"answerable": True, "generated_query": "SELECT region, SUM(amount) FROM orders GROUP BY region", "reason": "available"}),
                 ("chart_agent.mapping", mapping, {"chart_type": "Bar Chart", "field_mappings": [], "measure_columns": ["total"], "label_columns": ["region"], "metadata_config": {"title": "Totals"}, "reasoning": "two groups"}),
                 ("sql_agent.rephrase_answer", final, {"response": "North250; South200", "is_answered": True})]
        for operation, schema, answer in cases:
            with self.subTest(operation=operation):
                requests = []
                conf = operation_config(operation)
                if operation == "chart_agent.mapping":
                    conf = merge_binding(conf, {"provider": "openai", "model": "gpt-6.1-sol", "reasoning_effort": "high"})
                if operation == "sql_agent.rephrase_answer":
                    conf = merge_binding(conf, {"endpoint": "responses", "reasoning_effort": "high", "temperature": None})
                def respond(request):
                    payload = json.loads(request.content)
                    requests.append((request.url.path, payload))
                    tool = {"name": schema.__name__, "arguments": json.dumps(answer)}
                    if request.url.path.endswith("/responses"):
                        response = {"id": "resp_offline", "object": "response", "created_at": 1, "model": conf["model"],
                            "status": "completed", "error": None, "output": [{"type": "function_call", "id": "fc_offline",
                            "call_id": "call_offline", "status": "completed", **tool}],
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                    else:
                        response = {"id": "chat_offline", "object": "chat.completion", "created": 1, "model": conf["model"],
                            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                            "tool_calls": [{"id": "call_offline", "type": "function", "function": tool}]}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                    return httpx.Response(200, json=response)
                with httpx.Client(transport=httpx.MockTransport(respond)) as http:
                    model = build_chat_model(conf, api_key="synthetic-offline", http_client=http)
                    result = model.with_structured_output(schema, method="function_calling").invoke("Synthetic schema request")
                self.assertIsNotNone(result)
                self.assertEqual(len(requests), 1)
                path, payload = requests[0]
                self.assertEqual(payload["model"], conf["model"])
                if conf["endpoint"] == "responses":
                    self.assertEqual(path, "/v1/responses")
                    self.assertEqual(payload["reasoning"]["effort"], conf["reasoning_effort"])
                    self.assertNotIn("temperature", payload)
                else:
                    self.assertEqual(path, "/v1/chat/completions")
                    self.assertEqual(payload["reasoning_effort"], "none")

    def test_explicit_legacy_embeddings_and_mismatch(self):
        profile = load_profile(self.config({"embeddings": {"high_cardinality": {
            "provider": "openai", "model": "text-embedding-3-large", "dimensions": 3072}}}))
        self.assertEqual(profile["embeddings"]["high_cardinality"]["dimensions"], 3072)
        with self.assertRaises(ModelConfigurationError):
            load_profile(self.config({"embeddings": {"fewshot": {"model": "text-embedding-3-large"}}}))
        with patch.dict(os.environ, {"HC_EMBEDDING_MODEL": "text-embedding-3-large", "HC_DENSE_VECTOR_SIZE": "3072"}):
            self.assertEqual(load_profile()["embeddings"]["high_cardinality"]["dimensions"], 3072)

    def test_actual_sdk_plain_responses_blocks_and_chat_string_extract_same_text(self):
        for operation in ("sql_agent.db_router", "descriptions.default"):
            with self.subTest(operation=operation):
                conf = operation_config(operation)
                def respond(request):
                    if request.url.path.endswith("/responses"):
                        body = {"id": "resp_offline", "object": "response", "created_at": 1,
                            "model": conf["model"], "status": "completed", "error": None,
                            "output": [{"type": "message", "id": "msg_offline", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "First ", "annotations": []},
                                        {"type": "output_text", "text": "second", "annotations": []}]}],
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                    else:
                        body = {"id": "chat_offline", "object": "chat.completion", "created": 1,
                            "model": conf["model"], "choices": [{"index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "First second"}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                    return httpx.Response(200, json=body)
                with httpx.Client(transport=httpx.MockTransport(respond)) as http:
                    response = build_chat_model(conf, api_key="synthetic-offline", http_client=http).invoke("Synthetic plain output")
                self.assertIsInstance(response.content, list if conf["endpoint"] == "responses" else str)
                self.assertEqual(response_text(response), "First second")

    def test_actual_hc_collection_guard_never_deletes_existing_vectors(self):
        tree = ast.parse((BACKEND / "agent/utils/high_cardinality_qdrant_utils.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "QdrantCardinalityStore")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_ensure_collection")
        namespace = {"ModelConfigurationError": ModelConfigurationError, "verify_vector_size": verify_vector_size,
                     "_DENSE_NAME": "dense", "_SPARSE_NAME": "sparse", "_DENSE_VECTOR_SIZE": 3072}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "actual_hc_guard", "exec"), namespace)
        def store(vectors, sparse):
            client = types.SimpleNamespace(get_collections=AsyncMock(return_value=types.SimpleNamespace(collections=[types.SimpleNamespace(name="existing")])),
                get_collection=AsyncMock(return_value=types.SimpleNamespace(config=types.SimpleNamespace(params=types.SimpleNamespace(vectors=vectors, sparse_vectors=sparse)))),
                delete_collection=AsyncMock())
            return types.SimpleNamespace(collection_name="existing", client=client, _create_hybrid_collection=AsyncMock())
        good = store({"dense": types.SimpleNamespace(size=3072)}, {"sparse": {}})
        asyncio.run(namespace["_ensure_collection"](good))
        for bad in (store(types.SimpleNamespace(size=3072), {}), store({"dense": types.SimpleNamespace(size=1536)}, {"sparse": {}})):
            with self.assertRaises(ModelConfigurationError):
                asyncio.run(namespace["_ensure_collection"](bad))
            bad.client.delete_collection.assert_not_called()
            bad._create_hybrid_collection.assert_not_called()

    def test_actual_fewshot_service_preserves_configuration_error_identity(self):
        tree = ast.parse((BACKEND / "agent/utils/few_shot_utils.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FewShotService")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_similar_examples")
        method.decorator_list = []
        namespace = {**vars(typing), "ModelConfigurationError": ModelConfigurationError, "logger": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "actual_fewshot_service", "exec"), namespace)
        error = ModelConfigurationError("embedding dimension mismatch")
        service = types.SimpleNamespace(ensure_initialized=AsyncMock(), store=types.SimpleNamespace(
            get_similar_examples=AsyncMock(side_effect=error)))
        with self.assertRaises(ModelConfigurationError) as caught:
            asyncio.run(namespace["get_similar_examples"](service, "question", "user", "agent"))
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
