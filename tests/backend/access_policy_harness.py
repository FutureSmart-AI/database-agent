"""Load actual policy/node bodies without app bootstrap, secrets, DBs or providers.

Only decorators/import-time application wiring are omitted from node loading.
Tests execute the complete source function body, with explicit boundary spies.
"""
import ast
from contextlib import contextmanager
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time
import types
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def source_root(checkout, container):
    """The two supported test layouts: complete checkout and API image /app."""
    for candidate in (checkout/'backend', container):
        if (candidate/'agent/utils/table_access.py').is_file():
            return candidate
    raise RuntimeError('Product policy source is absent from checkout and API image')


BACKEND = source_root(ROOT, Path('/app'))
LOG = logging.getLogger('synthetic-access-policy-test')
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


def load_policy():
    spec = importlib.util.spec_from_file_location('synthetic_table_access', BACKEND/'agent/utils/table_access.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'logger': types.SimpleNamespace(logger=LOG)}):
        spec.loader.exec_module(module)
    return module


def load_function(relative, name, **bindings):
    tree = ast.parse((BACKEND/relative).read_bytes())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    namespace = {'AgentState': dict, 'logger': LOG, 'os': os, 'json': json, 'time': time,
        'Any':Any, 'Dict':Dict, 'List':List, 'Optional':Optional, 'Set':Set, 'Tuple':Tuple,
        'Literal':Literal,
        'record_node_seconds': Mock(), 'get_usage_tracker': lambda: types.SimpleNamespace(record_event=AsyncMock()),
        **bindings}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(BACKEND/relative),'exec'),namespace)
    return namespace[name]


@contextmanager
def modules(policy, fetch):
    parents = {name: types.ModuleType(name) for name in ['agent','agent.utils','agent.db_utils']}
    for module in parents.values(): module.__path__ = []
    with patch.dict(sys.modules, {**parents, 'agent.utils.table_access': policy, 'agent.utils.sampling_policy': policy,
            'agent.db_utils.table_description_db_utils':types.SimpleNamespace(list_table_description_from_db=fetch)}):
        yield


def policy_record(flags, *, agent='synthetic-agent', db='synthetic-db', status=True):
    return {'status':status, 'record':types.SimpleNamespace(chatbot_id=agent, db_id=db, entry_flags=flags)}


def state(sql='SELECT * FROM returns'):
    return {'user_id':'synthetic-user','agent_id':'synthetic-agent','db_id':'synthetic-db',
        'request_id':'synthetic-request','session_id':'synthetic-session',
        'runtime_db_details':{'db_id':'synthetic-db','db_engine':'postgresql'},
        'sql_query':sql, 'db_result':[(999,)], 'db_columns':['stale'], 'is_answered':True}
