"""Recuperación avanzada (Sesión 10): fusión, reranking, colecciones, routing, transformación de consulta y decay.

Cada módulo es una etapa pura o casi pura, sin acceso a `app.dependencies` (la composición vive allí): las etapas con
efectos (LLM, reranker, base de datos) reciben sus colaboradores por parámetro y se sustituyen en las pruebas.
"""
