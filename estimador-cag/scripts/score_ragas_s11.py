#!/usr/bin/env python3
"""Puntúa muestras de generación con RAGAS (Sesión 11). ÚNICO módulo que importa `ragas`.

La recolección de muestras (`eval_ragas_s11.py --collect-only`) necesita la aplicación y la base de datos; la puntuación
solo necesita `ragas` y una clave de LLM. Mantenerlas separadas deja el resto de scripts (y las pruebas) sin importar
`ragas`, una dependencia pesada que arrastra `langchain` y que podría chocar con el lock de la aplicación: si lo hace,
este puntuador se ejecuta en un servicio de verificación propio sin tocar nada más.

Una MUESTRA es un objeto JSON::

    {"id": "G1", "user_input": "...", "response": "...", "retrieved_contexts": ["..."], "reference": "..." | null}

Las cuatro métricas son faithfulness, answer_relevancy, context_precision y context_recall; las dos últimas exigen
`reference` (ground truth). Las muestras sin referencia solo se puntúan con las dos primeras.

Uso (necesita `OPENAI_API_KEY` real: el juez de RAGAS es un LLM)::

    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/score_ragas_s11.py evals/ragas_samples_s11.json --out /tmp/scores.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
# Las que no necesitan `ground_truth` (las únicas posibles en el modo monitor, sin referencia).
REFERENCE_FREE = ("faithfulness", "answer_relevancy")
JUDGE_MODEL = os.getenv("RAGAS_JUDGE_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("RAGAS_EMBEDDING_MODEL", "text-embedding-3-small")


def _number(value: object) -> float | None:
    """Puntuación como `float`, o `None` si RAGAS no pudo calcularla (NaN)."""
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) else round(number, 4)


def score_samples(samples: list[dict], metrics: Sequence[str] = METRICS) -> list[dict[str, float | None]]:
    """Una fila `{métrica: puntuación}` por muestra, en el orden de entrada.

    Las métricas que necesitan `reference` se omiten para las muestras sin ella (las filas pueden diferir en claves).
    """
    unknown = set(metrics) - set(METRICS)
    if unknown:
        raise ValueError(f"métricas desconocidas: {sorted(unknown)}")

    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.dataset_schema import SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    available = {
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
        "context_precision": context_precision,
        "context_recall": context_recall,
    }
    llm = LangchainLLMWrapper(ChatOpenAI(model=JUDGE_MODEL, temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=EMBEDDING_MODEL))

    rows: list[dict[str, float | None]] = [{} for _ in samples]
    with_reference = [i for i, sample in enumerate(samples) if sample.get("reference")]
    for group, group_metrics in (
        (list(range(len(samples))), [m for m in metrics if m in REFERENCE_FREE]),
        (with_reference, [m for m in metrics if m not in REFERENCE_FREE]),
    ):
        if not group or not group_metrics:
            continue
        dataset = EvaluationDataset(
            samples=[
                SingleTurnSample(
                    user_input=samples[i]["user_input"],
                    response=samples[i]["response"],
                    retrieved_contexts=samples[i]["retrieved_contexts"],
                    reference=samples[i].get("reference"),
                )
                for i in group
            ]
        )
        result = evaluate(
            dataset, metrics=[available[m] for m in group_metrics], llm=llm, embeddings=embeddings, show_progress=False
        )
        frame = result.to_pandas()
        for position, index in enumerate(group):
            for metric in group_metrics:
                rows[index][metric] = _number(frame[metric].iloc[position])
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Puntúa muestras de generación con RAGAS.")
    parser.add_argument("samples", type=Path, help="JSON con la lista de muestras.")
    parser.add_argument("--out", type=Path, default=None, help="Dónde escribir las puntuaciones (JSON).")
    parser.add_argument("--metrics", nargs="+", default=list(METRICS), choices=METRICS)
    args = parser.parse_args(argv)

    if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "").startswith("sk-test"):
        print("ERROR: hace falta una OPENAI_API_KEY real (el juez de RAGAS es un LLM).", file=sys.stderr)
        return 2
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    rows = score_samples(samples, args.metrics)
    payload = [{"id": sample.get("id"), "scores": row} for sample, row in zip(samples, rows, strict=True)]
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Puntuaciones de {len(payload)} muestras escritas en {args.out}.")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
