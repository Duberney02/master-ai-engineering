"""Doble del generador del LLM para las pruebas de Actor–Critic–Boss.

Enruta cada llamada por su prompt de sistema (estimador, crítico, metadatos, resumen, anclas) y guarda
todas las llamadas para poder inspeccionarlas.
"""

import json

from app.services.llm_wrapper import Completion

CRITIC_MARKER = "revisor independiente"
METADATA_MARKER = "extractor de datos"
SUMMARY_MARKER = "encargado de la memoria"
ANCHOR_MARKER = "Eres un clasificador"


def estimation(summary="Proyecto mediano.", confidence=70, cost=20000) -> dict:
    phases = [
        {"name": "Diseño", "description": "UX", "duration_weeks": 2, "cost_eur": cost * 0.2},
        {"name": "Desarrollo", "description": "Portal", "duration_weeks": 8, "cost_eur": cost * 0.8},
    ]
    return {
        "summary": summary,
        "confidence_pct": confidence,
        "phases": phases,
        "total_duration_weeks": 10,
        "total_cost_eur": cost,
    }


def accept(confidence=0.9) -> dict:
    return {"verdict": "accept", "issues": [], "confidence": confidence}


def needs_iteration(description="El coste de desarrollo es irreal.", fix="Subir el coste a 30000.", **extra) -> dict:
    return {
        "verdict": "needs_iteration",
        "confidence": 0.8,
        "issues": [
            {
                "category": "unrealistic_estimate",
                "severity": "major",
                "affected_field": "total_cost_eur",
                "description": description,
                "suggested_fix": fix,
            }
        ],
        **extra,
    }


def reject(explanation="La transcripción no describe un proyecto.") -> dict:
    return {"verdict": "reject", "issues": [], "confidence": 0.95, "explanation": explanation}


class ScriptedGenerator:
    """`generate(messages, accept=, **options)` con colas por tipo de llamada."""

    def __init__(self):
        self.calls: list[tuple[list[dict], dict]] = []
        self.estimations: list[object] = []
        self.critic: list[object] = []
        self.default_estimation = estimation()
        self.default_critic: object = accept()

    @staticmethod
    def _text(item) -> str:
        return item if isinstance(item, str) else json.dumps(item)

    async def __call__(self, messages, accept=None, **options):
        self.calls.append((messages, options))
        system = messages[0]["content"]
        if CRITIC_MARKER in system:
            item = self.critic.pop(0) if self.critic else self.default_critic
        elif METADATA_MARKER in system:
            item = {}
        elif SUMMARY_MARKER in system:
            item = "Resumen."
        elif ANCHOR_MARKER in system:
            item = {"is_anchor": False, "rules": []}
        else:
            item = self.estimations.pop(0) if self.estimations else self.default_estimation
        if isinstance(item, Exception):
            raise item
        return Completion(
            text=self._text(item),
            model=options.get("model", "gpt-4o-mini"),
            provider="openai",
            finish_reason="stop",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.001,
            request_cost_usd=0.001,
        )

    def of(self, marker: str) -> list[tuple[list[dict], dict]]:
        return [call for call in self.calls if marker in call[0][0]["content"]]

    @property
    def estimator_calls(self):
        markers = (CRITIC_MARKER, METADATA_MARKER, SUMMARY_MARKER, ANCHOR_MARKER)
        return [c for c in self.calls if not any(m in c[0][0]["content"] for m in markers)]

    @property
    def critic_calls(self):
        return self.of(CRITIC_MARKER)
