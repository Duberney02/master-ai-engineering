"""*Decay* temporal: resta peso a los finalistas obsoletos (Sesión 10).

Un embedding codifica lo que un chunk DICE, no cuándo se escribió ni si sigue siendo cierto: el presupuesto de AngularJS
de 2019 puede ser semánticamente perfecto y operativamente peligroso. El *decay* es la contrapartida BLANDA de un filtro
duro por fecha: en vez de excluir lo antiguo, multiplica su relevancia por una caída exponencial, de modo que la
recencia desempata sin silenciar el histórico.

`peso = 0.5 ** (edad_días / vida_media_días)`: un chunk con exactamente una vida media conserva la mitad de su
puntuación; la vida media por defecto es generosa (≈900 días, ≈2,5 años) porque los presupuestos envejecen despacio. Se
aplica AL FINAL, sobre los finalistas y DESPUÉS del reranking («lo blando, al cierre»): el cross-encoder, caro, decide
la relevancia y el *decay* solo ajusta el orden final. Nunca antes del reranking, o la recencia distorsionaría el
conjunto de candidatos que ve el reranker.

Precondición: la puntuación base debe ser NO NEGATIVA (el *decay* es un multiplicador en (0, 1]; con una base negativa
subiría hacia cero e invertiría el orden). Quien llama lo garantiza: el pipeline pasa los logits del reranker por una
sigmoide antes de llegar aquí.

Funciones puras y síncronas, sin llamadas al reloj: la fecha de referencia la inyecta quien llama (tests deterministas).
"""

from datetime import date

from app.generation.rag.schemas import RetrievedChunk


def decay_weight(age_days: float, half_life_days: float) -> float:
    """Multiplicador exponencial en `(0, 1]`.

    Una vida media no positiva desactiva el *decay* (peso 1.0); un chunk de fecha futura o sin edad no se penaliza.
    """
    if half_life_days <= 0 or age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def apply_temporal_decay(
    scored_chunks: list[tuple[RetrievedChunk, float]], *, half_life_days: float, reference_date: date
) -> list[tuple[RetrievedChunk, float]]:
    """Repondera `(chunk, puntuación_base)` por recencia y reordena de mejor a peor.

    Cada puntuación base (no negativa) se multiplica por el peso de su chunk según `document_date`; los chunks sin
    fecha conservan su puntuación (peso 1.0). Devuelve `(chunk, puntuación_con_decay)`. La ordenación es estable: ante
    una puntuación final igual, se conserva el orden previo.
    """
    weighted: list[tuple[RetrievedChunk, float]] = []
    for chunk, base in scored_chunks:
        if chunk.document_date is None:
            weight = 1.0
        else:
            weight = decay_weight((reference_date - chunk.document_date).days, half_life_days)
        weighted.append((chunk, base * weight))
    weighted.sort(key=lambda pair: pair[1], reverse=True)
    return weighted
