# Tasks

## 1. Inventario definitivo

- [x] 1.1 Convertir ambas matrices HTTP del diseño en casos de contrato trazables a código, incluidos parámetros, defaults, códigos, campos ausentes y nulos. Aceptación: nueve operaciones REST/SSE/salud y siete adicionales identificadas por método y consumidor.
- [x] 1.2 Confirmar consumidores de rutas, plantillas, estáticos, middleware, scripts, demo, dependencias y pruebas. Aceptación: lista de retirada y conservación con referencia para cada recurso compartido.

## 2. Caracterización del comportamiento

- [x] 2.1 Tras 1, preparar proyectos Compose de prueba propios con redes, bases y volúmenes efímeros independientes antes de ejecutar cualquier prueba. Verificar la titularidad de esos recursos y que la limpieza se limita a ellos, sin limpiezas globales ni intervenciones sobre PostgreSQL, Ollama, Open WebUI o sus recursos. Fijar fixtures Docker de estimaciones, sesiones, historial, adjuntos, vista previa y métricas. Aceptación: casos OK, no estimable, sin ID, expiración, error y estados de navegación reproducibles.
- [x] 2.2 Caracterizar Ajustes y Lab en HTML aislado con IA simulada. Aceptación: fixtures de siete campos, catálogo y primario, ocho estrategias, consultas, resultados jerárquicos y fallos de persistencia.
- [x] 2.3 Sembrar PostgreSQL efímero con comparaciones previas. Aceptación: fixture con IDs, payloads y datos de orden verificables en el corte.

## 3. API REST de Go

- [ ] 3.1 Tras 2, exponer sesiones y estimaciones explícitas. Verificar 201 UUID, valores opcionales, JSON, multipart repetido, URL-encoded admitido, adjuntos y referencias.
- [ ] 3.2 Exponer vista previa, historial, detalle y salud. Verificar defaults y forma de la vista previa sin memoria de sesión, datos de usuario ni llamadas al proveedor, versión y opciones inválidas, límites 1–50, ID ausente o inválido, historial indisponible y /up independiente de /health.
- [ ] 3.3 Aplicar límites de cabeceras, JSON, multipart y archivos, origen y limpieza de temporales. Verificar cuerpos sin Content-Length, Unicode válido, 404/405, 413/415/422 y guardrails 400 saneados, sin llamadas inesperadas.
- [ ] 3.4 Configurar conexión, espera de cabeceras y plazo total habitual y largo. Verificar cancelación hasta Python, 502/503/504 saneados en español, respuestas inválidas, mapeo de errores tipados, una generación válida que supera el plazo habitual y ausencia de reintentos de POST.

## 4. Intermediación SSE

- [ ] 4.1 Tras 3, intermediar las dos rutas con flush y un evento acotado en memoria. Verificar entrega incremental, fragmentación, comentarios, CRLF, datos multilínea, orden, cabeceras y metadatos.
- [ ] 4.2 Verificar HTTP previo, error terminal, EOF prematuro, secuencia inválida, inactividad, plazo total y cierre upstream ante cancelación. Aceptación: fallo saneado sin done falso ni reintento. En ambas rutas, cancelar tras el primer evento y comprobar que Python libera el generador y el recurso del proveedor, sin persistencia ni caché parcial.

## 5. Frontera de autorización

- [ ] 5.1 Tras 3, introducir decisión reutilizable en Go y denegar por defecto ante falta o fallo. Verificar 403 antes de invocar IA o almacenamiento en lecturas y mutaciones administrativas.
- [ ] 5.2 Componer fakes solo en pruebas y proteger toda coexistencia de rutas administrativas HTML. Verificar rechazo con cabeceras, cookies legacy, UUID conversacional y origen cruzado y que la imagen normal no puede activar el fake ni acepta credenciales predeterminadas. Verificar que el HTML transitorio conserva la cookie firmada, sus atributos, la compactación y los avisos flash, y rechaza con 422 las mutaciones sin token CSRF válido antes de invocar IA.

## 6. Comunicaciones de React

- [ ] 6.1 Tras 3 y 4, dirigir Vite/Nginx a Go para API y salud. Verificar rutas relativas, límites y plazos coordinados y flush SSE real tras Nginx.
- [ ] 6.2 Mantener contratos JSON/multipart y conectar AbortSignal. Verificar sesión inicial y nueva, 404 con borrador sin reenvío, TXT/PDF/DOCX y rechazo local con borrador intacto, carga y temporizador, prompt, historial, métricas y resultados con y sin ID. Al cancelar, verificar que se rehabilita el formulario sin mostrar un resultado parcial ni reenviar la solicitud.

## 7. Ajustes de IA en React

- [ ] 7.1 Tras 5, conectar GET/PUT de Ajustes al cliente existente. Probar catálogo filtrado, campos vigentes y por defecto, actualización parcial atómica, null, vacío sin llamada y mensajes saneados de Python.
- [ ] 7.2 Exponer proyección del primario con plazo corto configurable (2 s por defecto) y caché de 15 s. Probar caché de ausencia, invalidación al guardar y ausencia de datos del catálogo en la respuesta.
- [ ] 7.3 Tras 6 y 7.1–7.2, integrar selectores, embeddings de solo lectura, navegación, indicador, estados de error, reintento y confirmación con las convenciones visuales actuales. Verificar paridad, estado 403 en entrada directa con retorno a estimaciones, vista activa con `aria-current="page"` e inicio y navegación utilizables sin IA ni PostgreSQL.

## 8. Chunking Lab en React

- [ ] 8.1 Tras 5, exponer opciones y comparación reutilizando catálogo, corpus, adaptador y repositorio. Verificar ocho estrategias, avisos, consultas, `top_k=3` al omitirlo y en las opciones (DA-28), límites 1–10, valores válidos intactos, defaults ajenos al Lab preservados, validación, mapeo completo de errores, plazo largo y guardado 201 o resultado visible 200 con ID nulo.
- [ ] 8.2 Exponer historial y detalle en Go. Verificar 20 recientes, indisponibilidad, 404/500 y ausencia de llamadas a IA. Sembrar y crear IDs mayores que 2⁵³ − 1 para verificar alta, `Location`, listado, ruta React y detalle con dígitos exactos (DA-27), y comprobar que PostgreSQL conserva esquema, tipo y valor.
- [ ] 8.3 Tras 6 y 8.1–8.2, integrar navegación RAG y formularios, carga, errores, historial y detalle con estadísticas, costes y playground jerárquico. Probar conservación del formulario al fallar y recorridos con o sin datos guardados.

## 9. Verificación de paridad

- [ ] 9.1 Tras 6–8, ejecutar la matriz comparativa en Docker, incluidas acciones, resultados, avisos y errores. Aceptación: cada capacidad HTML tiene un recorrido React equivalente con IA simulada y autorización de pruebas donde aplica.
- [ ] 9.2 Verificar acceso a los mismos IDs y datos sembrados, avisos por fallo del repositorio y bloqueo en la composición normal. Registrar evidencia de aprobación del corte basada en resultados, sin depender del futuro sistema de identidad.

## 10. Retirada de HTML de Go

- [ ] 10.1 Solo tras 9, retirar la superficie del inventario HTML, dependencias de presentación y cookie legacy. Verificar rutas y formularios antiguos, ausencia de respuestas HTML Go y funcionamiento de /up.
- [ ] 10.2 Migrar pruebas de comportamiento y mantener casos de uso, validaciones, adaptadores, corpus y repositorio. Repetir paridad React y verificar conservación de registros, IDs y límites arquitectónicos.

## 11. Retirada completa de Streamlit

- [ ] 11.1 Tras 6, retirar app, cliente, utilidades y pruebas exclusivas, trasladar casos mixtos a fixtures neutros y conservar los recorridos REST/SSE.
- [ ] 11.2 Retirar la dependencia y regenerar uv.lock en Docker. Verificar que el lock y la imagen carecen de la dependencia del chat y mantienen dependencias compartidas.
- [ ] 11.3 Retirar la demo HTML de Python y su montaje exclusivo. Verificar ausencia de la página y conservación de las dos rutas SSE.

## 12. Dockerfiles, Compose y CI

- [ ] 12.1 Tras 10 y 11, eliminar arranque, mounts, variables y puerto 8501 de ambos Compose y del Dockerfile, y ajustar empaquetado Go/React. Verificar configuración e imágenes en Docker con valores ficticios, incluida la imagen mínima de Go sin privilegios y con sonda local.
- [ ] 12.2 Adaptar scripts, Compose de verificación y CI a sondas internas, API Go y suites en Docker. Verificar que funcionan sin chat ni FastAPI publicado.

## 13. Segmentación de redes

- [ ] 13.1 Tras 12, configurar client-net, service-net, go-data-net y ai-data-net y salida aislada de IA. Verificar seis servicios propios saludables, orden de arranque, sondas nativas, Redis Stack y conservación de estimaciones y comparaciones al reiniciar el proyecto con sus volúmenes. Comprobar que los recursos preexistentes de PostgreSQL, Ollama y Open WebUI quedan fuera del ciclo de vida del proyecto y que el aislamiento de 2.1 se mantiene.
- [ ] 13.2 Publicar solo 127.0.0.1:3001 y verificar acceso del operador autorizado por túnel SSH, ausencia de publicación IPv6 y fallo de acceso remoto directo sin túnel. Probar DNS, IP y TCP desde cliente, incluidos gateway, host y servicios preexistentes, y comprobar salida HTTPS simulada y credenciales exclusivas de IA.

## 14. Pruebas transversales

- [ ] 14.1 Tras 9–13, ejecutar recorridos React→Nginx→Go→IA en Docker, incluidos REST, SSE, sesiones, adjuntos, errores, historial y cancelación. Verificar con fakes, datos de prueba y sin proveedores reales. En REST, detener Python antes de escribir y cancelar desde React, luego repetir reteniendo la respuesta después de confirmar la escritura. Aceptación para ambos casos: Python observa el cierre y recibe un único POST. El primer caso deja cero filas y el segundo conserva exactamente una fila completa consultable. En las dos rutas SSE, verificar cierre hasta Python, liberación de recursos y ausencia de datos parciales o reintentos.
- [ ] 14.2 Ejecutar Vitest, compilación React, web-test, web-lint, api-test y api-lint en Docker. Verificar límites arquitectónicos, ausencia de autorización de pruebas en la imagen normal y regresiones de seguridad y aislamiento.
- [ ] 14.3 Auditar imágenes, configuración, fuentes y suites. Aceptación: sin interfaz independiente en Go ni referencias activas a Streamlit y con cobertura de comportamientos conservada, sin credenciales reales versionadas y con claves ficticias de proveedores inyectadas exclusivamente en estimador-cag.

## 15. Documentación y decisiones

- [ ] 15.1 Tras 13, actualizar en la futura implementación `AGENTS.md` y el contexto de `openspec/config.yaml` para registrar DA-01 a DA-28, con DA-27 y DA-28 aprobadas. Verificar importación por CLAUDE.md y dejar documentado el uso privado de desarrollo, exclusivo del operador por túnel SSH, sin exposición pública ni uso multiusuario hasta completar `homelab-authentication-authorization`, y el bloqueo administrativo por defecto.
- [ ] 15.2 Actualizar arquitectura, README, ejemplos e instrucciones operativas. Preparar revisión de propósitos obsoletos de las specs para el paso de integración de deltas cuando se autorice. Verificar que los documentos vigentes reflejan el túnel, las responsabilidades y la retirada de clientes históricos y que se conserva el archivo OpenSpec.

## 16. Validación final

- [ ] 16.1 Tras 14 y 15, revisar los once deltas y evidencias de paridad, aislamiento y bloqueo. Ejecutar OpenSpec status y validaciones estrictas individual y global, `git diff --check`, `git status --short`, `git ls-files --others --exclude-standard` y revisión independiente de los archivos sin seguimiento. Registrar cualquier fallo heredado e inspeccionar el alcance del diff.

## Trazabilidad de requisitos

Las tareas referenciadas contienen los criterios de aceptación de cada requisito. Los recorridos de paridad de 9.1–9.2 son obligatorios antes de 10.1.

| Delta | Requisito nuevo o modificado | Tareas de aceptación |
|---|---|---|
| deployment-stack | Compose raíz con todos los servicios | 6.1, 12.1, 13.1–13.2 |
| deployment-stack | Volúmenes y healthchecks | 3.2, 12.2, 13.1 |
| deployment-stack | Acceso acotado durante la integración | 5.1–5.2, 13.2, 15.1 |
| deployment-stack | Perfiles de desarrollo y verificación | 2.1, 6.1, 12.2, 13.1, 14.1–14.2 |
| deployment-stack | Credenciales exclusivas de IA | 12.1, 13.2, 14.3 |
| http-streaming | Intermediación pública de SSE | 4.1–4.2, 6.1, 14.1 |
| layered-architecture | Capas del servicio | 11.3, 14.1–14.2 |
| layered-architecture | Responsabilidades de la aplicación consolidada | 7.1, 8.1–8.2, 9.1, 10.1–10.2, 14.2 |
| prompt-preview | Vista previa del prompt de estimación | 3.2, 6.2, 14.1 |
| web-ai-settings | Pantalla de Ajustes | 7.1, 7.3, 9.1 |
| web-ai-settings | Guardar cambios | 7.1, 7.3, 9.1 |
| web-ai-settings | Indicador del modelo primario | 7.2–7.3, 9.1 |
| web-ai-settings | Consulta y actualización del catálogo | 7.1, 9.1 |
| web-backend-go | Chunking Lab con historial persistido | 2.3, 8.1–8.3, 9.2, 10.2 |
| web-backend-go | Ajustes de modelos y barra de navegación | 7.1–7.3, 9.1 |
| web-backend-go | Frontera con la API de IA | 3.4, 4.2, 6.1–6.2, 12.1, 14.1 |
| web-backend-go | Desarrollo y pruebas en Docker | 2.1, 12.1–12.2, 13.1, 14.2 |
| web-backend-go | Contratos JSON de Ajustes y Chunking Lab | 1.1, 5.1–5.2, 7.1–7.2, 8.1–8.2 |
| web-backend-go | Retirada del servidor HTML de aplicación | 1.2, 9.1–9.2, 10.1–10.2, 14.3 |
| web-backend-go | Contratos públicos de aplicación y salud | 1.1, 3.1–3.3, 4.1–4.2, 12.2 |
| web-backend-go | Seguridad de sesión, origen y administración | 3.1, 3.3, 5.1–5.2, 6.2, 9.2 |
| web-backend-go | Validación de transporte y errores de estimación | 3.1–3.4, 6.2, 14.1 |
| web-chunking-lab | Formulario del Chunking Lab | 8.1, 8.3, 9.1 |
| web-chunking-lab | Ejecución de la comparación | 8.1, 8.3, 9.1 |
| web-chunking-lab | Mapeo de errores del Lab | 8.1, 8.3, 9.1 |
| web-chunking-lab | Resultados | 8.3, 9.1 |
| web-chunking-lab | Historial persistido | 2.3, 8.1–8.3, 9.2, 13.1 |
| web-chunking-lab | Detalle de comparaciones existentes | 2.3, 8.1–8.3, 9.2, 10.2, 13.1 |
| web-client-contexts | Errores tipados y saneados | 3.3–3.4, 7.1, 8.1, 14.1 |
| web-client-contexts | Navegación por contexto | 7.3, 8.3, 9.1 |
| web-client-contexts | Estados de navegación administrativa | 7.3, 8.3, 9.2 |
| web-client | Retirada del cliente Streamlit | 11.1–11.3, 12.1–12.2, 14.3, 15.2 |
| web-client | Frontera del cliente web | 5.1–5.2, 6.1–6.2, 9.1–9.2, 10.1–10.2, 14.1 |
| web-react-client | Manejo de errores del cliente HTTP | 3.3–3.4, 6.1–6.2, 9.1 |
| web-react-client | Paridad funcional de la interfaz React | 6.2, 7.3, 8.3, 9.1–9.2 |
| web-react-client | Cliente web único con API de mismo origen | 6.1–6.2, 14.1 |

## Validación heredada

`openspec validate --all --strict` detecta que `session-11-calidad-generacion-rag` carece de deltas reconocidos. La resolución corresponde a ese cambio.
