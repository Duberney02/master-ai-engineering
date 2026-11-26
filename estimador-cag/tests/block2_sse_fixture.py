"""Upstream de integración para Go, con rutas FastAPI y dependencias simuladas."""

import asyncio
import os
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.responses import StreamingResponse

from app.api import estimations
from app.dependencies import get_history, get_pipeline
from app.domain.history import EstimationHistory
from app.domain.pipeline import EstimationPipeline
from app.domain.schemas import EstimationResult
from app.foundation.llm.wrapper import Completion
from app.main import app
from tests._fakes import openai_settings

settings = openai_settings(moderation_enabled=False)
engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
mode = ""
state = {}


@app.post("/__test/reset/{scenario}")
async def reset(scenario: str):
    global mode, state
    await history._ensure_schema()
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE estimations"))
    mode = scenario
    state = {
        "posts": 0,
        "provider_active": False,
        "provider_closed": False,
        "writing": False,
        "write_closed": False,
        "cache_writes": 0,
        "response_closed": False,
    }
    return state


@app.get("/__test/state")
async def get_state():
    async with engine.connect() as connection:
        rows = (
            await connection.execute(text("SELECT to_jsonb(e)::text FROM estimations AS e ORDER BY id"))
        ).scalars().all()
    return {**state, "committed": len(rows), "rows": rows}


@asynccontextmanager
async def provider():
    state["provider_active"] = True
    try:
        yield
    finally:
        state["provider_active"] = False
        state["provider_closed"] = True


class CacheProbe:
    async def get(self, key):
        return None

    async def lookup(self, request, version, model):
        return None

    async def set(self, key, payload):
        EstimationResult.model_validate(payload["result"])
        state["cache_writes"] += 1

    async def store(self, request, version, entry):
        EstimationResult.model_validate(entry.result)
        state["cache_writes"] += 1


async def fake_generation(system, user):
    async with provider():
        if mode == "before":
            await asyncio.Future()
        result = EstimationResult(
            summary="Resultado de prueba",
            confidence_pct=70,
            phases=[{"name": "Fase", "duration_weeks": 1, "cost_eur": 0}],
            total_duration_weeks=1,
            total_cost_eur=0,
        )
        return Completion(text=result.model_dump_json(exclude={"out_of_scope"}), model="fake", provider="openai")


class Pipeline(EstimationPipeline):
    def __init__(self):
        cache = CacheProbe()
        super().__init__(settings, exact_cache=cache, semantic_cache=cache, generate=fake_generation)

    async def check_input(self, request, prompt_version):
        state["posts"] += 1
        await super().check_input(request, prompt_version)


class GatedSession(AsyncSession):
    async def commit(self):
        try:
            if mode == "write":
                await self.flush()
                state["writing"] = True
                await asyncio.Future()
            await super().commit()
        finally:
            state["write_closed"] = True


class History(EstimationHistory):
    def _sessions(self):
        return async_sessionmaker(engine, expire_on_commit=False, class_=GatedSession)


history = History(settings, engine=engine)


async def fake_transcription(*args):
    state["posts"] += 1
    async with provider():
        yield "Primer token"
        await asyncio.Future()


@app.middleware("http")
async def hold_after_result(request, call_next):
    response = await call_next(request)
    if request.url.path != "/api/v1/estimate/stream" or mode != "after":
        return response
    original = response.body_iterator

    async def gated():
        try:
            async for chunk in original:
                yield chunk
                if chunk.startswith(b"event: result"):
                    await asyncio.Future()
        finally:
            await original.aclose()
            state["response_closed"] = True

    return StreamingResponse(gated(), status_code=response.status_code, headers=dict(response.headers))


app.dependency_overrides[get_pipeline] = Pipeline
app.dependency_overrides[get_history] = lambda: history
estimations.generate_estimation_stream = fake_transcription
