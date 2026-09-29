# Tasks

## 1. OpenSpec y base

- [x] 1.1 Inicializar OpenSpec/Codex, documentar comandos y contexto; verificar validate --strict y versión de CLI.
- [x] 1.2 Registrar línea base pytest y agregar dependencias de ejecución Redis/httpx; verificar instalación con uv y lock actualizado.

## 2. Generación resiliente

- [x] 2.1 Implementar configuración, wrapper asíncrono, caché TTL, fallback y costes; probar acierto, fallo, corrupción, expiración, aislamiento y recuperación real entre adaptadores simulados.
- [x] 2.2 Integrar fases y streaming con métricas reales y cierre de recursos; probar cancelación, truncamiento y fallo después de texto sin fallback.
- [x] 2.3 Incorporar logs estructurados y documentación de configuración/costes; probar JSON sin datos sensibles.

## 3. Opciones de estimación

- [x] 3.1 Añadir thinking_budget y validación por proveedor; probar kwargs y rechazo antes de E/S y documentar límites.
- [x] 3.2 Añadir presupuesto de proyecto opcional y evaluación monetaria; probar tarifas, decimales, sumas incorrectas y compatibilidad del formato anterior; documentar solicitud.

## 4. Transporte y clientes

- [x] 4.1 Implementar SSE, metadatos, evaluación y errores; probar eventos multilínea, validación, dos fases y fallo sin done; documentar contrato.
- [x] 4.2 Migrar Streamlit a HTTP manteniendo panel e historial, agregar limpieza y demo HTML; probar parser SSE y AppTest con transporte simulado.
- [x] 4.3 Actualizar Compose/CI para Redis interno y chat sin claves, documentar arranque; verificar configuración y checks disponibles.

## 5. Integración

- [x] 5.1 Ejecutar suite completa, comprobaciones de sintaxis, OpenSpec estricto y revisión de diff; registrar resultados y limitaciones en verificación.

## 6. Registro con structlog

- [x] 6.1 Migrar todos los loggers de aplicación a structlog.get_logger(), configurar renderizadores y filtrado de campos; verificar JSON, consola, nivel, interoperabilidad y ausencia de secretos con pytest; actualizar dependencia, lock y documentación.

## 7. Tarifas de ejemplo

- [x] 7.1 Consultar fuentes oficiales de OpenAI y Anthropic, completar MODEL_PRICES en .env.example con fecha, unidades y alcance, y verificar carga con el esquema de configuración.
