"""Detección de anclas: reglas heurísticas con nombre y detector LLM con respaldo."""

import json

import pytest

from app.services.anchors import (
    AnchorVerdict,
    HeuristicAnchorDetector,
    LLMAnchorDetector,
    build_anchor_detector,
    fold,
)
from app.services.llm_wrapper import Completion
from tests._fakes import openai_settings

detector = HeuristicAnchorDetector()


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Ya firmamos el contrato con el cliente la semana pasada.", "contract"),
        ("Tenemos una orden de compra aprobada por finanzas.", "contract"),
        ("El alcance está cerrado: solo el portal de pedidos.", "closed_scope"),
        ("Congelamos el alcance, sin cambios de alcance hasta el lanzamiento.", "closed_scope"),
        ("El presupuesto acordado es de 45.000 euros.", "agreed_budget"),
        ("No podemos superar 30000 EUR en total.", "agreed_budget"),
        ("La fecha límite es el 15 de marzo, es inamovible.", "deadline"),
        ("Hay que entregar antes del 30 de junio.", "deadline"),
        ("Debemos cumplir el RGPD y la normativa de protección de datos.", "legal_regulatory"),
        ("Los datos son confidenciales y hay un NDA firmado.", "legal_regulatory"),
    ],
)
async def test_heuristic_rules_identify_each_kind_of_commitment(text, rule):
    match = await detector.detect(text, "respuesta del asistente")

    assert match is not None and rule in match.rules and match.source == "heuristic"


async def test_a_single_turn_can_match_several_rules_in_a_stable_order():
    match = await detector.detect(
        "Contrato firmado, presupuesto acordado de 20000 euros y fecha límite el 1 de julio.", ""
    )

    assert match.rules == ("contract", "agreed_budget", "deadline")


@pytest.mark.parametrize(
    "text",
    [
        "Queremos una aplicación para gestionar pedidos y facturas de los clientes.",
        "Quizá podríamos añadir notificaciones push más adelante, ¿qué os parece?",
        "El equipo usa React y PostgreSQL y quiere un panel de administración.",
    ],
)
async def test_ordinary_turns_are_not_anchors(text):
    assert await detector.detect(text, "") is None


async def test_only_the_user_message_is_evaluated():
    # La estimación del asistente siempre habla de costes y plazos: no debe convertir el turno en ancla.
    assert await detector.detect("Queremos una web sencilla.", "presupuesto acordado, fecha límite, contrato") is None


def test_fold_removes_accents_and_case():
    assert fold("Fecha LÍMITE · Ñandú") == "fecha limite · nandu"


# --- Detector LLM ---


def _generator(*texts_or_errors):
    calls = []
    queue = list(texts_or_errors)

    async def generate(messages, accept=None, **options):
        calls.append((messages, options))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return Completion(text=item if isinstance(item, str) else json.dumps(item), model="m", provider="openai")

    generate.calls = calls
    return generate


async def test_llm_detector_returns_the_rules_chosen_by_the_model():
    generate = _generator({"is_anchor": True, "rules": ["agreed_budget", "deadline"]})
    llm = LLMAnchorDetector(openai_settings(summary_model="modelo-barato"), generate=generate)

    match = await llm.detect("Presupuesto cerrado en 10k y entrega en mayo", "ok")

    assert match.rules == ("agreed_budget", "deadline") and match.source == "llm"
    messages, options = generate.calls[0]
    assert "Presupuesto cerrado" in messages[1]["content"]
    assert options["model"] == "modelo-barato"


async def test_llm_detector_says_no_when_the_model_does():
    llm = LLMAnchorDetector(openai_settings(), generate=_generator({"is_anchor": False, "rules": []}))

    assert await llm.detect("hola", "hola") is None


async def test_llm_anchor_without_rules_gets_a_placeholder_rule():
    llm = LLMAnchorDetector(openai_settings(), generate=_generator({"is_anchor": True, "rules": []}))

    assert (await llm.detect("x", "y")).rules == ("llm_unspecified",)


async def test_llm_detector_falls_back_to_the_heuristic_when_the_provider_fails():
    llm = LLMAnchorDetector(openai_settings(), generate=_generator(RuntimeError("caído")))

    match = await llm.detect("El contrato está firmado.", "")

    assert match.rules == ("contract",) and match.source == "heuristic"


async def test_llm_detector_falls_back_when_the_answer_is_never_valid():
    llm = LLMAnchorDetector(openai_settings(), generate=_generator("no es json", "tampoco"))

    assert await llm.detect("Hola, sin compromisos", "") is None
    match = await LLMAnchorDetector(openai_settings(), generate=_generator("no es json", "tampoco")).detect(
        "Fecha límite el 3 de mayo", ""
    )
    assert match.rules == ("deadline",)


def test_unknown_rule_names_are_rejected_by_the_verdict_schema():
    with pytest.raises(ValueError):
        AnchorVerdict.model_validate({"is_anchor": True, "rules": ["inventada"]})


def test_the_detector_mode_selects_the_implementation():
    assert isinstance(build_anchor_detector(openai_settings()), HeuristicAnchorDetector)
    assert isinstance(build_anchor_detector(openai_settings(anchor_detection_mode="llm")), LLMAnchorDetector)
