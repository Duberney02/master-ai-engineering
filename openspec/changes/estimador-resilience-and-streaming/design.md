# Design

## Context

Véase proposal.md. La API usa dataclasses para resultados, Pydantic para contratos, SDK asíncronos y pruebas que sustituyen clientes en llm_service. Streamlit importa el servicio directamente. El prompt español y la evaluación de rangos son contratos que se conservan.

## Goals / Non-Goals

**Goals:** evolución aditiva, fallos saneados, pruebas sin llamadas pagadas y OpenSpec validable.

**Non-Goals:** migrar todo el historial anterior, añadir autenticación multiusuario, publicar servicios o garantizar ahorros/rendimiento sin medición.

## Decisions

- Conservar SDK nativos y sus adaptadores; extraer políticas comunes a un wrapper asíncrono con callbacks. LiteLLM agregaría otra capa sin necesidad para dos proveedores. El wrapper selecciona proveedor explícitamente, conserva metadatos y distingue errores recuperables.
- Redis usa redis.asyncio, timeout corto, TTL y namespace versionado. Caché deshabilitada sin REDIS_URL; Compose añade Redis interno. Clave SHA-256 de prompt, entrada, proveedor/modelo, fallback, límite, temperatura y razonamiento. No guardar errores, vacíos o truncamientos. Almacenar la misma estructura completa para streaming y respuesta normal, conservando finish_reason real. Sin bloqueo distribuido: solicitudes simultáneas idénticas pueden generar dos llamadas; no se promete deduplicación en vuelo.
- Tarifas por modelo configuradas mediante JSON, sin afirmar precios actuales. Sin tarifa se devuelve null. estimated_cost_usd representa coste original; request_cost_usd representa llamadas exitosas no cacheadas. Intentos fallidos podrían tener facturación no observable y se documenta.
- Fallback opcional ante 429/timeout/conexión/5xx del proveedor, sin fallback ante credenciales o solicitud inválida. SDK aplica reintentos; no duplicarlos en otra capa. En streaming solo se permite fallback antes del primer texto, cerrando siempre generadores y recursos.
- El endpoint SSE usa StreamingResponse con data JSON (texto escapado) y eventos token/metadata/done/error. Misma orquestación de dos fases, opciones y evaluación que el endpoint normal. Los controles inválidos se validan antes de iniciar la respuesta. Cancelación se propaga y no almacena resultados parciales.
- Streamlit usa httpx y un parser SSE aislado y probado; el contexto del prompt se mantiene local porque es puro y no requiere claves. Los errores se muestran aparte y las métricas se borran al comenzar una nueva solicitud.
- Logs usan structlog.get_logger() con eventos y campos nombrados. ProcessorFormatter integra registros estándar; JSONRenderer en producción y ConsoleRenderer en desarrollo. Un procesador conserva únicamente campos operativos permitidos y excluye claves, transcripciones y trazas con mensajes de proveedores. No registrar textos de excepciones externas.
- thinking_budget se habilita explícitamente solo en Anthropic; incompatible con fallback a OpenAI. La compatibilidad específica del modelo la determina el proveedor; su rechazo se comunica saneado.
- Presupuesto económico opcional mantiene intacta la tabla existente de horas y añade una tabla separada con validación Decimal/numérica y tarifas esperadas.

## Risks / Trade-offs

- Redis contiene respuestas de reuniones → desactivado por defecto, TTL configurable y sin puerto publicado en Compose; instalación destinada a un solo ámbito de confianza.
- Cambio de proveedor puede variar estimaciones → fallback opt-in, modelo real visible y nunca mezclar fragmentos.
- Datos de uso no disponibles → no inventar consumo/finalización; no cachear streaming sin terminación válida.
- Preprocesamiento retrasa el primer token → solo al solicitar two_phase y documentado.
- Caché de alto volumen de transcripciones → límite existente de 50000 caracteres y TTL; capacidad/evicción se configura en operación.

## Migration Plan

Agregar dependencias y variables opcionales; ejecutar pruebas antes y después. Mantener POST /estimate y sus campos anteriores. Activar Redis/fallback/precios mediante configuración. Cambiar chat a URL de API y dependencia healthy en Compose. Para rollback desactivar REDIS_URL/fallback o restaurar código anterior; namespace de caché impide interpretar formatos antiguos. Archivar el cambio OpenSpec únicamente tras verificaciones completas, o mantenerlo listo para revisión si hay limitaciones externas.
