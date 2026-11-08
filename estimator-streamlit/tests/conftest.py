"""Fixtures compartidas: un backend `estimator-web` simulado en la frontera HTTP (`httpx` del cliente).

Las pruebas nunca llaman a un servicio real ni usan claves.
"""

import uuid

import httpx
import pytest

DESCRIPTION = "Herramienta interna para planificar las vacaciones del equipo de soporte."
RESULT = {
    "summary": "Proyecto pequeño con calendario y aprobaciones.",
    "confidence_pct": 80,
    "phases": [
        {"name": "Diseño", "description": "Pantallas", "duration_weeks": 1, "cost_eur": 2400},
        {"name": "Desarrollo", "description": "Calendario", "duration_weeks": 4, "cost_eur": 9600},
    ],
    "total_duration_weeks": 5,
    "total_cost_eur": 12000,
}
OUT_OF_SCOPE = {
    "summary": "Out of scope: faltan procesos y objetivos.",
    "confidence_pct": 10,
    "phases": [{"name": "No estimable", "description": "x", "duration_weeks": 1, "cost_eur": 0}],
    "total_duration_weeks": 1,
    "total_cost_eur": 0,
}
EMPTY_FACTS = {"project_name": None, "assumed_team_size": None, "mentioned_technologies": [], "agreed_scope": None}
FACTS = {
    "project_name": "Vacaciones",
    "assumed_team_size": 3,
    "mentioned_technologies": ["Django", "PostgreSQL"],
    "agreed_scope": "Calendario y aprobaciones",
}
SYSTEM_PROMPT = "Eres un arquitecto sénior de estimación de software.\n\n## Contrato de salida (JSON)"
PREVIEW = {
    "prompt_version": "v3",
    "system_prompt": SYSTEM_PROMPT,
    "examples": [
        {"title": "Portal de reservas para un gimnasio", "description": "Web donde los socios reservan clases."},
        {"title": "Plataforma de IA para todo el hospital", "description": "Queremos una IA que mejore el hospital."},
    ],
}


def estimation_body(result=RESULT, facts=EMPTY_FACTS, prompt_version="v3", estimation_id=None, **metrics):
    return {
        "result": result | {"out_of_scope": result["confidence_pct"] < 30},
        "prompt_version": prompt_version,
        "estimation_id": estimation_id,
        "metrics": {
            "model": "gpt-4o-mini",
            "usage": {"input_tokens": 111, "output_tokens": 22, "total_tokens": 133},
            "latency_ms": 10,
            "cache_hit": False,
            "request_cost_usd": None,
        }
        | metrics,
        "project_metadata": facts,
    }


def reply(status, body, method="POST"):
    return httpx.Response(status, json=body, request=httpx.Request(method, "http://backend"))


class FakeBackend:
    """Backend `estimator-web` simulado: conversaciones, estimaciones y vista previa del prompt."""

    def __init__(self, mocker):
        self.conversations: list[str] = []
        self.estimates: list[dict] = []
        self.previews: list[dict] = []
        self.replies: list = []  # `httpx.Response` o excepción por estimación; vacío = respuesta correcta
        self.facts = EMPTY_FACTS
        self.result = RESULT
        self.preview_reply = None  # `httpx.Response` o excepción para la vista previa; None = correcta
        mocker.patch("estimator_chat.client.httpx.post", self.post)
        mocker.patch("estimator_chat.client.httpx.get", self.get)

    def post(self, url, **kwargs):
        if url.endswith("/api/conversations"):
            self.conversations.append(str(uuid.uuid4()))
            return reply(201, {"conversation_id": self.conversations[-1]})
        conversation_id = url.split("/api/conversations/")[1].split("/")[0]
        self.estimates.append({"url": url, "conversation_id": conversation_id, **kwargs})
        if self.replies:
            answer = self.replies.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        body = estimation_body(self.result, self.facts, kwargs["data"]["prompt_version"])
        return reply(200, body)

    def get(self, url, **kwargs):
        assert url.endswith("/api/prompt-preview"), url
        self.previews.append(kwargs["params"])
        if isinstance(self.preview_reply, Exception):
            raise self.preview_reply
        return self.preview_reply or reply(200, PREVIEW | {"prompt_version": kwargs["params"]["prompt_version"]}, "GET")


@pytest.fixture
def api(mocker) -> FakeBackend:
    return FakeBackend(mocker)
