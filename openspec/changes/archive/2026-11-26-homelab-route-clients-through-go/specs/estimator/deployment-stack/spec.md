# Spec Delta

## MODIFIED Requirements

### Requirement: Compose raíz con todos los servicios
El Compose raíz SHALL definir React/Nginx, Go, estimador-cag, PostgreSQL de Go, PostgreSQL de IA con pgvector y Redis Stack. SHALL conectar React y Go en `client-net`, Go e IA en `service-net`, Go y su PostgreSQL en `go-data-net`, e IA, Redis Stack y PostgreSQL de IA en `ai-data-net`. React SHALL apuntar su proxy a Go. Solo React/Nginx SHALL publicar un puerto en integración, enlazado a 127.0.0.1:3001 y accesible mediante túnel SSH. estimador-cag SHALL disponer de salida a proveedores cloud sin abrir puertos de entrada ni habilitar tránsito desde el cliente. Go SHALL recibir `ESTIMATOR_API_URL` y la IA SHALL recibir `REDIS_URL` y `DATABASE_URL` internos. El Compose SHALL NOT definir servicios Rails ni Streamlit.

#### Scenario: Web React tras el proxy
- **WHEN** el navegador solicita el historial en el origen React
- **THEN** Nginx llama a Go desde el mismo origen, sin CORS ni exposición de la URL interna, y Go consulta la API de IA por su red interna

#### Scenario: Aislamiento efectivo
- **WHEN** se prueba DNS y conexión directa por IP desde la red cliente y desde el host
- **THEN** el cliente alcanza a Go, falla al alcanzar IA, Redis, PostgreSQL u Ollama, el cliente tampoco alcanza esos servicios mediante el gateway o rutas y puertos del host, y el host no dispone de puertos publicados de backend o almacenes

#### Scenario: Salida de IA
- **WHEN** se prueba resolución y HTTPS desde IA hacia un proveedor simulado
- **THEN** la operación funciona sin publicar FastAPI

#### Scenario: Configuración válida
- **WHEN** se ejecuta docker compose config con valores ficticios
- **THEN** aparecen los seis servicios con las redes y publicaciones declaradas

#### Scenario: Arranque completo
- **WHEN** se levantan los servicios de integración con fakes
- **THEN** las sondas alcanzan healthy y React consulta el historial vía Go

### Requirement: Volúmenes y healthchecks
Los dos PostgreSQL y Redis Stack SHALL conservar sus volúmenes con nombre. Todos los servicios SHALL disponer de healthcheck y los dependientes SHALL esperar a los servicios necesarios mediante `condition: service_healthy`. Las sondas de PostgreSQL y Redis Stack SHALL usar `pg_isready` y `redis-cli ping`. Las sondas locales de Go, Nginx e IA SHALL usar respectivamente `/up`, `/healthz` y `/health` interno, sin generar estimaciones.

#### Scenario: Orden de arranque
- **WHEN** se inicia el stack
- **THEN** IA espera a sus almacenes, Go espera a IA y su PostgreSQL, y React espera a Go

#### Scenario: Persistencia entre reinicios
- **WHEN** se reinicia sin eliminar volúmenes
- **THEN** se conservan estimaciones y comparaciones existentes

## ADDED Requirements

### Requirement: Acceso acotado durante la integración
Hasta completar `homelab-authentication-authorization`, la aplicación SHALL operar exclusivamente como entorno privado de desarrollo, accesible solo por el operador autorizado mediante túnel SSH, sin exposición pública ni habilitación multiusuario. Go SHALL denegar por defecto las operaciones administrativas. React/Nginx SHALL carecer de ruta directa a IA y almacenes, incluidas rutas disponibles a través del host.

#### Scenario: Verificación de publicaciones
- **WHEN** se comprueban las publicaciones efectivas en IPv4 e IPv6 y se compara acceso por túnel SSH con acceso desde otra máquina sin túnel
- **THEN** el operador autorizado accede por el túnel, la conexión remota directa falla, Go, IA y almacenes carecen de publicaciones y una petición administrativa en la composición normal recibe 403


### Requirement: Perfiles de desarrollo y verificación
Vite SHALL dirigir API y salud a Go. Los Compose secundarios y de verificación SHALL mantener el aislamiento del despliegue de integración y SHALL usar sondas internas o fakes para comprobaciones de servicio. Los seis servicios del Compose raíz SHALL usar recursos propios del proyecto. PostgreSQL, Ollama y Open WebUI preexistentes del homelab y sus recursos SHALL quedar fuera del ciclo de vida de Compose del proyecto. Las pruebas SHALL usar proyectos Compose, redes, bases de datos y volúmenes independientes, con datos efímeros. Las operaciones de prueba SHALL NOT detener, modificar ni eliminar infraestructura preexistente, ejecutar limpiezas globales ni eliminar volúmenes de infraestructura.

#### Scenario: Recursos de prueba independientes
- **WHEN** se inspeccionan las configuraciones, se ejecutan las suites y se limpian sus recursos efímeros
- **THEN** los recursos de prueba tienen identidad propia, ningún servicio o recurso preexistente cambia y la limpieza se limita al proyecto de prueba

#### Scenario: Desarrollo y CI
- **WHEN** se valida el proxy de Vite y se ejecutan pruebas en Docker con credenciales ficticias
- **THEN** el flujo de navegador solo alcanza Go y los servicios de prueba funcionan sin publicar FastAPI en integración ni contactar proveedores reales

### Requirement: Credenciales exclusivas de IA
Las credenciales reales SHALL NOT versionarse. Las claves de proveedores SHALL cargarse desde entorno local excluido o secretos de despliegue en estimador-cag exclusivamente. Las contraseñas de PostgreSQL SHALL parametrizarse y las bases y usuarios SHALL mantenerse separados.

#### Scenario: Inspección de variables
- **WHEN** se renderiza Compose con valores ficticios y se inspeccionan los servicios
- **THEN** solo estimador-cag recibe claves de proveedores, cada base usa su propia configuración y los archivos versionados contienen únicamente valores ficticios o referencias a secretos

## REMOVED Requirements

### Requirement: Secretos fuera del repositorio
**Reason**: Se retira el contrato ligado a la interfaz o topología anterior.
**Migration**: La cobertura aplicable se traslada a «Credenciales exclusivas de IA» en este delta.
