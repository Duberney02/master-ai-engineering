# Verification

Todo se ejecutó en Docker desde la raíz del repositorio, rama `session_07/refined`.

| Comando | Resultado |
|---|---|
| `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed! |
| `docker compose -f docker-compose.verify.yml run --rm api-test` | **1202 passed, 13 skipped** (línea base 1164 tras el change de chunking: +38 pruebas, ninguna existente modificada salvo los dobles de caché semántica por la nueva firma) |
| `docker compose -f docker-compose.verify.yml run --rm openspec validate modelos-llm-en-runtime --strict` | Change is valid |
| `docker compose build estimador-cag` + OpenAPI de la imagen de producción | La imagen arranca y expone `/api/v1/config/models` y `/embeddings/compare` |
| Redis real (`redis:7-alpine`) + `RuntimeModelConfig` desde dos instancias | El «otro proceso» ve `{'primary_model': 'claude-sonnet-4-5', 'critic_model': 'gpt-4o'}`; `effective_settings` da `anthropic claude-sonnet-4-5`; tras `null` el hash queda vacío |
| Redis Stack real (`redis/redis-stack-server`) + `SemanticCache` con redisvl | Mismo modelo: acierto. `claude-sonnet-4-5` y `gpt-4o`: fallo (el filtro por tag con nombres con guiones funciona) |

## Contraste con la spec

- **Overrides persistentes y lectura degradable**: `tests/test_runtime_config.py` (almacén, persistencia entre instancias, campos ajenos ignorados, Redis caído al leer y al escribir, sin `redis_url`).
- **Resolución sin reiniciar**: la siguiente llamada usa el nuevo modelo y vuelve al anterior tras restablecer; primario de otro proveedor enruta al SDK de Anthropic; tarea de otro proveedor enruta a su SDK; override sin clave se ignora; `estimator_model` queda suplantado.
- **Fallback bajo override**: primario sobrescrito falla de forma reintentable y atiende el fallback configurado.
- **Cachés por modelo**: el pipeline usa claves exactas distintas y el filtro semántico correcto para cada modelo; `tests/test_semantic_cache.py` cubre el aislamiento, la entrada sin modelo y el nuevo nombre del índice.
- **API**: `tests/test_config_api.py` (17 pruebas): lectura, embeddings fuera de los knobs, catálogo filtrado por claves, parcial, `null`, 422 (knob, catálogo, proveedor del chunker), 400 con clave nombrada y sin filtrarla, todo-o-nada, 503 sin detalle interno, logs de auditoría (y su ausencia al rechazar) y aditividad de rutas.

## Limitaciones y notas

- La resolución es por solicitud (no por llamada); ver `design.md`. Una conversación ACB larga puede ver un cambio entre iteraciones, pero cada llamada es coherente consigo misma.
- No se ha ejecutado contra proveedores reales (sin claves); las pruebas usan SDK simulados y Redis simulado, más las comprobaciones con Redis reales de arriba.
- El índice de la caché semántica cambia de nombre (`…_by_model`): las entradas antiguas caducan por TTL.
