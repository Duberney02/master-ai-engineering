ESTIMATION_EXAMPLES: list[dict[str, str]] = [
    {
        "meeting_summary": (
            "El cliente Comercial Andina necesita una plataforma web para gestionar "
            "su inventario de más de 5 000 SKUs. Actualmente usan hojas de cálculo. "
            "Requieren: registro y edición de productos, control de stock con alertas "
            "de mínimo, historial de movimientos, dashboard con métricas clave "
            "(rotación, valorización), autenticación por roles (admin, bodeguero, "
            "gerente), exportación a Excel y despliegue en AWS. Stack preferido: "
            "React + FastAPI + PostgreSQL. Tienen equipo de QA interno. "
            "El plazo deseado es 3 meses."
        ),
        "estimation": """\
## Estimación: Plataforma de Gestión de Inventario — Comercial Andina

### Supuestos
- Diseño UI/UX incluye 2 rondas de revisión; cambios mayores fuera de alcance.
- Autenticación vía JWT; sin SSO ni LDAP.
- Base de datos PostgreSQL en RDS; sin alta disponibilidad multi-región.
- Exportaciones CSV/Excel generadas en el servidor; sin reportes BI complejos.
- El equipo de QA del cliente ejecuta pruebas de aceptación; el equipo dev entrega pruebas unitarias e integración.
- CI/CD básico con GitHub Actions hacia staging y producción en AWS ECS.

### Requisitos identificados
- CRUD de productos y categorías
- Control de stock con alertas de mínimo
- Historial de movimientos de inventario
- Dashboard con métricas (rotación, valorización)
- Autenticación con roles (admin, bodeguero, gerente)
- Exportación a Excel/CSV
- Despliegue en AWS

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | Diseño | Wireframes y flujos UX (5 pantallas principales) | 24 |
| 2 | Diseño | Prototipo interactivo y revisiones | 16 |
| 3 | Backend | Modelado de base de datos y migraciones | 12 |
| 4 | Backend | API REST: productos y categorías (CRUD) | 20 |
| 5 | Backend | API REST: movimientos de inventario y alertas | 16 |
| 6 | Backend | API REST: métricas para dashboard | 12 |
| 7 | Backend | Exportación CSV/Excel | 8 |
| 8 | Auth | JWT: login, refresh, roles y permisos | 16 |
| 9 | Frontend | Setup React + routing + estado global | 10 |
| 10 | Frontend | Módulo de productos (listado, formularios) | 24 |
| 11 | Frontend | Módulo de inventario y alertas | 20 |
| 12 | Frontend | Dashboard y gráficas | 16 |
| 13 | Frontend | Páginas de autenticación y sesión | 10 |
| 14 | Testing | Pruebas unitarias backend (≥70% cobertura) | 20 |
| 15 | Testing | Pruebas de integración API | 12 |
| 16 | DevOps | Dockerización y configuración AWS ECS | 16 |
| 17 | DevOps | Pipeline CI/CD (GitHub Actions) | 12 |
| 18 | DevOps | Configuración RDS, variables de entorno, secretos | 8 |
| 19 | PM | Gestión de proyecto, demos, documentación técnica | 20 |

### Resumen

- **Total estimado:** 292 horas
- **Rango recomendado:** 280–340 horas (buffer de riesgo ~15%)
- **Equipo recomendado:** 1 Tech Lead / Full-stack Sr, 1 Frontend Mid, 1 Backend Mid
- **Duración aproximada:** 3–3.5 meses (equipo de 3, ~40 h/semana)

### Riesgos e incertidumbres
- Migración de datos desde Excel puede requerir trabajo adicional no estimado.
- Definición de roles podría expandirse si hay más de 3 perfiles.
- Integración con ERP o facturación fue mencionada informalmente; no está en el alcance.

### Preguntas abiertas
- ¿Se requiere aplicación móvil o solo web responsivo?
- ¿Las alertas de stock son en pantalla o también por email/SMS?
- ¿Qué datos históricos deben migrarse desde las hojas de cálculo?
""",
    },
    {
        "meeting_summary": (
            "La clínica Salud Total quiere digitalizar su proceso de reservas médicas. "
            "Actualmente las citas se gestionan por teléfono. Necesitan: portal web "
            "para pacientes (registro, selección de especialidad, médico y horario), "
            "panel de administración para médicos y recepcionistas, recordatorios "
            "automáticos por email y WhatsApp, historial de citas por paciente, "
            "cancelación y reprogramación, y un módulo básico de pago en línea "
            "(integración con Wompi). Stack: Vue.js + Django + MySQL. "
            "El cliente no tiene equipo técnico interno. Plazo: 4 meses."
        ),
        "estimation": """\
## Estimación: Sistema de Reservas Médicas — Clínica Salud Total

### Supuestos
- Módulo de pago cubre solo Wompi (tarjetas); pagos en efectivo fuera de alcance.
- Recordatorios WhatsApp vía API oficial de WhatsApp Business (Meta); aprobación del número es responsabilidad del cliente.
- Historial de citas es solo lectura; sin expediente clínico.
- Autenticación separada para pacientes (email/contraseña) y personal interno.
- Sin integración con sistemas de historia clínica existentes.
- Infraestructura: VPS o instancia EC2 básica; sin orquestación de contenedores.
- El equipo dev entrega QA completo (cliente sin equipo técnico).

### Requisitos identificados
- Portal web para pacientes: registro, login, selección de cita
- Catálogo de especialidades, médicos y disponibilidad horaria
- Creación, cancelación y reprogramación de citas
- Historial de citas por paciente
- Recordatorios automáticos por email y WhatsApp
- Pago en línea con Wompi
- Panel de administración para médicos y recepcionistas

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | Diseño | UX: flujos paciente y admin (8 pantallas) | 28 |
| 2 | Diseño | Prototipo, revisiones y aprobación | 16 |
| 3 | Backend | Modelos de datos (Django ORM, MySQL) | 14 |
| 4 | Backend | API: registro y autenticación de pacientes | 14 |
| 5 | Backend | API: catálogo de especialidades, médicos y disponibilidad | 18 |
| 6 | Backend | API: creación, cancelación y reprogramación de citas | 20 |
| 7 | Backend | API: historial de citas por paciente | 8 |
| 8 | Backend | Integración Wompi (pagos, webhooks, reconciliación) | 24 |
| 9 | Backend | Notificaciones: email (SendGrid) | 10 |
| 10 | Backend | Notificaciones: WhatsApp Business API | 16 |
| 11 | Backend | Panel admin Django + permisos por rol | 16 |
| 12 | Frontend | Setup Vue.js + Vue Router + Pinia | 8 |
| 13 | Frontend | Portal paciente: registro y login | 12 |
| 14 | Frontend | Portal paciente: búsqueda y reserva de citas | 24 |
| 15 | Frontend | Portal paciente: mis citas e historial | 12 |
| 16 | Frontend | Panel recepcionista: agenda y gestión de citas | 20 |
| 17 | Testing | Pruebas unitarias e integración backend | 24 |
| 18 | Testing | Pruebas end-to-end (flujo de reserva y pago) | 16 |
| 19 | DevOps | Dockerización, servidor, SSL, backups | 14 |
| 20 | DevOps | Variables de entorno, secretos, monitoreo básico | 8 |
| 21 | PM | Gestión, demos, manuales de usuario y documentación | 24 |

### Resumen

- **Total estimado:** 346 horas
- **Rango recomendado:** 330–400 horas (buffer ~15%; WhatsApp y Wompi tienen riesgo de demoras externas)
- **Equipo recomendado:** 1 Tech Lead / Backend Sr, 1 Frontend Mid, 1 QA / Dev Jr
- **Duración aproximada:** 3.5–4 meses

### Riesgos e incertidumbres
- Aprobación de cuenta WhatsApp Business (Meta) puede tardar 2–4 semanas; bloquea el módulo de recordatorios.
- Wompi puede requerir documentación empresarial para activar pagos en producción.
- Gestión de disponibilidad en tiempo real puede ser más compleja según reglas de negocio que surjan.

### Preguntas abiertas
- ¿Los médicos gestionan su propia agenda o solo lo hace recepción?
- ¿Hay un sistema de historia clínica con el que eventualmente deba integrarse?
- ¿Se necesita soporte multiidioma?
""",
    },
]
