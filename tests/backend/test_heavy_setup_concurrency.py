"""DA-MEM-002: database setup work runs one heavy section at a time per API process.

Two databases added seconds apart started two profiling/description jobs at once; with a chat
question on top the 1024 MB hosted task ran out of memory. These tests drive the product's own
job entry points concurrently (profiling, HC registration's reads, both description jobs) and
fail if any two heavy sections overlap, if a queued job is dropped, or if the BM25 encoder is
loaded more than once. Synthetic fakes only; nothing reaches a database, Qdrant or a provider.
"""
import asyncio
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from access_policy_harness import BACKEND

sys.path.insert(0, str(BACKEND))
# Product modules build (never connect) a metadata engine at import time.
for _k, _v in {"POSTGRES_USER": "synthetic", "POSTGRES_PASSWORD": "synthetic",
               "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432",
               "POSTGRES_DB_NAME": "synthetic", "OPENAI_API_KEY": "sk-synthetic"}.items():
    os.environ.setdefault(_k, _v)

from agent.utils import heavy_work_gate  # noqa: E402
from agent.utils import high_cardinality_qdrant_utils as hcq  # noqa: E402
from api.v1.routers import hc_profile  # noqa: E402
from api.v1.schemas.hc_profile import TriggerHCProfileRequest  # noqa: E402
from api.v1.utils import description_jobs_helper as djh  # noqa: E402

DB = {"db_details": {"db_engine": "postgresql", "db_name": "synthetic"}}


class Occupancy:
    """Records how many heavy sections run at once (called from worker threads)."""

    def __init__(self, hold=0.15):
        self.hold = hold
        self.lock = threading.Lock()
        self.now = 0
        self.peak = 0
        self.finished = []

    def run(self, name):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(self.hold)
        with self.lock:
            self.now -= 1
            self.finished.append(name)


class HeavySetupConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.occ = Occupancy()
        occ = self.occ

        def profiler(db_details, config, table_names):
            occ.run("profile")
            return {"orders": {"status": {"classification": "NORMAL_COLUMN"}}}

        def inspect(db_details):
            occ.run("describe")
            return "- orders (status:text)"

        def introspect_tables(_):
            occ.run("table-describe")
            return ["orders"]

        class Llm:
            async def ainvoke(self, prompt):
                return types.SimpleNamespace(content="Synthetic description.")

        patches = [
            patch.object(hc_profile, "_get_agent", AsyncMock(return_value=types.SimpleNamespace(owner_id=None))),
            patch.object(hc_profile.database_db_utils, "get_db_connection_by_id",
                         AsyncMock(return_value={"status": True, **DB})),
            patch.object(hc_profile, "profile_all_tables", profiler),
            patch.object(hc_profile, "save_hc_column_profiles", AsyncMock(return_value={"status": True})),
            patch.object(djh, "_inspect_schema_sync", inspect),
            patch.object(djh, "_build_llm", AsyncMock(return_value=Llm())),
            patch.object(djh, "_set_job", AsyncMock()),
            patch.object(djh, "_apply_description_to_db", AsyncMock()),
            patch("knowledge.db_utils.table_description_db_utils.get_table_names_from_db", introspect_tables),
            patch("api.v1.utils.columns_helper.get_table_columns_from_db", lambda *a: []),
            patch("api.v1.utils.tables_helper.get_all_agent_table_descriptions", AsyncMock(return_value=[])),
            patch("knowledge.db_utils.table_description_db_utils.save_generated_table_descriptions",
                  AsyncMock(return_value={"status": True})),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_two_setups_and_their_description_jobs_never_overlap_and_all_finish(self):
        body = TriggerHCProfileRequest(auto_register_hc=False)
        jobs = [
            hc_profile.run_hc_profile_for_agent(None, "AGENT_A", body, db_id="DB_A"),
            djh._run_generation("AGENT_A", "DB_A", "JOB_A", DB["db_details"], apply_to_db=True),
            hc_profile.run_hc_profile_for_agent(None, "AGENT_B", body, db_id="DB_B"),
            djh._run_generation("AGENT_B", "DB_B", "JOB_B", DB["db_details"], apply_to_db=True),
            djh._run_table_generation("AGENT_B", "DB_B", "TBLDESC_B", DB["db_details"]),
        ]
        results = await asyncio.gather(*jobs)
        self.assertEqual(self.occ.peak, 1, "two heavy setup sections ran at the same time")
        self.assertEqual(sorted(self.occ.finished),
                         ["describe", "describe", "profile", "profile", "table-describe"])
        self.assertEqual([r["status"] for r in results[0::2][:2]], ["success", "success"])
        self.assertEqual(heavy_work_gate.heavy_work_state()["running"], 0)
        self.assertEqual(heavy_work_gate.heavy_work_state()["waiting"], 0)

    async def test_chat_work_is_not_queued_behind_a_running_setup(self):
        started = asyncio.Event()

        async def setup():
            async with heavy_work_gate.heavy_work("setup"):
                started.set()
                await asyncio.sleep(0.3)

        task = asyncio.create_task(setup())
        await started.wait()
        t0 = time.monotonic()
        await asyncio.sleep(0)  # a request that does not enter the gate runs immediately
        self.assertLess(time.monotonic() - t0, 0.05)
        self.assertEqual(heavy_work_gate.heavy_work_state()["running"], 1)
        await task

    async def test_a_gated_section_reaching_another_gated_call_does_not_deadlock(self):
        async with heavy_work_gate.heavy_work("outer"):
            await asyncio.wait_for(self._inner(), timeout=1)  # same task on 3.12
            # wait_for runs the coroutine in a task of its own on 3.11 (the API image); gather does
            # on every version.
            await asyncio.wait_for(asyncio.gather(self._inner(), self._inner()), timeout=1)

    async def _inner(self):
        async with heavy_work_gate.heavy_work("inner"):
            return True

    async def test_a_task_spawned_inside_a_section_queues_once_that_section_released(self):
        released, inside = asyncio.Event(), {"now": 0, "peak": 0}

        async def section(name, before=None):
            if before is not None:
                await before.wait()
            async with heavy_work_gate.heavy_work(name):
                inside["now"] += 1
                inside["peak"] = max(inside["peak"], inside["now"])
                await asyncio.sleep(0.05)
                inside["now"] -= 1

        async with heavy_work_gate.heavy_work("outer"):
            # Starts only after "outer" released, but carries its context.
            child = asyncio.create_task(section("spawned", before=released))
        other = asyncio.create_task(section("other"))
        await asyncio.sleep(0)  # "other" now holds the gate
        released.set()
        await asyncio.gather(child, other)
        self.assertEqual(inside["peak"], 1, "a spawned task slipped past the gate")

    async def test_a_failed_section_releases_the_gate(self):
        with self.assertRaises(RuntimeError):
            async with heavy_work_gate.heavy_work("fails"):
                raise RuntimeError("synthetic")
        await asyncio.wait_for(self._inner(), timeout=1)


class ColumnIndexingIsChunkedTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_large_column_is_embedded_in_bounded_chunks_and_fully_upserted(self):
        embedded, upserted = [], []

        class Embedder:
            async def aembed_documents(self, texts):
                embedded.append(len(texts))
                return [[0.0] * 4 for _ in texts]

        class Client:
            async def upsert(self, collection_name, points):
                upserted.extend(p.id for p in points)

        store = hcq.QdrantCardinalityStore.__new__(hcq.QdrantCardinalityStore)
        store.collection_name, store.client = "synthetic", Client()
        values = [f"value-{i}" for i in range(600)]
        sparse = lambda texts: [hcq.SparseVector(indices=[1], values=[1.0]) for _ in texts]
        with patch.object(store, "_ensure_collection", AsyncMock()), \
                patch.object(store, "_make_embedding_fn", lambda api_key=None: Embedder()), \
                patch.object(hcq, "_encode_sparse_batch", sparse):
            self.assertTrue(await store.store_values(values, {"table": "t", "column": "c", "db_id": "DB"}))
        self.assertLessEqual(max(embedded), hcq._INDEX_CHUNK_SIZE, "a whole column was embedded at once")
        self.assertEqual(sum(embedded), 600)
        self.assertEqual(len(set(upserted)), 600)


class SparseEncoderLoadsOnceTests(unittest.TestCase):
    def test_concurrent_callers_share_one_bm25_model(self):
        built = []

        class SlowModel:
            def __init__(self, model_name):
                time.sleep(0.1)
                built.append(model_name)

        fake = types.SimpleNamespace(SparseTextEmbedding=SlowModel)
        with patch.dict(sys.modules, {"fastembed": fake}), patch.object(hcq, "_sparse_encoder", None):
            seen = []
            threads = [threading.Thread(target=lambda: seen.append(hcq._get_sparse_encoder()))
                       for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(built), 1, "the BM25 model was loaded once per caller")
        self.assertEqual(len({id(m) for m in seen}), 1)


if __name__ == "__main__":
    unittest.main()
