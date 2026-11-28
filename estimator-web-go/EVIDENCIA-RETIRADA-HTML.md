# Evidencia de retirada del cliente HTML de Go (tareas 10.1 y 10.2)

Base: `6322a1d`. Esta nota sustituye, para las referencias que dejan de ser válidas, a las pruebas Go de HTML citadas
en la referencia del Bloque 1 (`caracterizacion.md`) y en los documentos de verificación de los bloques, hoy consolidados en
`openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/verification.md`. Los originales se recuperan de Git (commit
`1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c`, misma carpeta; ver la sección «Recuperación de las evidencias originales»). Cada prueba retirada tiene una correspondencia explícita con cobertura vigente en Go (REST/SSE/frontera) o en
React (`estimator-web-react/src`). «Go» = `estimator-web-go/internal/…`.

## Referencias históricas afectadas

| Referencia histórica | Estado | Reemplazo |
|---|---|---|
| `security_test.go::TestTheHealthProbeAnswers200WithoutCallingAnyone` (E9, `/up`) | **Conservada con el mismo nombre** y archivo; ahora comprueba además `text/plain`, HEAD y ausencia de HTML | `web/security_test.go` |
| `estimations_test.go` (E3–E5, «consumidores») | Retirada | Filas «estimations_test.go» abajo |
| `home_test.go`, `settings_test.go`, `lab_test.go` (A1–A7, A3 badge) | Retiradas | Filas respectivas abajo; contratos A1–A7 ya cubiertos por `api_admin_test.go` |
| `TestLegacyLabPostWithoutTopKUsesOne` (2.2, `lab_test.go`) | Retirada: era una inconsistencia histórica del formulario HTML (1 sin `top_k`) | `api_admin_test.go::TestLabCreateNormalizesTopKPerDA28` (3 por defecto, DA-28) |
| `security_test.go`, `session_test.go` (5.2: cookie firmada, atributos, compactación, flash, 422 sin CSRF) | Retiradas con `internal/session` | Filas «security_test.go» y «session_test.go» |
| `internal/web/server.go` L90–L125, `templates.go`, `estimations.go`, `settings.go`, `lab.go` (enlaces del diseño) | Archivos eliminados | Registro de rutas en `server.go::Handler` y `api.go::apiHandler` |

## Pruebas retiradas → cobertura vigente

### `home_test.go` (inicio, barra, indicador del primario)

| Prueba retirada | Cobertura vigente |
|---|---|
| Landing con una tarjeta por contexto; inicio sin IA; layout sin servicio | React `pages.test.tsx`: «ofrece las cuatro entradas…», «el inicio y la navegación son utilizables sin IA ni PostgreSQL»; Go: `TestRetiredHTMLRoutesAnswerJSON404WithoutEffects` (`/` ya no existe y no llama a IA) |
| Barra con el modelo primario efectivo; sección activa; indicador ausente | React `pages.test.tsx`: «muestra el modelo primario y solo enlaza a Ajustes cuando Go ya concedió acceso», «sin servicio…omite el indicador», «un valor ausente no deja indicador»; Go `TestPrimaryModelProjectionIsPublicAndOmitsTheCatalog` |
| Reenvío del formulario marca historial como Rails | React `pages.test.tsx`: «la sección RAG sigue activa…» (navegación activa); sin equivalente de cookie |
| Badge cacheado 15 s; fallo cacheado; nil ante timeout/500/malformada; expiración e invalidación | Go `TestPrimaryModelCachesAbsenceAndFailureForFifteenSeconds`, `TestPrimaryModelUsesTheShortConfigurableDeadline`, `TestBadgeCache*` (5 pruebas de concurrencia, TTL e invalidación), `TestSettingsWriteInvalidatesThePrimaryProjection` |

### `settings_test.go` (Ajustes HTML → `PUT/GET /api/v1/ai/settings`)

| Prueba retirada | Cobertura vigente (`api_admin_test.go`) |
|---|---|
| Siete knobs con defecto y vigente; opción vacía = restablecer; override preseleccionado; chunkers por proveedor | `TestSettingsReadProjectsTheCatalogWithNullsAndProviderFilters`; React `admin.test.tsx` («muestra los siete knobs…», «los chunkers solo ofrecen los modelos de su proveedor») |
| Update envía todos los knobs, blancos→nulos, confirma; refresca el indicador | `TestSettingsWriteSendsEveryKnobAndConvertsEmptyToNull`, `TestSettingsWriteInvalidatesThePrimaryProjection`; React «guarda los siete campos…» |
| Ignora knobs desconocidos; sin modelos no llama al servicio | `TestSettingsWriteWithoutRecognizedFieldsNeverCallsTheService`, `TestSettingsRejectionIsPrefixedOnlyOnWriteAndKeepsTheAtomicRequestWhole` |
| PUT aceptado además de PATCH | Contrato vigente solo `PUT` (`TestAdminRoutesRejectUnsupportedMethodsAndUnknownSubpaths`); PATCH/POST `_method` retirados (`TestRetiredHTMLRoutesAnswerJSON404WithoutEffects`) |
| Rechazo con detalle y formulario conservado; 503 de almacén; servicio inalcanzable; error del servidor en lectura | `TestSettingsErrorsAreSanitizedAndNeverRetried`, `TestSettingsRejectionLeavesTheBadgeCacheUntouched`; React «un rechazo muestra el aviso saneado…», «si falla la lectura inicial…» |

### `lab_test.go` (Chunking Lab HTML → `/api/v1/rag/chunking-comparisons`)

| Prueba retirada | Cobertura vigente |
|---|---|
| `new`: gratuitas preseleccionadas, de pago marcadas; consultas y `top_k` | `TestLabOptionsExposeTheCatalogDefaultsAndLimits` |
| `create` envía corpus, estrategias, consultas y `top_k`, guarda y redirige | `TestLabCreateSavesAndReturnsDecimalIDLocationAndOrderedResult` (201 + `Location`) y `pg_test.go::TestLabEndToEndWithPostgreSQL` (migrada a REST con PostgreSQL) |
| Ignora estrategias desconocidas, deduplica, acota `top_k` | `TestLabCreateFiltersStrategiesAndNormalizesQueriesWithoutArbitraryLimits`, `TestLabCreateNormalizesTopKPerDA28` |
| Sin estrategias se rechaza antes de llamar | `TestLabCreateRejectsEmptySelectionAndBadShapesBeforeCallingAI` |
| Plazo ampliado solo para esta llamada | `TestLabTimeoutDoesNotWidenTheOtherOperations` |
| Errores del servicio → estado y mensaje saneado; timeout 504 | `TestLabCreateMapsEveryAIErrorWithoutRetries` |
| Fallo al guardar o sin base: se muestra igualmente | `TestLabCreateWithSaveFailureReturnsTheResultWithNullIDAndWarning` |
| `show`: tabla de estadísticas, barras, playground; run solo estadísticas; 404; BD caída → error | `TestLabDetailReturnsTheStoredRunAndMapsTheFailures`; React `admin.test.tsx` (estadísticas, barras, similitud, extractos); `pg_test.go::TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL` |
| `index`: recientes primero sin llamar a IA; vacío; BD no disponible | `TestLabListReturnsTheTwentyNewestWithoutCallingAI`, `TestLabListWithUnavailableHistoryIsEmptyWithAWarning`; React `admin.test.tsx` |
| `TestLegacyLabPostWithoutTopKUsesOne` | Ver tabla anterior (DA-28) |

### `estimations_test.go` y `conversation_test.go` (estimaciones, conversación)

| Prueba retirada | Cobertura vigente |
|---|---|
| Formulario con campos, carga `.txt`, indicador, temporizador, contador | React `pages.test.tsx` («muestra el formulario, el contador…», «durante el envío deshabilita el botón…», «al cargar un .txt válido…») |
| Envío válido → API → redirección al detalle guardado; sin `estimation_id` resultado en línea | Go `TestPublicRESTContracts` (turno con `estimation_id:null` y `/estimate`); React «una descripción válida llama a la API y navega al detalle», «sin estimation_id muestra el resultado en línea…» |
| `.txt` sustituye la descripción; 80 000 caracteres; corta/larga rechazadas sin llamar; archivos inválidos | Go `TestPublicJSONKeepsMaximumUnicodeDescription`, `TestInvalidRESTTransportNeverCallsUpstream`, `TestTurnLimitsRejectOversizedAndUnsupportedParts`; React «una descripción fuera de rango…»; reglas de formulario: `estimation/form_test.go` (conservada, 17 pruebas) |
| Formulario conserva valores; guardrail muestra el mensaje; API inalcanzable saneada; error 5xx sin cuerpo crudo; respuesta inválida | Go `TestPublicErrorsAndHealthAreSanitized` (400 con `reason`, 503, 404 sin cuerpo interno), `TestRESTRejectsInvalidUpstreamContracts` (502), **nueva** `TestAnUnreachableAIServiceIsASanitized503OnEveryPublicRoute`; React «tras un error de la API conserva los datos…», «con la API caída muestra el mensaje de conexión…» |
| Resultado con duración, coste, confianza y fases; baja confianza «No estimable»; descripción truncada | React `pages.test.tsx` («carga la estimación, sus métricas…», «un resultado out_of_scope muestra «No estimable» sin cifras»), `lib/format.test.ts` |
| Estimación inexistente → 404; ID no numérico → 404 sin llamar; API inalcanzable en el detalle | Go `TestInvalidRESTTransportNeverCallsUpstream` (ID inválido 422 sin upstream; el 404 HTML pasa a 422 FastAPI, ya anotado en E5); React «un identificador no numérico muestra el error…», «una estimación inexistente…» |
| Historial: lista enlazada, vacío, deshabilitado (503), API caída | Go `TestPublicRESTContracts` (`/api/v1/estimations?limit=10`); React «lista las estimaciones…», «trunca el extracto a 90 caracteres», «con la lista vacía…», «con 503 muestra un aviso…» |
| Barra lateral: prompt de sistema, ejemplos, métricas, caché y precios desconocidos, registro viejo sin métricas, prompt no renderizable, página de error sin barra | Go `TestPublicRESTContracts` (`/prompts/estimation` ignora `session_id`); React «muestra el formulario…el prompt por defecto en la barra», «al cambiar las opciones la barra pide el prompt…», «si el prompt no se puede renderizar avisa…», «el botón de la barra la oculta…», «carga la estimación, sus métricas…» |
| Sesión creada una vez y conservada; reintento si falló al cargar; envío a la sesión creada | Go `TestPublicRESTContracts` (`POST /sessions`), `TestRESTSessionRequiresExactSessionIDKey`; React `conversation.test.tsx` («crea una sesión al cargar…», «si la creación de la sesión falló al cargar, el envío la reintenta») |
| Adjuntos múltiples multipart, mensaje corto con adjuntos, valor vacío ignorado, inválidos sin llamar, rechazo del servidor | Go `TestMultipartTurnPreservesRepeatedFileParts`, `TestTurnLimitsRejectOversizedAndUnsupportedParts`; React «permite seleccionar varios adjuntos…», «un rechazo de adjunto del servidor…» |
| Metadatos en la barra y en pantallas posteriores; metadatos enormes no desbordan la cookie | React «muestra los project_metadata…», «los metadatos se conservan al navegar…»; **sin equivalente** para el desbordamiento de cookie (la cookie ya no existe: `TestNoHTMLPresentationDependenciesRemain`) |
| «Nueva conversación» abre otra sesión y limpia metadatos; funciona aunque la API falle; sesión perdida abre otra y avisa | React ««Nueva conversación» crea otra sesión…», «si la API perdió la sesión abre otra, avisa y conserva lo escrito», «tras el 404 de sesión no se reenvía…» |

### `security_test.go`

| Prueba retirada | Cobertura vigente (`web/security_test.go` salvo indicación) |
|---|---|
| `TestTheHealthProbeAnswers200WithoutCallingAnyone` | Conservada (mismo nombre) |
| `TestUnknownRoutesAreA404Page`, `TestStaticPublicFilesAreServed` | `TestRetiredHTMLRoutesAnswerJSON404WithoutEffects` (rutas, métodos, estáticos `robots.txt`/`404.html`/`422.html`/`500.html`) |
| CSRF: sin token, token erróneo, token en cabecera, formularios con token | Retiradas con el formulario. La protección de mutaciones es la validación de origen: `TestMutationsStillRejectForeignOriginOnRetiredAndLiveRoutes`, `authorization_test.go::TestOriginRejectionPrecedesUpstream`, `api_admin_test.go::TestAdminMutationsRejectCrossOriginBeforeAnyEffect` |
| Cookie manipulada = sesión vacía; cookie `HttpOnly`/`SameSite=Lax` | Sin sesión que manipular. `TestLegacySessionCookieIsNeverIssuedAndIsExpiredWhenSent` (nunca se emite; la legada se expira con `Max-Age=0`, `Path=/`, `HttpOnly`); `authorization_test.go` envía la cookie legada y falsifica cabeceras sin efecto |
| Cuerpo sobredimensionado rechazado (HTML, 64 MiB) | Límites REST vigentes: `api_test.go::TestInvalidRESTTransportNeverCallsUpstream` (413 JSON) y `TestTurnLimitsRejectOversizedAndUnsupportedParts` (413 adjunto) |
| `TestAPanicInAHandlerIsASanitized500` | **Migrada con el mismo nombre**: `recoverer` devuelve 500 JSON saneado, sin traza ni cadena de consulta en el registro; nuevas `TestAPanicAfterTheResponseStartedAbortsInsteadOfAppendingAnError`, `TestRequestLogsCarryTheRoutePatternWithoutSessionIDsOrQueries` |

### `session_test.go` (`internal/session`, eliminado)

| Prueba retirada | Cobertura vigente |
|---|---|
| Conversación y metadatos sobreviven a la cookie; reinicio; compactado de metadatos enormes; cookie ajena = vacía; flash una vez; `FlashNow`; token CSRF; atributos de la cookie | Sin consumidor: la conversación vive en React (UUID de sesión de la API, `conversation.test.tsx`); metadatos en el JSON de la API (`TestRESTPreservesAdditiveFieldsAndExactNumbers`). `TestNoHTMLPresentationDependenciesRemain` impide reintroducir el paquete, `html/template`, `cookiejar`, `SecretKeyBase` y CSRF de formulario |

### `format_test.go` (funciones de presentación, eliminado con `format.go`)

| Prueba retirada | Cobertura vigente |
|---|---|
| `formatCost`, `formatWeeks`, `formatUSD`, helpers numéricos, `delimited`, `formatTime`, `truncate`, etiquetas y fuentes de caché, `roundedPct`/`plainInt` | React `lib/format.test.ts` (etiquetas, procedencia, coste EUR, semanas, USD, fecha UTC, motivo fuera de alcance, enteros con miles, truncado) |

### `pg_test.go` (migrado, no retirado)

`TestLabEndToEndWithPostgreSQL` y `TestLabHistoryPersistsAcrossServerInstances` pasan de formulario/redirección HTML a REST
(201 + `Location`, detalle, historial, 404). `TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL` y
`TestLabAtomicPersistenceInPostgreSQL` se conservan sin cambios. Se mantienen los IDs, el esquema y los registros.

## Verificación de paridad aplicable a 10.2

- Contratos REST/SSE, autorización administrativa (`authorization_test.go`, `api_admin_test.go`), repositorio
  (`internal/rag`, `pg_test.go`), adaptadores (`internal/estimatorai`), corpus y reglas (`internal/estimation`,
  `internal/ai`) siguen en verde sin modificar sus pruebas.
- Límites arquitectónicos: `internal/archtest` actualizado solo para quitar `session` y su importación desde `web`; sin
  excepciones nuevas.
- La paridad React de 9.1–9.2 se comprueba hoy con `verification/verify-parity.sh` (`verification/parity.json` y
  `verification/parity-check.mjs`, de solo lectura): el resultado figura en `verification.md`.
