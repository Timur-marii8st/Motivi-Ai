import json
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from app.services.memory_orchestrator import MemoryPack
from app.services.core_memory_service import CoreMemoryService
from app.models.core_memory import CoreFact, CoreFactEmbedding


@dataclass
class FakeUser:
    id: int
    name: str
    age: int
    user_timezone: str
    wake_time: object
    bed_time: object
    occupation_json: object


@dataclass
class FakeWorking:
    id: int
    user_id: int
    working_memory_text: str
    created_at: datetime
    decay_date: object = None


@dataclass
class FakeEpisode:
    id: int
    user_id: int
    text: str
    created_at: datetime


@dataclass
class FakeCore:
    id: int
    user_id: int
    core_text: object
    created_at: datetime
    sleep_schedule_json: object = None


@dataclass
class FakeCoreFact:
    id: int
    core_memory_id: int
    fact_text: str
    created_at: datetime


class DummyStatement:
    def where(self, *a, **kw):
        return self
    def limit(self, *a, **kw):
        return self
    def order_by(self, *a, **kw):
        return self
    def join(self, *a, **kw):
        return self


class LocalEmbedding:
    def cosine_distance(self, query):
        return 0


def test_memory_pack_core_facts_parsing():
    user = FakeUser(id=1, name="Alice", age=30, user_timezone="UTC", wake_time=None, bed_time=None, occupation_json=None)
    working = FakeWorking(id=1, user_id=1, working_memory_text="current working", created_at=datetime.now(timezone.utc))
    episodes = [FakeEpisode(id=1, user_id=1, text="ep1", created_at=datetime(2025, 12, 1, tzinfo=timezone.utc))]

    # Case A: JSON list of facts
    facts = [
        FakeCoreFact(id=1, core_memory_id=1, fact_text="Alice likes coffee", created_at=datetime(2025, 12, 4, 12, 0, tzinfo=timezone.utc)),
        FakeCoreFact(id=2, core_memory_id=1, fact_text="Alice works nights", created_at=datetime(2025, 12, 3, 9, 0, tzinfo=timezone.utc)),
    ]
    core = FakeCore(id=1, user_id=1, core_text=None, created_at=datetime(2025, 12, 1, tzinfo=timezone.utc))

    pack = MemoryPack(user=user, core=core, core_facts=facts, working=working, episodes=episodes)
    ctx = pack.to_context_dict()
    assert isinstance(ctx["core_memory"]["core_facts"], list)
    assert ctx["core_memory"]["core_facts"][0]["fact"] == "Alice likes coffee"

    # Case B: Legacy plain string
    core2 = FakeCore(id=2, user_id=1, core_text=None, created_at=datetime(2025, 12, 2, tzinfo=timezone.utc))
    facts2 = [FakeCoreFact(id=3, core_memory_id=2, fact_text="Alice likes tea", created_at=datetime(2025, 12, 2, tzinfo=timezone.utc))]
    pack2 = MemoryPack(user=user, core=core2, core_facts=facts2, working=working, episodes=episodes)
    ctx2 = pack2.to_context_dict()
    assert isinstance(ctx2["core_memory"]["core_facts"], list)
    assert ctx2["core_memory"]["core_facts"][0]["fact"] == "Alice likes tea"


async def _fake_embed(text, task_type="retrieval_document"):
    return [0.1, 0.2, 0.3]


def test_core_memory_service_store_core_appends(monkeypatch):
    # Create a fake cm that will be returned and mutated by get_or_create
    initial_created = datetime(2025, 12, 1, tzinfo=timezone.utc)
    cm = FakeCore(id=1, user_id=1, core_text=None, created_at=initial_created)

    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_exec_result = MagicMock()
    fake_exec_result.scalars.return_value.all.return_value = []
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    fake_session.execute = AsyncMock(return_value=fake_exec_result)
    # session.add is synchronous in SQLModel/SQLAlchemy; use custom function to capture added objects
    added_objects = []
    def fake_add(obj):
        added_objects.append(obj)
    fake_session.add = fake_add
    fake_session.flush = AsyncMock()
    # configure execute to return result with scalar_one_or_none() -> None
    fake_execute_result = MagicMock()
    fake_execute_result.scalar_one_or_none.return_value = None
    fake_session.execute = AsyncMock(return_value=fake_execute_result)

    async def fake_get_or_create(session, user_id):
        return cm

    monkeypatch.setattr(CoreMemoryService, "get_or_create", staticmethod(fake_get_or_create))

    # Patch CoreFact and CoreFactEmbedding in the service to avoid SQLModel mapper init
    @dataclass
    class LocalFakeCoreFact:
        id: int = None
        core_memory_id: int = None
        fact_text: str = None
        created_at: datetime = None

    class LocalEmbedding:
        def cosine_distance(self, query):
            return 0

    @dataclass
    class LocalFakeCoreFactEmbedding:
        id: int = None
        core_fact_id: int = None
        embedding: object = LocalEmbedding()
        created_at: datetime = None

    import app.services.core_memory_service as cms
    monkeypatch.setattr(cms, "CoreFact", LocalFakeCoreFact)
    monkeypatch.setattr(cms, "CoreFactEmbedding", LocalFakeCoreFactEmbedding)
    # monkeypatch select to avoid SQLModel select usage and SQLModel Column expression errors
    class DummyStatement:
        def where(self, *a, **kw):
            return self
        def limit(self, *a, **kw):
            return self
        def order_by(self, *a, **kw):
            return self

    monkeypatch.setattr(cms, "select", lambda *args, **kwargs: DummyStatement())

    svc = CoreMemoryService(embeddings=type("E", (), {"embed": staticmethod(_fake_embed)})())

    # Run store_core twice
    asyncio.run(svc.store_core(fake_session, 1, "Fact A"))
    asyncio.run(svc.store_core(fake_session, 1, "Fact B"))

    # ensure we added two CoreFact objects and two CoreFactEmbedding objects
    fact_objs = [o for o in added_objects if getattr(o, "fact_text", None) in ("Fact A", "Fact B")]
    emb_objs = [o for o in added_objects if getattr(o, "embedding", None) == [0.1, 0.2, 0.3]]
    assert len(fact_objs) == 2
    assert any(o.fact_text == "Fact A" for o in fact_objs)
    assert any(o.fact_text == "Fact B" for o in fact_objs)
    assert len(emb_objs) == 2
    # The created_at of CoreMemory row remains unchanged (we didn't set it intentionally)
    assert cm.created_at == initial_created
    # We don't modify created_at of CoreMemory in this flow


def test_retrieve_similar_returns_facts(monkeypatch):
    from app.services.core_memory_service import CoreMemoryService
    import app.services.core_memory_service as cms

    # Patch select and CoreFact to avoid SQLModel dependency
    @dataclass
    class LocalFakeCoreFact:
        id: int = None
        core_memory_id: int = None
        fact_text: str = None
        created_at: datetime = None

    # sample results
    facts = [LocalFakeCoreFact(id=1, core_memory_id=1, fact_text="A"), LocalFakeCoreFact(id=2, core_memory_id=1, fact_text="B")]

    fake_execute_result = MagicMock()
    fake_execute_result.scalars.return_value.all.return_value = facts

    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=fake_execute_result)

    async def fake_embed(text, task_type="retrieval_query"):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(cms, "select", lambda *args, **kwargs: DummyStatement())
    @dataclass
    class LocalFakeCoreFactEmbedding:
        id: int = None
        core_fact_id: int = None
        embedding: object = LocalEmbedding()
        created_at: datetime = None

    monkeypatch.setattr(cms, "CoreFact", LocalFakeCoreFact)
    monkeypatch.setattr(cms, "CoreFactEmbedding", LocalFakeCoreFactEmbedding)

    svc = CoreMemoryService(embeddings=type("E", (), {"embed": staticmethod(fake_embed)})())
    res = asyncio.run(svc.retrieve_similar(fake_session, user_id=1, query_text="hey", top_k=2))
    assert isinstance(res, list)
    assert len(res) == 2
    assert res[0].fact_text == "A"


def test_memory_orchestrator_assemble_passes_core_facts(monkeypatch):
    from app.services.memory_orchestrator import MemoryOrchestrator
    from app.services.core_memory_service import CoreMemoryService
    from app.services.working_memory_service import WorkingMemoryService
    from app.services.episodic_memory_service import EpisodicMemoryService

    # Create a fake environment
    async def fake_get_or_create(session, user_id):
        return FakeCore(id=1, user_id=1, core_text=None, created_at=datetime.now(timezone.utc))

    async def fake_retrieve_similar(session, user_id, query_text, top_k=5):
        return [FakeCoreFact(id=1, core_memory_id=1, fact_text="Important fact", created_at=datetime.now(timezone.utc))]

    async def fake_list_facts(session, user_id):
        return [FakeCoreFact(id=1, core_memory_id=1, fact_text="Important fact", created_at=datetime.now(timezone.utc))]

    async def fake_retrieve_working(session, user_id, query_text, top_k=5):
        return []

    async def fake_retrieve_episodes(session, user_id, query_text, top_k=5):
        return []

    core_service = CoreMemoryService()
    monkeypatch.setattr(core_service, "get_or_create", fake_get_or_create)
    monkeypatch.setattr(core_service, "retrieve_similar", fake_retrieve_similar)
    monkeypatch.setattr(core_service, "list_facts_for_user", fake_list_facts)

    wm_service = WorkingMemoryService()
    monkeypatch.setattr(wm_service, "retrieve_similar", fake_retrieve_working)

    ep_service = EpisodicMemoryService(embeddings=type("E", (), {"embed": staticmethod(_fake_embed)})())
    monkeypatch.setattr(ep_service, "retrieve_similar", fake_retrieve_episodes)

    mo = MemoryOrchestrator(episodic_service=ep_service, core_service=core_service, working_service=wm_service)
    # Create a fake session and user
    fake_exec_result_for_history = MagicMock()
    fake_exec_result_for_history.scalars.return_value.all.return_value = []
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=fake_exec_result_for_history)
    user = FakeUser(id=1, name="Test", age=30, user_timezone="UTC", wake_time=None, bed_time=None, occupation_json=None)

    pack = asyncio.run(mo.assemble(fake_session, user, "Hi"))
    assert isinstance(pack.core_facts, list)
    assert pack.core_facts[0].fact_text == "Important fact"
