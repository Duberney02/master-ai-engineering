"""Modelos en runtime: almacén en Redis, resolución efectiva por solicitud y su efecto en las llamadas al LLM."""

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.foundation.llm.runtime_config import (
    HASH_KEY,
    MODEL_KNOBS,
    RuntimeConfigUnavailable,
    RuntimeModelConfig,
    effective_settings,
    provider_for_model,
    task_model,
)
from app.foundation.llm.service import generate_from_messages, generate_from_prompts
from app.foundation.llm.wrapper import LLMWrapper, ProviderFailure
from tests._fakes import (
    anthropic_response,
    openai_response,
    patch_anthropic,
    patch_openai,
    patch_settings,
)

URL = "redis://fake:6379/0"


def make_settings(**kw) -> Settings:
    kw.setdefault("openai_api_key", "sk-test")
    kw.setdefault("redis_url", URL)
    return Settings(llm_provider="openai", _env_file=None, **kw)


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def redis(mocker, server):
    """Cada operación abre su propio cliente: los datos viven en el servidor simulado, como entre procesos."""

    def factory(url, **kwargs):
        assert url == URL
        return FakeAsyncRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    return mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=factory)


@pytest.fixture
def store(redis):
    return RuntimeModelConfig(make_settings())


# --- Almacén ----------------------------------------------------------------------------------------------


def test_the_knobs_cover_the_llm_models_but_not_the_embedding_model():
    assert set(MODEL_KNOBS) == {
        "primary_model",
        "fallback_model",
        "critic_model",
        "metadata_model",
        "summary_model",
        "propositional_chunker_model",
        "contextual_chunker_model",
    }
    assert "embedding_model" not in MODEL_KNOBS


async def test_without_overrides_the_snapshot_is_the_settings_defaults(store):
    snapshot = await store.snapshot()

    assert snapshot["primary_model"] == {"effective": "gpt-4o-mini", "default": "gpt-4o-mini", "overridden": False}
    # Las tareas sin modelo propio heredan el primario; el fallback sin configurar no tiene valor.
    assert snapshot["critic_model"]["default"] == "gpt-4o-mini"
    assert snapshot["fallback_model"] == {"effective": None, "default": None, "overridden": False}


async def test_set_and_reset_round_trip(store):
    await store.set_many({"primary_model": "gpt-4o", "critic_model": "gpt-4o"})
    snapshot = await store.snapshot()
    assert snapshot["primary_model"] == {"effective": "gpt-4o", "default": "gpt-4o-mini", "overridden": True}
    assert snapshot["metadata_model"]["overridden"] is False

    await store.set_many({"primary_model": None})
    assert (await store.snapshot())["primary_model"]["overridden"] is False
    assert await store.overrides() == {"critic_model": "gpt-4o"}


async def test_overrides_are_shared_between_processes_and_survive_restarts(redis):
    await RuntimeModelConfig(make_settings()).set_many({"primary_model": "gpt-4o"})

    assert await RuntimeModelConfig(make_settings()).overrides() == {"primary_model": "gpt-4o"}


async def test_unknown_stored_fields_are_ignored(store, server):
    await FakeAsyncRedis(server=server, decode_responses=True).hset(HASH_KEY, mapping={"x": "y", "primary_model": "gpt-4o"})

    assert await store.overrides() == {"primary_model": "gpt-4o"}


async def test_reads_degrade_to_defaults_when_redis_is_down(mocker):
    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=ConnectionError("down"))
    config = RuntimeModelConfig(make_settings())

    assert await config.overrides() == {}
    assert (await config.snapshot())["primary_model"]["effective"] == "gpt-4o-mini"
    settings = make_settings()
    assert await effective_settings(settings) is settings


async def test_writes_fail_visibly_when_redis_is_down_or_missing(mocker):
    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=ConnectionError("down"))
    with pytest.raises(RuntimeConfigUnavailable):
        await RuntimeModelConfig(make_settings()).set_many({"primary_model": "gpt-4o"})

    with pytest.raises(RuntimeConfigUnavailable):
        await RuntimeModelConfig(make_settings(redis_url=None)).set_many({"primary_model": "gpt-4o"})
    assert await RuntimeModelConfig(make_settings(redis_url=None)).overrides() == {}


def test_provider_is_inferred_from_the_model_name():
    assert provider_for_model("claude-sonnet-4-5", "openai") == "anthropic"
    assert provider_for_model("gpt-4o", "anthropic") == "openai"
    assert provider_for_model("o3-mini", "anthropic") == "openai"
    assert provider_for_model("mi-modelo", "anthropic") == "anthropic"


# --- Resolución efectiva ----------------------------------------------------------------------------------


async def test_effective_settings_applies_the_primary_override_and_its_provider(store):
    settings = make_settings(anthropic_api_key="sk-ant", estimator_model="gpt-4o")
    await store.set_many({"primary_model": "claude-sonnet-4-5"})

    effective = await effective_settings(settings)

    assert effective.effective_model() == "claude-sonnet-4-5" and effective.llm_provider == "anthropic"
    # El primario en runtime suplanta al modelo de estimación fijado en `.env`; los `Settings` originales no cambian.
    assert effective.estimator_model is None
    assert settings.llm_provider == "openai" and settings.effective_model() == "gpt-4o-mini"


async def test_effective_settings_applies_fallback_with_its_provider(store):
    settings = make_settings(anthropic_api_key="sk-ant")
    await store.set_many({"fallback_model": "claude-haiku-4-5"})

    effective = await effective_settings(settings)

    assert (effective.fallback_provider, effective.fallback_model) == ("anthropic", "claude-haiku-4-5")


async def test_effective_settings_applies_task_and_chunker_models(store):
    await store.set_many(
        {"critic_model": "gpt-4o", "summary_model": "gpt-4o", "propositional_chunker_model": "gpt-4o"}
    )

    effective = await effective_settings(make_settings())

    assert (effective.critic_model, effective.summary_model, effective.propositional_chunker_model) == ("gpt-4o",) * 3
    assert effective.metadata_model is None


async def test_an_override_whose_provider_has_no_key_is_ignored(store):
    await store.set_many({"primary_model": "claude-sonnet-4-5", "critic_model": "gpt-4o"})

    effective = await effective_settings(make_settings())  # sin clave de Anthropic

    assert effective.effective_model() == "gpt-4o-mini" and effective.llm_provider == "openai"
    assert effective.critic_model == "gpt-4o"


async def test_task_model_prefers_the_override_then_settings(store):
    settings = make_settings(summary_model="gpt-4o-mini")

    assert await task_model(settings, "summary_model") == "gpt-4o-mini"
    assert await task_model(settings, "critic_model") is None
    await store.set_many({"summary_model": "gpt-4o", "critic_model": "gpt-4o"})
    assert await task_model(settings, "summary_model") == "gpt-4o"
    assert await task_model(settings, "critic_model") == "gpt-4o"


# --- Efecto en las llamadas -------------------------------------------------------------------------------


async def test_the_next_call_uses_the_new_model_without_rebuilding_anything(mocker, store):
    patch_settings(mocker, make_settings())
    create = patch_openai(mocker, openai_response("uno"), openai_response("dos"), openai_response("tres"))

    await generate_from_prompts("sys", "usr")
    await store.set_many({"primary_model": "gpt-4o"})
    await generate_from_prompts("sys", "usr2")
    await store.set_many({"primary_model": None})
    await generate_from_prompts("sys", "usr3")

    assert [call.kwargs["model"] for call in create.await_args_list] == ["gpt-4o-mini", "gpt-4o", "gpt-4o-mini"]


async def test_overriding_the_primary_with_another_provider_routes_the_call_there(mocker, store):
    patch_settings(mocker, make_settings(anthropic_api_key="sk-ant"))
    openai = patch_openai(mocker, openai_response("x"))
    anthropic = patch_anthropic(mocker, anthropic_response("desde claude", model="claude-sonnet-4-5"))
    await store.set_many({"primary_model": "claude-sonnet-4-5"})

    completion = await generate_from_prompts("sys", "usr")

    assert completion.text == "desde claude" and completion.provider == "anthropic"
    assert anthropic.await_args.kwargs["model"] == "claude-sonnet-4-5" and openai.await_count == 0


async def test_a_task_model_of_another_provider_is_routed_to_its_own_sdk(mocker, store):
    patch_settings(mocker, make_settings(anthropic_api_key="sk-ant"))
    openai = patch_openai(mocker, openai_response("x"))
    anthropic = patch_anthropic(mocker, anthropic_response("resumen", model="claude-haiku-4-5"))

    completion = await generate_from_messages(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], model="claude-haiku-4-5"
    )

    assert completion.provider == "anthropic" and anthropic.await_count == 1 and openai.await_count == 0


async def test_fallback_runs_under_an_override(mocker, store):
    patch_settings(mocker, make_settings(anthropic_api_key="sk-ant", fallback_provider="anthropic", fallback_model="claude-haiku-4-5"))
    openai = patch_openai(mocker, ProviderFailure(503, "caído", retryable=True), ProviderFailure(503, "caído", retryable=True))
    anthropic = patch_anthropic(mocker, anthropic_response("rescate", model="claude-haiku-4-5"))
    await store.set_many({"primary_model": "gpt-4o"})

    completion = await generate_from_prompts("sys", "usr")

    # El primario efectivo (override) se intenta primero; el fallback configurado entra cuando falla de forma reintentable.
    assert openai.await_args_list[0].kwargs["model"] == "gpt-4o"
    assert completion.text == "rescate" and anthropic.await_args.kwargs["model"] == "claude-haiku-4-5"


def test_wrapper_targets_follow_the_provider_of_each_model():
    wrapper = LLMWrapper(make_settings(anthropic_api_key="sk-ant"))

    assert list(wrapper.targets("claude-sonnet-4-5", allow_fallback=False)) == [("anthropic", "claude-sonnet-4-5")]
    assert list(wrapper.targets("gpt-4o", allow_fallback=False)) == [("openai", "gpt-4o")]
    assert list(wrapper.targets("modelo-propio", allow_fallback=False)) == [("openai", "modelo-propio")]


# --- Caché exacta y semántica bajo un override ------------------------------------------------------------


async def test_pipeline_caches_are_keyed_by_the_effective_model(store):
    from app.domain.pipeline import EstimationPipeline
    from app.generation.cag.exact import make_result_key
    from tests.test_pipeline import GOOD, REQUEST, FakeGenerate, FakeGuardrails, Recorder

    class Exact:
        def __init__(self):
            self.gets, self.sets = [], []

        async def get(self, key):
            self.gets.append(key)

        async def set(self, key, value):
            self.sets.append(key)

    class Semantic:
        def __init__(self):
            self.lookups = []

        async def lookup(self, request, prompt_version, model=None):
            self.lookups.append(model)

        async def store(self, request, prompt_version, entry):
            return None

    rec = Recorder()
    exact, semantic = Exact(), Semantic()
    pipeline = EstimationPipeline(
        make_settings(),
        guardrails=FakeGuardrails(rec),
        exact_cache=exact,
        semantic_cache=semantic,
        generate=FakeGenerate(rec, GOOD, GOOD),
    )

    await pipeline.run(REQUEST, "v3")
    await store.set_many({"primary_model": "gpt-4o"})
    await pipeline.run(REQUEST, "v3")

    assert semantic.lookups == ["gpt-4o-mini", "gpt-4o"]
    assert exact.gets[0] == make_result_key(REQUEST, "v3", "openai", "gpt-4o-mini")
    assert exact.gets[1] == make_result_key(REQUEST, "v3", "openai", "gpt-4o")
    assert exact.gets[0] != exact.gets[1]
