"""Complete setup/write/read/node bodies with synthetic ORM/source/provider boundaries."""
from contextlib import ExitStack
from datetime import datetime
import asyncio
import json
import socket
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile
from access_policy_harness import BACKEND, load_function, load_policy, modules, state

sys.path.insert(0, str(BACKEND))
from agent.utils.table_flag_writes import canonical_table_flags_for_write
from agent.utils.model_profiles import ModelConfigurationError, response_text


class FreshPolicyWriteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for obj, name in ((socket, 'create_connection'), (socket.socket, 'connect'), (socket.socket, 'connect_ex')):
            self.stack.enter_context(patch.object(obj, name, side_effect=AssertionError('External network forbidden')))
        self.record = None

        class Row:
            agent_id = 'agent-field'
            db_id = 'db-field'
            def __init__(self, **values):
                self.__dict__.update(values)
        def result(*_args):
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(first=lambda: self.record),
                                         first=lambda: (self.record,) if self.record else None)
        self.session = types.SimpleNamespace(execute=AsyncMock(side_effect=result), commit=AsyncMock(),
            refresh=AsyncMock(), add=lambda row: setattr(self, 'record', row))
        async def sessions():
            yield self.session
        bindings = dict(TableDescription=Row, select=lambda *_: types.SimpleNamespace(where=lambda *_: None),
            get_async_session=sessions, get_primary_db_id=AsyncMock(return_value='synthetic-db'),
            datetime=datetime, canonical_table_flags_for_write=canonical_table_flags_for_write)
        self.write = load_function('knowledge/db_utils/table_description_db_utils.py', 'upload_to_db_table_description', **bindings)
        self.write_flags = load_function('knowledge/db_utils/table_description_db_utils.py', 'upload_to_db_include_or_exclude_table_names', **bindings)
        self.fetch = AsyncMock(side_effect=lambda *_args, **_kwargs: {'status': True, 'record': self.record})
        self.storage = types.SimpleNamespace(upload_to_db_table_description=self.write,
            upload_to_db_include_or_exclude_table_names=self.write_flags, list_table_description_from_db=self.fetch)
        self.verify = AsyncMock(return_value=object())
        self.source = types.SimpleNamespace(get_db_connection=AsyncMock(return_value={'status': True, 'db_details': {}}),
            get_all_tables=AsyncMock(return_value=['orders', 'order_status_history']))
        helper = dict(verify_agent_exists=self.verify, get_primary_db_id=AsyncMock(return_value='synthetic-db'),
            table_description_db_utils=self.storage, database_db_utils=self.source,
            HTTPException=HTTPException, UploadFile=UploadFile,
            canonical_table_flags_for_write=canonical_table_flags_for_write)
        helper['_normalize_table_descriptions'] = load_function('api/v1/utils/tables_helper.py', '_normalize_table_descriptions', HTTPException=HTTPException)
        self.create = load_function('api/v1/utils/tables_helper.py', 'create_agent_table_descriptions', **helper)
        self.visibility = load_function('api/v1/utils/tables_helper.py', 'update_agent_table_visibility', **helper)
        self.read_configuration = load_function('api/v1/utils/tables_helper.py', 'get_all_agent_table_descriptions', **helper)
        self.policy = load_policy()
        self.sampling = load_function('agent/utils/sampling_policy.py', 'get_table_visibility',
            TableAccessPolicyError=self.policy.TableAccessPolicyError, _bare=self.policy._bare)

    async def create_metadata(self):
        result = await self.create('synthetic-agent', 'application/json',
            raw_body=json.dumps([{'orders': 'current orders'}, {'order_status_history': 'status history'}]).encode(),
            db_id='synthetic-db', user_id='synthetic-user')
        self.assertEqual(result['status'], 'success')

    async def test_actual_setup_writer_to_both_strict_readers_selector_sampling_and_exec(self):
        await self.create_metadata()
        self.assertEqual(self.record.entry_flags, {'orders': True, 'order_status_history': True})
        self.assertTrue(all(type(v) is bool for v in self.record.entry_flags.values()))
        await self.visibility('synthetic-agent', 'order_status_history', False, db_id='synthetic-db')
        self.assertIs(self.record.entry_flags['order_status_history'], False)
        await self.create_metadata()
        self.assertIs(self.record.entry_flags['order_status_history'], False)
        selected = AsyncMock(return_value=('', ['orders']))
        examples = AsyncMock(return_value=[])
        selector = load_function('agent/nodes/select_table_and_fewshots.py', 'node_select_and_fewshots',
            ModelConfigurationError=ModelConfigurationError, select_tables=selected,
            get_agent_node_config=AsyncMock(return_value=None),
            get_few_shot_service=AsyncMock(return_value=types.SimpleNamespace(get_similar_examples=examples)),
            build_few_shot_examples_string=lambda value: value)
        forbidden = Mock(side_effect=AssertionError('Excluded source/model work reached'))
        sql_gen = load_function('agent/nodes/sql_gen.py', 'node_sql_gen', get_agent_node_config=forbidden)
        execute = load_function('agent/nodes/sql_exec.py', 'node_sql_exec', try_exec_sql=forbidden)
        with modules(self.policy, self.fetch):
            for reader in (self.policy.get_table_visibility, self.sampling):
                self.assertEqual(await reader('synthetic-user', 'synthetic-agent', 'synthetic-db'),
                                 (['orders'], ['order_status_history']))
            current = state('SELECT * FROM orders')
            current.update(query='orders', table_descriptions={'orders':'current orders','order_status_history':'history'})
            current = await selector(current)
            self.assertEqual(current['selected_tables'], ['orders'])
            self.assertEqual(json.loads(selected.await_args.args[1]), [{'orders': 'current orders'}])
            permitted_executor = Mock(return_value=(True, (['region','total'], [('North',250),('South',200)]), None))
            permitted_exec = load_function('agent/nodes/sql_exec.py', 'node_sql_exec', try_exec_sql=permitted_executor)
            permitted_result = await permitted_exec(state('SELECT region, SUM(amount) AS total FROM orders GROUP BY region'))
            self.assertEqual(permitted_result['db_result'], [('North',250),('South',200)])
            permitted_executor.assert_called_once()
            sampled = state()
            sampled['selected_tables'] = ['order_status_history']
            with patch.dict(sys.modules, {'agent.utils.sampling_policy': types.SimpleNamespace(
                    get_table_visibility=self.sampling, blocked_table_names=self.policy.blocked_table_names)}):
                denied = await sql_gen(sampled)
            self.assertEqual(denied['access_denied_tables'], ['order_status_history'])
            denied = await execute(state('SELECT * FROM order_status_history'))
            self.assertEqual(denied['access_denied_tables'], ['order_status_history'])
            self.record.db_id = 'foreign-db'
            for reader in (self.policy.get_table_visibility, self.sampling):
                with self.assertRaises(self.policy.TableAccessPolicyError):
                    await reader('synthetic-user','synthetic-agent','synthetic-db')
        forbidden.assert_not_called()

    async def test_only_explicit_write_normalizes_legacy_exact_flags_and_invalid_input_never_writes(self):
        await self.create_metadata()
        self.record.entry_flags = {'orders': 1, 'order_status_history': 0}
        with modules(self.policy, self.fetch):
            for reader in (self.policy.get_table_visibility, self.sampling):
                with self.assertRaises(self.policy.TableAccessPolicyError):
                    await reader('synthetic-user','synthetic-agent','synthetic-db')
        await self.visibility('synthetic-agent','order_status_history',False,db_id='synthetic-db')
        self.assertIs(self.record.entry_flags['orders'], True)
        self.assertIs(self.record.entry_flags['order_status_history'], False)
        before = dict(self.record.entry_flags)
        for bad in ({'orders':'false'}, {'orders':2}, {'orders':1.0}, '{"orders":true,"orders":false}'):
            self.session.execute.reset_mock()
            result = await self.write(None,'synthetic-agent',entry_flags=bad,db_id='synthetic-db')
            self.assertIs(result['status'], False)
            self.session.execute.assert_not_called()
            self.assertEqual(self.record.entry_flags,before)

    async def test_complete_automatic_table_description_job_writes_booleans_and_preserves_false(self):
        await self.create_metadata()
        await self.visibility('synthetic-agent','order_status_history',False,db_id='synthetic-db')
        rows = [{'table_name':'orders','description':'','is_included':True},
                {'table_name':'order_status_history','description':'','is_included':False}]
        setter = AsyncMock()
        job = load_function('api/v1/utils/description_jobs_helper.py','_run_table_generation',
            asyncio=asyncio, _TABLE_GEN_CONCURRENCY=6,
            _build_llm=lambda: types.SimpleNamespace(ainvoke=AsyncMock(return_value=types.SimpleNamespace(text='description'))),
            _set_job=setter, _TABLE_PROMPT_INTRO='unchanged source prompt omitted at synthetic model boundary',
            response_text=response_text)
        parents = {name:types.ModuleType(name) for name in ('api','api.v1','api.v1.utils','knowledge','knowledge.db_utils')}
        for item in parents.values(): item.__path__=[]
        with patch.dict(sys.modules,{**parents,
            'api.v1.utils.columns_helper':types.SimpleNamespace(get_table_columns_from_db=lambda *_: []),
            'api.v1.utils.tables_helper':types.SimpleNamespace(get_all_agent_table_descriptions=AsyncMock(return_value=rows)),
            'knowledge.db_utils.table_description_db_utils':types.SimpleNamespace(
                get_table_names_from_db=lambda *_:['orders','order_status_history'], upload_to_db_table_description=self.write)}):
            await job('synthetic-agent','synthetic-db','synthetic-job',{'db_name':'synthetic'},overwrite=True)
        self.assertEqual(self.record.entry_flags,{'orders':True,'order_status_history':False})
        self.assertTrue(all(type(v) is bool for v in self.record.entry_flags.values()))
        self.assertEqual(setter.await_args.kwargs['status'],'done', setter.await_args)

    async def test_falsey_malformed_existing_configuration_cannot_become_default_allow_job_write(self):
        await self.create_metadata()
        setter, model = AsyncMock(), Mock(side_effect=AssertionError('Model reached invalid policy'))
        job = load_function('api/v1/utils/description_jobs_helper.py','_run_table_generation',
            asyncio=asyncio, _TABLE_GEN_CONCURRENCY=6, _build_llm=model, _set_job=setter,
            _TABLE_PROMPT_INTRO='unchanged prompt omitted at synthetic boundary', response_text=response_text)
        parents = {name:types.ModuleType(name) for name in ('api','api.v1','api.v1.utils','knowledge','knowledge.db_utils')}
        for item in parents.values(): item.__path__=[]
        for bad in (False, 0, [], '', None):
            with self.subTest(stored_flags=bad):
                self.record.entry_flags=bad
                self.session.commit.reset_mock()
                with self.assertRaises(ValueError):
                    await self.read_configuration('synthetic-agent', db_id='synthetic-db')
                with patch.dict(sys.modules,{**parents,
                    'api.v1.utils.columns_helper':types.SimpleNamespace(get_table_columns_from_db=Mock()),
                    'api.v1.utils.tables_helper':types.SimpleNamespace(get_all_agent_table_descriptions=self.read_configuration),
                    'knowledge.db_utils.table_description_db_utils':types.SimpleNamespace(
                        get_table_names_from_db=Mock(), upload_to_db_table_description=self.write)}):
                    await job('synthetic-agent','synthetic-db','synthetic-job',{'db_name':'synthetic'},overwrite=True)
                self.assertEqual(setter.await_args.kwargs['status'],'failed')
                self.session.commit.assert_not_called()
                self.assertEqual(self.record.entry_flags,bad)
        model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
