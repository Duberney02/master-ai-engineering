"""Separación en frases con el tokenizador Punkt de NLTK.

Los datos de Punkt (`punkt_tab`) se descargan al construir la imagen Docker (ver `Dockerfile`, `NLTK_DATA`):
en ejecución no se descarga nada. Si faltan, se falla con un mensaje claro en lugar de descargar a escondidas.
"""

import nltk


class SentenceTokenizerUnavailable(RuntimeError):
    """Faltan los datos de Punkt de NLTK."""


def split_sentences(text: str) -> list[str]:
    try:
        return [s.strip() for s in nltk.sent_tokenize(text, language="english") if s.strip()]
    except LookupError as exc:
        raise SentenceTokenizerUnavailable(
            "Faltan los datos 'punkt_tab' de NLTK (se instalan al construir la imagen)."
        ) from exc
