"""Jerarquía de errores del pipeline RAG de estimación (Sesión 9).

Cada etapa lanza su subclase para que la API traduzca el fallo al código HTTP adecuado y lo registre con un
`error_type` significativo. El mensaje de estas excepciones nunca llega al cliente: la API responde con un texto
genérico y el detalle va al log.
"""


class RagError(Exception):
    """Base de todos los errores del pipeline RAG."""


class EmbedderUnavailableError(RagError):
    """No hay servicio de embeddings (falta `OPENAI_API_KEY`)."""


class ReformulationError(RagError):
    """La reformulación falló incluso con la reescritura simple de respaldo."""


class RetrievalError(RagError):
    """No se pudo consultar el almacén vectorial o calcular el embedding de la consulta."""


class GenerationError(RagError):
    """La generación estructurada de la estimación falló sin remedio."""


class MalformedEstimateError(RagError):
    """La estimación incumple la regla de coherencia de `insufficient` tras un intento de reparación."""
