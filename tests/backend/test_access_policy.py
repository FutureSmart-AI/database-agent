"""S60 synthetic execution-boundary regressions; no app bootstrap or external I/O."""
import asyncio
from contextlib import ExitStack
import json
import socket
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from access_policy_harness import load_policy, load_function, modules, policy_record, state, source_root


FLAGS = {'orders':True, 'returns':False}


class HarnessLayoutTests(unittest.TestCase):
    def test_checkout_and_API_image_source_layouts_are_explicit(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);checkout=root/'checkout';image=root/'app'
            target=image/'agent/utils/table_access.py';target.parent.mkdir(parents=True);target.write_text('')
            self.assertEqual(source_root(checkout,image),image)
            target=checkout/'backend/agent/utils/table_access.py';target.parent.mkdir(parents=True);target.write_text('')
            self.assertEqual(source_root(checkout,image),checkout/'backend')
            with self.assertRaises(RuntimeError):source_root(root/'missing-checkout',root/'missing-image')


def synthetic_execute(_details, sql):
    # Each executor call owns a new in-memory fixture, including its worker thread.
    with sqlite3.connect(':memory:') as db:
        db.execute("ATTACH DATABASE ':memory:' AS public")
        db.execute('CREATE TABLE orders(id INTEGER)')
        db.executemany('INSERT INTO orders VALUES (?)', [(1,), (2,)])
        db.execute('CREATE TABLE public.returns(id INTEGER)')
        db.execute('INSERT INTO public.returns VALUES (9)')
        cursor=db.execute(sql)
        return True, ([d[0] for d in cursor.description], cursor.fetchall()), None


class AccessBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Preserve socket's type: Windows asyncio uses isinstance on its local
        # wakeup socket. Block outbound connection methods, not local loop IPC.
        self.network=ExitStack();self.addCleanup(self.network.close)
        for target,name in [(socket,'create_connection'),(socket.socket,'connect'),(socket.socket,'connect_ex')]:
            self.network.enter_context(patch.object(target,name,side_effect=AssertionError('No external network')))
        self.policy=load_policy()
        self.node=load_function('agent/nodes/sql_exec.py','node_sql_exec',try_exec_sql=Mock())

    async def run_node(self, sql, response=None, error=None, *, execute=None, input_state=None):
        fetch=AsyncMock(side_effect=error) if error else AsyncMock(return_value=response)
        executor=execute or Mock(side_effect=AssertionError('Forbidden source executor reached'))
        node=load_function('agent/nodes/sql_exec.py','node_sql_exec',try_exec_sql=executor)
        with modules(self.policy,fetch): out=await node(input_state or state(sql))
        return out,executor,fetch

    def assert_denied(self,out,executor):
        executor.assert_not_called()
        self.assertEqual(out['sql_query'],'')
        self.assertEqual(out['db_result'],[])
        self.assertIsNone(out['db_columns'])
        self.assertIsNone(out['sql_error'])
        self.assertIs(out['is_answered'],False)

    async def test_excluded_joins_scoped_and_qualified_ctes_never_execute(self):
        cases=[
            'SELECT * FROM returns',
            'SELECT o.id FROM orders o JOIN returns r ON o.id=r.id',
            'SELECT * FROM public.returns',
            'WITH returns AS (SELECT 1 AS id) SELECT * FROM public.returns',
            'SELECT * FROM returns WHERE EXISTS (WITH returns AS (SELECT 1) SELECT * FROM returns)',
            'WITH visible AS (SELECT * FROM returns) SELECT * FROM visible',
            'WITH returns AS (SELECT 1), nested AS (SELECT * FROM public.returns) SELECT * FROM nested',
            'SELECT * FROM orders; SELECT * FROM returns',
            'SELECT * FROM orders WHERE id IN (SELECT id FROM returns)',
            'WITH returns AS (SELECT * FROM public.returns) SELECT * FROM returns',
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                out,executor,_=await self.run_node(sql,policy_record(FLAGS))
                self.assert_denied(out,executor)
                self.assertIn('returns',out['access_denied_tables'])

    async def test_unavailable_unbound_or_malformed_policy_never_executes(self):
        responses=[None,{}, {'status':False,'record':None},policy_record(None),policy_record({}),
            policy_record('{bad JSON'),policy_record({'orders':True,'returns':'false'}),
            policy_record({'orders':1}),policy_record({'orders':None}),policy_record(['orders']),
            policy_record(FLAGS,agent='other-agent'),policy_record(FLAGS,db='other-db'),
            policy_record(FLAGS,status=False),policy_record('{"returns": false, "returns": true}'),
            policy_record({'returns':False,'public.returns':True})]
        for response in responses:
            with self.subTest(response=response):
                out,executor,_=await self.run_node('SELECT * FROM returns',response)
                self.assert_denied(out,executor);self.assertTrue(out['access_policy_error'])
        out,executor,_=await self.run_node('SELECT * FROM returns',error=OSError('synthetic store unavailable'))
        self.assert_denied(out,executor);self.assertTrue(out['access_policy_error'])

    async def test_checker_exception_is_not_permission(self):
        with patch.object(self.policy,'blocked_tables',side_effect=RuntimeError('synthetic parser failure')):
            out,executor,_=await self.run_node('SELECT * FROM returns',policy_record(FLAGS))
        self.assert_denied(out,executor);self.assertTrue(out['access_policy_error'])

    async def test_unknown_tables_and_unparseable_sql_fail_closed_even_all_true(self):
        for sql in ['SELECT * FROM newly_added_table','SELECT ((( FROM orders WHERE']:
            with self.subTest(sql=sql):
                out,executor,_=await self.run_node(sql,policy_record({'orders':True}))
                self.assert_denied(out,executor)

    async def test_permitted_queries_and_harmless_ctes_execute_complete_synthetic_rows(self):
        cases=[('SELECT id FROM orders ORDER BY id', FLAGS, [(1,),(2,)]),
            ('WITH returns AS (SELECT id FROM orders) SELECT id FROM returns ORDER BY id',FLAGS,[(1,),(2,)]),
            ('WITH returns AS (SELECT 1 AS id) SELECT id FROM returns',FLAGS,[(1,)]),
            ('WITH x AS (WITH returns AS (SELECT 1 AS id) SELECT id FROM returns) SELECT id FROM x',FLAGS,[(1,)]),
            ('WITH RECURSIVE returns AS (SELECT 1 AS id UNION ALL SELECT id+1 FROM returns WHERE id<2) SELECT id FROM returns ORDER BY id',FLAGS,[(1,),(2,)]),
            ('SELECT returns.id FROM orders AS returns ORDER BY returns.id',FLAGS,[(1,),(2,)]),
            ('SELECT id FROM public.returns',{'orders':True,'returns':True},[(9,)]),
            ('SELECT COUNT(*) FROM orders WHERE id<0',FLAGS,[(0,)])]
        for sql,flags,expected in cases:
            with self.subTest(sql=sql):
                executor=Mock(side_effect=synthetic_execute)
                out,executor,_=await self.run_node(sql,policy_record(flags),execute=executor)
                executor.assert_called_once()
                self.assertEqual(out['db_result'],expected)
                self.assertFalse(out['access_policy_error'])

    async def test_policy_reloaded_when_it_changes_and_runtime_database_binding_wins(self):
        fetch=AsyncMock(side_effect=[policy_record({'orders':True,'returns':True}),policy_record(FLAGS)])
        executor=Mock(side_effect=synthetic_execute)
        node=load_function('agent/nodes/sql_exec.py','node_sql_exec',try_exec_sql=executor)
        with modules(self.policy,fetch):
            first=await node(state('SELECT id FROM public.returns'))
            second=await node(state('SELECT id FROM public.returns'))
        self.assertEqual(first['db_result'],[(9,)])
        self.assertEqual(executor.call_count,1);self.assertEqual(second['sql_query'],'')
        self.assertEqual(fetch.await_count,2)
        # A response for the fallback DB is not a policy for the runtime source.
        s=state();s['db_id']='fallback-db';s['runtime_db_details']['db_id']='runtime-db'
        out,executor,fetch=await self.run_node('',policy_record(FLAGS,db='fallback-db'),input_state=s)
        self.assert_denied(out,executor)
        self.assertEqual(fetch.await_args.kwargs['db_id'],'runtime-db')

    async def test_sql_generation_denies_before_source_samples_suffix_or_model(self):
        for response,selected in [(policy_record(FLAGS),['returns']), (policy_record(None),['orders']),
                (policy_record(FLAGS,db='other-db'),['orders']), (policy_record(FLAGS),['newly_added_table'])]:
            with self.subTest(response=response,selected=selected):
                source=Mock(side_effect=AssertionError('Source sampling must not run'))
                model=AsyncMock(side_effect=AssertionError('Model must not run'))
                node=load_function('agent/nodes/sql_gen.py','node_sql_gen',asyncio=asyncio,
                    sql_database=types.SimpleNamespace(SQLDatabase=types.SimpleNamespace(from_uri=source)),
                    get_agent_node_config=model)
                s=state();s['selected_tables']=selected
                with modules(self.policy,AsyncMock(return_value=response)):out=await node(s)
                self.assert_denied(out,source);model.assert_not_called()

    async def test_permitted_schema_sampling_gate_keeps_only_permitted_tables(self):
        class SamplingReached(BaseException):pass
        samples=[]
        def sample(uri,**kw):samples.append(kw['include_tables']);raise SamplingReached()
        node=load_function('agent/nodes/sql_gen.py','node_sql_gen',asyncio=asyncio,
            sql_database=types.SimpleNamespace(SQLDatabase=types.SimpleNamespace(from_uri=sample)),
            get_agent_node_config=AsyncMock(return_value={}),get_node_additional_instruction=AsyncMock(return_value=None))
        s=state();s['selected_tables']=['orders'];s['runtime_db_details'].update(
            db_user='synthetic',db_password='synthetic',db_host='unused',db_name='synthetic')
        sqlalchemy=types.ModuleType('sqlalchemy');sqlalchemy.create_engine=lambda uri:None
        sqlalchemy.inspect=lambda engine:None
        with modules(self.policy,AsyncMock(return_value=policy_record(FLAGS))), \
             patch.dict(sys.modules,{'sqlalchemy':sqlalchemy,'agent.utils.high_cardinality_utils':
                types.SimpleNamespace(get_suffix_string=AsyncMock(return_value=''))}):
            with self.assertRaises(SamplingReached):await node(s)
        self.assertEqual(samples,[['orders']])

    async def test_cross_database_boundary_and_failure_propagation(self):
        executor=Mock(side_effect=synthetic_execute)
        sql=load_function('agent/nodes/sql_exec.py','node_sql_exec',try_exec_sql=executor)
        class Subgraph:
            async def ainvoke(self,substate):
                substate['sql_query']='SELECT id FROM '+('orders' if substate['db_id']=='permitted-db' else 'public.returns')
                return await sql(substate)
        fanout=load_function('agent/nodes/cross_db_fanout.py','node_cross_db_fanout',asyncio=asyncio,
            single_db_subgraph=Subgraph(),_DB_FIELDS=('db_id','db_engine'))
        merge=load_function('agent/nodes/cross_db_merge.py','node_cross_db_merge')
        def fetch(user,agent,db_id):return policy_record(FLAGS,db=db_id)
        s=state();s.update(cross_db_plan={'sub_questions':[{'db_id':d,'question':'synthetic'}
            for d in ['permitted-db','denied-db']]},selected_dbs=[{'db_id':d,'db_engine':'postgresql'}
            for d in ['permitted-db','denied-db']])
        with modules(self.policy,AsyncMock(side_effect=fetch)):
            out=await fanout(s)
            self.assertEqual(out['cross_db_results'][1]['access_denied_tables'],['returns'])
            out=await merge(out)
        self.assertEqual(executor.call_count,1)
        self.assertEqual(out['db_result'],[]);self.assertEqual(out['sql_query'],'')
        self.assertIs(out['is_answered'],False)

    async def test_policy_failure_final_answer_abstains_without_model_or_chart(self):
        failure=load_function('agent/utils/answerability.py','failure_response')
        model=AsyncMock(side_effect=AssertionError('No model'))
        final=load_function('agent/nodes/final_answer.py','node_final_answer',failure_response=failure,get_agent_node_config=model)
        route=load_function('agent/runner.py','route_after_final_answer')
        s=self.policy.deny_table_access(state(),policy_error=True)
        s.update(include_graph_output=True,query='make a chart')
        out=await final(s)
        self.assertIs(out['is_answered'],False)
        self.assertIn('could not be verified',out['response']);model.assert_not_called()
        self.assertEqual(route(out),'END')

    async def test_generation_denial_stays_terminal_through_exec_and_both_routes(self):
        # Actual graph composition, not just an isolated generation-node result:
        # sql_gen always feeds sql_exec in both the main and cross-DB core.
        for response,selected in [(policy_record(FLAGS),['returns']), (policy_record(None),['orders'])]:
            with self.subTest(selected=selected,response=response):
                fetch=AsyncMock(return_value=response)
                source=Mock(side_effect=AssertionError('Denied executor reached'))
                model=AsyncMock(side_effect=AssertionError('Denied flow invoked model'))
                gen=load_function('agent/nodes/sql_gen.py','node_sql_gen',get_agent_node_config=model)
                execute=load_function('agent/nodes/sql_exec.py','node_sql_exec',try_exec_sql=source)
                pandas_route=load_function('agent/nodes/check_pandas.py','check_pandas_needed')
                main_route=load_function('agent/runner.py','route_after_sql_exec',check_pandas_needed=pandas_route)
                cross_route=load_function('agent/nodes/cross_db_fanout.py','_route_after_subquery_exec')
                s=state();s['selected_tables']=selected
                with modules(self.policy,fetch):
                    out=await execute(await gen(s))
                    self.assertEqual(await main_route(out),'final_answer_node')
                    self.assertEqual(cross_route(out),'END')
                self.assert_denied(out,source)
                self.assertEqual(fetch.await_count,1)
                model.assert_not_called()
                self.assertNotIn('retry_count',out)


if __name__=='__main__':unittest.main(verbosity=2)
