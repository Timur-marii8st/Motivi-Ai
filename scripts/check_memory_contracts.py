"""Dependency-free contract checks for the unchanged memory orchestrator.
No API, PostgreSQL, embedding model, or end-to-end app is exercised here.
"""
from __future__ import annotations
import ast
import asyncio
import hashlib
import inspect
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/services/memory_orchestrator.py"

class Field:
    def __eq__(self, other): return ("user_id", other)
    def asc(self): return "history_order_asc"

class Query:
    def __init__(self): self.operations = []
    def where(self, value): self.operations.append(("where", value)); return self
    def order_by(self, value): self.operations.append(("order_by", value)); return self
    def limit(self, value): self.operations.append(("limit", value)); return self

class Logger:
    def warning(self, *args): pass
    def debug(self, *args): pass

source_text = SOURCE.read_text()
tree = ast.parse(source_text, filename=str(SOURCE))
selected = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in {"MemoryPack", "MemoryOrchestrator"}]
assert len(selected) == 2
module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
ns = dict(Any=Any, Dict=Dict, List=List, Optional=Optional, inspect=inspect, datetime=datetime, timezone=timezone,
          select=lambda _: Query(), WorkingMemoryEntry=NS(user_id=Field(), history_order=Field()), logger=Logger())
exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), ns)
MemoryOrchestrator, MemoryPack = ns["MemoryOrchestrator"], ns["MemoryPack"]

class Session:
    def __init__(self, events): self.events=events; self.queries=[]; self.busy=False
    async def execute(self, query):
        if self.busy: raise AssertionError("Concurrent use of one session")
        self.busy=True
        await asyncio.sleep(0)
        self.events.append("history")
        self.queries.append(query.operations)
        self.busy=False
        return NS(scalars=lambda: NS(all=lambda: []))

class Fixture:
    def __init__(self, vector=None, empty=False):
        self.events=[]; self.calls=[]; self.embedding_calls=0
        self.vector=[] if empty else (vector if vector is not None else [0.1, 0.2])
        self.session=Session(self.events); self.user=NS(id=7)
        self.fact=NS(fact_text="Prefers written contact",created_at=None)
        self.working=NS(working_memory_text="Plan",created_at=None,decay_date=None)
        self.core=NS(sleep_schedule_json={},created_at=None)
        async def embed(text, **kwargs):
            self.embedding_calls+=1; self.events.append("embed"); return self.vector
        def retriever(kind, result):
            async def retrieve(session,user_id,query_text,top_k=5,query_vec=None):
                if session.busy: raise AssertionError("Concurrent access")
                session.busy=True; await asyncio.sleep(0); session.busy=False
                self.events.append(kind); self.calls.append((kind,user_id,query_text,top_k,query_vec))
                return result
            return retrieve
        async def recent_core(session,user_id,limit):
            self.events.append("recent_core");self.calls.append(("recent_core",user_id,limit));return [self.fact]
        async def recent_episodes(session,user_id,limit):
            self.events.append("recent_episodes");self.calls.append(("recent_episodes",user_id,limit));return []
        async def get_core(session,user_id): self.events.append("get_core"); return self.core
        async def get_working(session,user_id): self.events.append("get_working"); return self.working
        self.core_service=NS(embeddings=NS(embed=embed),retrieve_similar=retriever("core",[self.fact]),list_facts_for_user=recent_core,get_or_create=get_core)
        self.working_service=NS(retrieve_similar=retriever("working",[self.working]),get_or_create=get_working)
        self.episode_service=NS(retrieve_similar=retriever("episodes",[]),get_recent_episodes=recent_episodes)
        self.orchestrator=MemoryOrchestrator(self.episode_service,self.core_service,self.working_service)

class Checks(unittest.IsolatedAsyncioTestCase):
    async def test_one_embedding_reused_across_three_retrievers(self):
        f=Fixture()
        pack=await f.orchestrator.assemble(f.session,f.user,"question",top_k=2)
        self.assertEqual(f.embedding_calls,1)
        self.assertEqual([x[0] for x in f.calls],["core","working","episodes"])
        self.assertTrue(all(x[4] is f.vector for x in f.calls))
        self.assertTrue(all(x[1:3]==(7,"question") for x in f.calls))
        self.assertEqual(f.calls[0][3],2)
        self.assertEqual(f.calls[2][3],2)
        self.assertEqual(pack.core_facts,[f.fact])

    async def test_shared_session_calls_are_sequential_and_history_is_scoped(self):
        f=Fixture()
        await f.orchestrator.assemble(f.session,f.user,"question")
        self.assertEqual(f.events,["embed","core","working","episodes","history","get_core"])
        self.assertEqual(f.session.queries,[[("where",("user_id",7)),("order_by","history_order_asc"),("limit",7)]])

    async def test_empty_embedding_uses_recent_memory_fallback(self):
        f=Fixture(empty=True)
        pack=await f.orchestrator.assemble(f.session,f.user,"question",top_k=3)
        self.assertEqual(f.events,["embed","recent_core","recent_episodes","history","get_core","get_working"])
        self.assertEqual(f.calls,[("recent_core",7,3),("recent_episodes",7,3)])
        self.assertIs(pack.working,f.working)

    async def test_legacy_retriever_without_optional_arguments(self):
        calls=[]
        async def legacy(session,user_id,query_text):
            calls.append((session,user_id,query_text));return ["ok"]
        result=await MemoryOrchestrator._call_retrieve_similar(legacy,"session",7,query_text="q",top_k=2,query_vec=[1])
        self.assertEqual(result,["ok"])
        self.assertEqual(calls,[("session",7,"q")])

    async def test_embedding_exception_is_not_silently_treated_as_empty_vector(self):
        f=Fixture()
        async def fail(*args,**kwargs): raise TimeoutError("simulated")
        f.core_service.embeddings.embed=fail
        with self.assertRaises(TimeoutError):
            await f.orchestrator.assemble(f.session,f.user,"question")
        self.assertEqual(f.calls,[])

    async def test_context_serialization_orders_working_history(self):
        f=Fixture()
        f.user=NS(id=7,name="Test",age=None,user_timezone="Europe/Moscow",wake_time=None,bed_time=None,occupation_json={})
        first=NS(working_memory_text="first",history_order=1,created_at=None)
        second=NS(working_memory_text="second",history_order=2,created_at=None)
        pack=MemoryPack(f.user,f.core,[f.fact],f.working,[],[second,first])
        context=pack.to_context_dict()
        self.assertEqual([x["text"] for x in context["working_memory"]["history"]],["first","second"])
        self.assertEqual(context["core_memory"]["core_facts"],[{"fact":f.fact.fact_text,"created_at":None}])
        self.assertEqual(context["relevant_episodes"],[])

if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={"scope":"isolated component contracts; external dependencies replaced; unchanged class code loaded via AST",
             "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"tests_run":result.testsRun,
             "failures":len(result.failures),"errors":len(result.errors),
             "not_measured":["retrieval relevance","real database concurrency","LLM answer quality","production latency","uptime"]}
    print(json.dumps(summary,ensure_ascii=False))
    sys.exit(not result.wasSuccessful())

