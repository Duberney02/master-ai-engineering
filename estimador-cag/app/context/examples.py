"""Ejemplos históricos para el contexto CAG (Context-Augmented Generation).

Cada ejemplo se define **una sola vez** como datos estructurados
(`EstimationExample`) y de ahí se derivan las tres representaciones que puede
inyectarse en el prompt: Markdown (idéntico al formato de salida que exige el
prompt), JSON y narrativa. Así los totales y los desgloses no pueden divergir
entre formatos: el total de horas es siempre la suma de las tareas, y el rango
recomendado se valida al importar el módulo.
"""

import json
from dataclasses import dataclass
from typing import Literal

ExampleFormat = Literal["markdown", "json", "narrative"]


@dataclass(frozen=True)
class EstimationExample:
    """Una estimación histórica estructurada."""

    title: str
    meeting_summary: str
    supuestos: tuple[str, ...]
    requisitos: tuple[str, ...]
    tareas: tuple[tuple[str, str, int], ...]  # (área, tarea, horas)
    rango: tuple[int, int]  # (mínimo, máximo) de horas recomendadas
    equipo: str
    duracion: str
    riesgos: tuple[str, ...]
    preguntas: tuple[str, ...]
    rango_nota: str = ""

    def __post_init__(self) -> None:
        if not self.tareas:
            raise ValueError(f"{self.title}: el desglose no puede estar vacío")
        if any(horas <= 0 for _, _, horas in self.tareas):
            raise ValueError(f"{self.title}: todas las tareas deben tener horas > 0")
        low, high = self.rango
        if not low <= self.total_hours <= high:
            raise ValueError(
                f"{self.title}: el total ({self.total_hours} h) queda fuera del rango recomendado ({low}–{high} h)"
            )

    @property
    def total_hours(self) -> int:
        """Total de horas: siempre la suma del desglose (fuente única de verdad)."""
        return sum(horas for _, _, horas in self.tareas)

    @property
    def estimation_markdown(self) -> str:
        """Estimación en el mismo formato Markdown que exige el prompt."""
        bullets = lambda items: "\n".join(f"- {item}" for item in items)  # noqa: E731
        rows = "\n".join(
            f"| {i} | {area} | {tarea} | {horas} |" for i, (area, tarea, horas) in enumerate(self.tareas, start=1)
        )
        nota = f" ({self.rango_nota})" if self.rango_nota else ""
        return (
            f"## Estimación: {self.title}\n\n"
            f"### Supuestos\n{bullets(self.supuestos)}\n\n"
            f"### Requisitos identificados\n{bullets(self.requisitos)}\n\n"
            "### Desglose de tareas\n\n"
            "| # | Área | Tarea | Horas |\n"
            "|---|------|-------|------:|\n"
            f"{rows}\n\n"
            "### Resumen\n\n"
            f"- **Total estimado:** {self.total_hours} horas\n"
            f"- **Rango recomendado:** {self.rango[0]}–{self.rango[1]} horas{nota}\n"
            f"- **Equipo recomendado:** {self.equipo}\n"
            f"- **Duración aproximada:** {self.duracion}\n\n"
            f"### Riesgos e incertidumbres\n{bullets(self.riesgos)}\n\n"
            f"### Preguntas abiertas\n{bullets(self.preguntas)}\n"
        )

    def as_dict(self) -> dict:
        return {
            "proyecto": self.title,
            "resumen_reunion": self.meeting_summary,
            "supuestos": list(self.supuestos),
            "requisitos_identificados": list(self.requisitos),
            "desglose_de_tareas": [
                {"n": i, "area": area, "tarea": tarea, "horas": horas}
                for i, (area, tarea, horas) in enumerate(self.tareas, start=1)
            ],
            "resumen": {
                "total_horas": self.total_hours,
                "rango_recomendado_horas": {"min": self.rango[0], "max": self.rango[1]},
                "equipo_recomendado": self.equipo,
                "duracion_aproximada": self.duracion,
            },
            "riesgos_e_incertidumbres": list(self.riesgos),
            "preguntas_abiertas": list(self.preguntas),
        }


def _example(data: dict) -> EstimationExample:
    return EstimationExample(
        title=data["title"],
        meeting_summary=data["meeting_summary"],
        supuestos=tuple(data["supuestos"]),
        requisitos=tuple(data["requisitos"]),
        tareas=tuple(tuple(t) for t in data["tareas"]),
        rango=tuple(data["rango"]),
        equipo=data["equipo"],
        duracion=data["duracion"],
        riesgos=tuple(data["riesgos"]),
        preguntas=tuple(data["preguntas"]),
        rango_nota=data.get("rango_nota", ""),
    )


# Orden deliberado: cualquier prefijo del catálogo mezcla tamaños y dominios
# (medio, medio, IA, pequeño, grande), de modo que `num_examples` siempre
# entrega variedad además de cantidad.
_RAW_EXAMPLES: list[dict] = [
    {
        "title": "Plataforma de Gestión de Inventario — Comercial Andina",
        "meeting_summary": "El cliente Comercial Andina necesita una plataforma web para gestionar su "
        "inventario de más de 5 000 SKUs. Actualmente usan hojas de cálculo. "
        "Requieren: registro y edición de productos, control de stock con alertas de "
        "mínimo, historial de movimientos, dashboard con métricas clave (rotación, "
        "valorización), autenticación por roles (admin, bodeguero, gerente), "
        "exportación a Excel y despliegue en AWS. Stack preferido: React + FastAPI + "
        "PostgreSQL. Tienen equipo de QA interno. El plazo deseado es 3 meses.",
        "supuestos": [
            "Diseño UI/UX incluye 2 rondas de revisión; cambios mayores fuera de alcance.",
            "Autenticación vía JWT; sin SSO ni LDAP.",
            "Base de datos PostgreSQL en RDS; sin alta disponibilidad multi-región.",
            "Exportaciones CSV/Excel generadas en el servidor; sin reportes BI complejos.",
            "El equipo de QA del cliente ejecuta pruebas de aceptación; el equipo dev entrega "
            "pruebas unitarias e integración.",
            "CI/CD básico con GitHub Actions hacia staging y producción en AWS ECS.",
        ],
        "requisitos": [
            "CRUD de productos y categorías",
            "Control de stock con alertas de mínimo",
            "Historial de movimientos de inventario",
            "Dashboard con métricas (rotación, valorización)",
            "Autenticación con roles (admin, bodeguero, gerente)",
            "Exportación a Excel/CSV",
            "Despliegue en AWS",
        ],
        "tareas": [
            ["Diseño", "Wireframes y flujos UX (5 pantallas principales)", 24],
            ["Diseño", "Prototipo interactivo y revisiones", 16],
            ["Backend", "Modelado de base de datos y migraciones", 12],
            ["Backend", "API REST: productos y categorías (CRUD)", 20],
            ["Backend", "API REST: movimientos de inventario y alertas", 16],
            ["Backend", "API REST: métricas para dashboard", 12],
            ["Backend", "Exportación CSV/Excel", 8],
            ["Auth", "JWT: login, refresh, roles y permisos", 16],
            ["Frontend", "Setup React + routing + estado global", 10],
            ["Frontend", "Módulo de productos (listado, formularios)", 24],
            ["Frontend", "Módulo de inventario y alertas", 20],
            ["Frontend", "Dashboard y gráficas", 16],
            ["Frontend", "Páginas de autenticación y sesión", 10],
            ["Testing", "Pruebas unitarias backend (≥70% cobertura)", 20],
            ["Testing", "Pruebas de integración API", 12],
            ["DevOps", "Dockerización y configuración AWS ECS", 16],
            ["DevOps", "Pipeline CI/CD (GitHub Actions)", 12],
            ["DevOps", "Configuración RDS, variables de entorno, secretos", 8],
            ["PM", "Gestión de proyecto, demos, documentación técnica", 20],
        ],
        "rango": [280, 340],
        "rango_nota": "buffer de riesgo ~15%",
        "equipo": "1 Tech Lead / Full-stack Sr, 1 Frontend Mid, 1 Backend Mid",
        "duracion": "3–3.5 meses (equipo de 3, ~40 h/semana)",
        "riesgos": [
            "Migración de datos desde Excel puede requerir trabajo adicional no estimado.",
            "Definición de roles podría expandirse si hay más de 3 perfiles.",
            "Integración con ERP o facturación fue mencionada informalmente; no está en el alcance.",
        ],
        "preguntas": [
            "¿Se requiere aplicación móvil o solo web responsivo?",
            "¿Las alertas de stock son en pantalla o también por email/SMS?",
            "¿Qué datos históricos deben migrarse desde las hojas de cálculo?",
        ],
    },
    {
        "title": "Sistema de Reservas Médicas — Clínica Salud Total",
        "meeting_summary": "La clínica Salud Total quiere digitalizar su proceso de reservas médicas. "
        "Actualmente las citas se gestionan por teléfono. Necesitan: portal web para "
        "pacientes (registro, selección de especialidad, médico y horario), panel de "
        "administración para médicos y recepcionistas, recordatorios automáticos por "
        "email y WhatsApp, historial de citas por paciente, cancelación y "
        "reprogramación, y un módulo básico de pago en línea (integración con Wompi). "
        "Stack: Vue.js + Django + MySQL. El cliente no tiene equipo técnico interno. "
        "Plazo: 4 meses.",
        "supuestos": [
            "Módulo de pago cubre solo Wompi (tarjetas); pagos en efectivo fuera de alcance.",
            "Recordatorios WhatsApp vía API oficial de WhatsApp Business (Meta); aprobación "
            "del número es responsabilidad del cliente.",
            "Historial de citas es solo lectura; sin expediente clínico.",
            "Autenticación separada para pacientes (email/contraseña) y personal interno.",
            "Sin integración con sistemas de historia clínica existentes.",
            "Infraestructura: VPS o instancia EC2 básica; sin orquestación de contenedores.",
            "El equipo dev entrega QA completo (cliente sin equipo técnico).",
        ],
        "requisitos": [
            "Portal web para pacientes: registro, login, selección de cita",
            "Catálogo de especialidades, médicos y disponibilidad horaria",
            "Creación, cancelación y reprogramación de citas",
            "Historial de citas por paciente",
            "Recordatorios automáticos por email y WhatsApp",
            "Pago en línea con Wompi",
            "Panel de administración para médicos y recepcionistas",
        ],
        "tareas": [
            ["Diseño", "UX: flujos paciente y admin (8 pantallas)", 28],
            ["Diseño", "Prototipo, revisiones y aprobación", 16],
            ["Backend", "Modelos de datos (Django ORM, MySQL)", 14],
            ["Backend", "API: registro y autenticación de pacientes", 14],
            ["Backend", "API: catálogo de especialidades, médicos y disponibilidad", 18],
            ["Backend", "API: creación, cancelación y reprogramación de citas", 20],
            ["Backend", "API: historial de citas por paciente", 8],
            ["Backend", "Integración Wompi (pagos, webhooks, reconciliación)", 24],
            ["Backend", "Notificaciones: email (SendGrid)", 10],
            ["Backend", "Notificaciones: WhatsApp Business API", 16],
            ["Backend", "Panel admin Django + permisos por rol", 16],
            ["Frontend", "Setup Vue.js + Vue Router + Pinia", 8],
            ["Frontend", "Portal paciente: registro y login", 12],
            ["Frontend", "Portal paciente: búsqueda y reserva de citas", 24],
            ["Frontend", "Portal paciente: mis citas e historial", 12],
            ["Frontend", "Panel recepcionista: agenda y gestión de citas", 20],
            ["Testing", "Pruebas unitarias e integración backend", 24],
            ["Testing", "Pruebas end-to-end (flujo de reserva y pago)", 16],
            ["DevOps", "Dockerización, servidor, SSL, backups", 14],
            ["DevOps", "Variables de entorno, secretos, monitoreo básico", 8],
            ["PM", "Gestión, demos, manuales de usuario y documentación", 24],
        ],
        "rango": [330, 400],
        "rango_nota": "buffer ~15%; WhatsApp y Wompi tienen riesgo de demoras externas",
        "equipo": "1 Tech Lead / Backend Sr, 1 Frontend Mid, 1 QA / Dev Jr",
        "duracion": "3.5–4 meses",
        "riesgos": [
            "Aprobación de cuenta WhatsApp Business (Meta) puede tardar 2–4 semanas; bloquea el "
            "módulo de recordatorios.",
            "Wompi puede requerir documentación empresarial para activar pagos en producción.",
            "Gestión de disponibilidad en tiempo real puede ser más compleja según reglas de negocio que surjan.",
        ],
        "preguntas": [
            "¿Los médicos gestionan su propia agenda o solo lo hace recepción?",
            "¿Hay un sistema de historia clínica con el que eventualmente deba integrarse?",
            "¿Se necesita soporte multiidioma?",
        ],
    },
    {
        "title": "Asistente Virtual de Atención al Cliente con IA — Andes Seguros",
        "meeting_summary": "La aseguradora Andes Seguros quiere un asistente virtual para atención al "
        "cliente por web y WhatsApp que responda preguntas sobre pólizas, coberturas "
        "y siniestros a partir de su base de conocimiento (unos 300 documentos PDF y "
        "una intranet). Debe citar la fuente de cada respuesta, escalar a un agente "
        "humano cuando la confianza sea baja, guardar el historial de conversaciones "
        "y ofrecer un panel a supervisores con métricas (resolución sin humano, "
        "satisfacción). Deben proteger los datos personales conforme a la Ley 1581. "
        "Stack: Python + FastAPI y PostgreSQL; el proveedor de LLM está por definir. "
        "Plazo: 3 meses.",
        "supuestos": [
            "El LLM se consume por API de un proveedor externo; no se entrena ni se aloja un modelo propio.",
            "Recuperación con embeddings sobre PostgreSQL (pgvector); sin infraestructura vectorial dedicada.",
            "Los PDF contienen texto seleccionable; el OCR de documentos escaneados no está incluido.",
            "Los datos personales se enmascaran antes de enviarse al proveedor de LLM.",
            "El cliente aporta y valida un conjunto de 100 preguntas reales para la evaluación.",
            "El número de WhatsApp Business ya está aprobado por Meta al iniciar la integración.",
            "Solo idioma español y canal de texto (sin voz).",
        ],
        "requisitos": [
            "Asistente conversacional web (widget embebible) y por WhatsApp",
            "Respuestas basadas en la base de conocimiento, con cita de la fuente",
            "Escalamiento a agente humano cuando la confianza es baja",
            "Registro histórico de conversaciones",
            "Panel de supervisores con métricas de resolución y satisfacción",
            "Protección de datos personales (Ley 1581)",
        ],
        "tareas": [
            ["Descubrimiento", "Análisis de la base de conocimiento y definición de casos de uso", 16],
            ["Datos", "Ingesta, limpieza y segmentación de ~300 PDF", 24],
            ["Datos", "Embeddings e índice vectorial (pgvector)", 16],
            ["Backend", "Pipeline RAG: recuperación, prompt y citas de fuente", 32],
            ["Backend", "Política de escalamiento y umbral de confianza", 16],
            ["Backend", "API de conversaciones y persistencia", 20],
            ["Backend", "Enmascaramiento de datos personales (PII)", 12],
            ["Integración", "Canal de WhatsApp Business API", 24],
            ["Frontend", "Widget de chat web embebible", 20],
            ["Frontend", "Panel de supervisores y métricas", 24],
            ["Evaluación", "Dataset de evaluación y métricas de calidad (100 preguntas)", 20],
            ["Evaluación", "Ajuste de prompts y umbrales tras la evaluación", 16],
            ["Testing", "Pruebas unitarias e integración", 20],
            ["DevOps", "Contenedores, CI/CD y observabilidad (trazas y consumo de tokens)", 20],
            ["PM", "Gestión de proyecto, demos y documentación", 16],
        ],
        "rango": [290, 370],
        "rango_nota": "buffer ~25% por calidad de datos y comportamiento del LLM",
        "equipo": "1 Ingeniero ML/Backend Sr, 1 Backend Mid, 1 Frontend Mid (part-time)",
        "duracion": "3 meses (~12 semanas)",
        "riesgos": [
            "Documentos desactualizados o contradictorios degradan la calidad de las respuestas.",
            "Riesgo de respuestas incorrectas (alucinaciones) en temas sensibles como "
            "coberturas; requiere umbrales y revisión humana.",
            "Costo y latencia del proveedor de LLM pueden exceder lo esperado con alto volumen.",
            "La aprobación de WhatsApp Business puede demorar 2–4 semanas.",
        ],
        "preguntas": [
            "¿Los PDF son texto o escaneados? ¿Hay que incluir OCR?",
            "¿Quién mantendrá actualizada la base de conocimiento?",
            "¿Existe una restricción de proveedor de LLM o de residencia de datos?",
            "¿Se necesitan consultas personalizadas (estado de una póliza) que requieran "
            "integrarse con el core de seguros?",
        ],
    },
    {
        "title": "Sitio Web Corporativo con CMS — Estudio Trazo",
        "meeting_summary": "El estudio de arquitectura Trazo quiere renovar su sitio web corporativo: "
        "seis secciones (inicio, servicios, portafolio con filtros por tipo de "
        "proyecto, nosotros, blog y contacto). El diseño ya está aprobado en Figma. "
        "El formulario de contacto debe enviar los leads a HubSpot, y necesitan SEO "
        "básico y analítica con GA4. Quieren un CMS headless para publicar proyectos "
        "y artículos sin depender de desarrollo. Despliegue en Vercel. Plazo: 6 "
        "semanas.",
        "supuestos": [
            "El diseño de Figma es definitivo; los cambios de diseño posteriores están fuera de alcance.",
            "El cliente entrega textos e imágenes; el equipo carga como máximo 20 entradas iniciales.",
            "CMS headless SaaS (por ejemplo Strapi Cloud o Contentful); sin autoalojamiento.",
            "Solo español; sin versión multiidioma.",
            "Cuenta de HubSpot existente con acceso por API.",
        ],
        "requisitos": [
            "Sitio con seis secciones basado en el diseño de Figma",
            "Portafolio con filtros por tipo de proyecto",
            "Blog administrable desde un CMS",
            "Formulario de contacto integrado con HubSpot",
            "SEO básico y analítica GA4",
            "Despliegue en Vercel",
        ],
        "tareas": [
            ["Diseño", "Revisión del Figma y sistema de componentes", 8],
            ["Frontend", "Configuración de Next.js, layout y navegación", 8],
            ["Frontend", "Páginas estáticas (inicio, servicios, nosotros)", 16],
            ["Frontend", "Portafolio con filtros y detalle de proyecto", 16],
            ["Frontend", "Blog (listado, detalle y paginación)", 12],
            ["CMS", "Modelado de contenido y configuración del CMS headless", 12],
            ["Integración", "Formulario de contacto con HubSpot", 8],
            ["SEO", "SEO técnico, metadatos, sitemap y GA4", 8],
            ["Testing", "Pruebas cross-browser, responsive y accesibilidad básica", 10],
            ["DevOps", "Despliegue en Vercel, dominio y SSL", 4],
            ["PM", "Gestión, revisiones con el cliente y capacitación del CMS", 10],
        ],
        "rango": [105, 130],
        "rango_nota": "buffer ~15% por rondas de revisión",
        "equipo": "1 Frontend Sr, 1 Diseñador UI (part-time, solo revisión)",
        "duracion": "5–6 semanas",
        "riesgos": [
            "Retrasos en la entrega de contenido del cliente desplazan el cierre del proyecto.",
            "Cambios de diseño tardíos elevan el esfuerzo de frontend.",
            "El plan de HubSpot del cliente podría limitar el uso de su API.",
        ],
        "preguntas": [
            "¿Se requiere una versión en inglés?",
            "¿Debe migrarse contenido del sitio actual?",
            "¿Quién administra el dominio y el DNS?",
        ],
    },
    {
        "title": "App Móvil de Fuerza de Ventas con Modo Offline — Agroandes",
        "meeting_summary": "La distribuidora Agroandes necesita una app móvil (Android e iOS) para 25 "
        "vendedores en campo: catálogo de unos 3 000 productos, toma de pedidos y "
        "registro de visitas con funcionamiento sin conexión y sincronización "
        "posterior, geolocalización de visitas, firma del cliente y consulta de "
        "cartera. Además, un panel web para supervisores (rutas, metas y reportes) y "
        "un backend propio. Debe integrarse con su SAP Business One para inventario, "
        "precios y cartera. Stack: React Native + NestJS + PostgreSQL. Plazo deseado: "
        "6 meses.",
        "supuestos": [
            "La integración con SAP Business One usa su Service Layer (API REST); el cliente "
            "provee ambiente de pruebas.",
            "La sincronización offline es por deltas con resolución de conflictos «gana el servidor» salvo pedidos.",
            "Publicación en App Store y Google Play con cuentas del cliente.",
            "Un solo país, moneda e idioma; sin multiempresa.",
            "El cliente facilita 5 vendedores para pruebas de campo.",
        ],
        "requisitos": [
            "App móvil Android/iOS con catálogo y búsqueda",
            "Toma de pedidos y registro de visitas sin conexión, con sincronización posterior",
            "Geolocalización de visitas y firma del cliente",
            "Consulta de cartera por cliente",
            "Panel web para supervisores (rutas, metas y reportes)",
            "Integración con SAP Business One",
        ],
        "tareas": [
            ["Diseño", "Investigación con vendedores, flujos y wireframes", 32],
            ["Diseño", "Sistema de diseño y prototipo móvil y web", 40],
            ["Arquitectura", "Diseño técnico de sincronización offline-first y conflictos", 24],
            ["Backend", "Modelo de datos y migraciones", 16],
            ["Backend", "API: catálogo, clientes y visitas", 36],
            ["Backend", "API: pedidos y flujo de aprobación", 28],
            ["Backend", "Motor de sincronización (deltas, cola y conflictos)", 48],
            ["Integración", "Conector SAP Business One (inventario, precios y cartera)", 56],
            ["Backend", "Autenticación, roles y gestión de dispositivos", 20],
            ["Móvil", "Configuración de React Native, navegación y almacenamiento local", 24],
            ["Móvil", "Catálogo y búsqueda sin conexión", 28],
            ["Móvil", "Toma de pedidos y carrito sin conexión", 40],
            ["Móvil", "Visitas, geolocalización y firma del cliente", 32],
            ["Móvil", "Consulta de cartera y sincronización en segundo plano", 24],
            ["Frontend", "Panel web de supervisores: rutas, metas y reportes", 44],
            ["Testing", "Pruebas unitarias e integración (backend y móvil)", 36],
            ["Testing", "Pruebas de campo y modo offline en dispositivos reales", 24],
            ["DevOps", "CI/CD, entornos y publicación en tiendas", 24],
            ["DevOps", "Monitoreo, logs y reporte de fallos móviles", 12],
            ["PM", "Gestión, demos, capacitación y documentación", 40],
        ],
        "rango": [600, 780],
        "rango_nota": "buffer ~25%: integración SAP y sincronización offline son los mayores focos de incertidumbre",
        "equipo": "1 Tech Lead / Backend Sr, 1 Móvil Sr, 1 Full-stack Mid, 1 QA (part-time), 1 Diseñador "
        "UX (primeras 6 semanas)",
        "duracion": "5–6 meses",
        "riesgos": [
            "La calidad y disponibilidad de la API de SAP puede exigir trabajo adicional no estimado.",
            "Los conflictos de sincronización offline solo se descubren completamente en pruebas de campo.",
            "Los tiempos de revisión de App Store pueden retrasar el lanzamiento.",
            "El plazo de 6 meses deja poco margen si el alcance crece.",
        ],
        "preguntas": [
            "¿Qué versión de SAP Business One usan y hay ambiente de pruebas?",
            "¿Cuántos pedidos por vendedor y día se esperan y qué antigüedad de datos es aceptable offline?",
            "¿Se requiere una versión de tableta o solo teléfono?",
            "¿Existen políticas de seguridad de dispositivos (MDM)?",
        ],
    },
]

ESTIMATION_EXAMPLES_CATALOG: list[EstimationExample] = [_example(d) for d in _RAW_EXAMPLES]
MAX_EXAMPLES = len(ESTIMATION_EXAMPLES_CATALOG)

# Vista de compatibilidad: lista de dicts con las claves históricas
# (`meeting_summary`, `estimation`) usadas por el resto de la aplicación.
ESTIMATION_EXAMPLES: list[dict[str, str]] = [
    {"meeting_summary": ex.meeting_summary, "estimation": ex.estimation_markdown} for ex in ESTIMATION_EXAMPLES_CATALOG
]


def select_examples(n: int) -> list[EstimationExample]:
    """Devuelve los primeros `n` ejemplos, acotado al tamaño del catálogo."""
    return ESTIMATION_EXAMPLES_CATALOG[: max(0, min(n, MAX_EXAMPLES))]


def format_examples(examples: list[EstimationExample], fmt: ExampleFormat = "markdown") -> str:
    """Representa los ejemplos en el formato pedido, listos para inyectar en el prompt."""
    if not examples:
        return ""
    if fmt == "markdown":
        return _format_markdown(examples)
    if fmt == "json":
        return _format_json(examples)
    if fmt == "narrative":
        return _format_narrative(examples)
    raise ValueError(f"Formato de ejemplos desconocido: {fmt}")


def _format_markdown(examples: list[EstimationExample]) -> str:
    parts = [
        f"### Historical Example {i}\n\n"
        f"**Meeting Summary:**\n{ex.meeting_summary}\n\n"
        f"**Generated Estimation:**\n{ex.estimation_markdown}\n"
        for i, ex in enumerate(examples, start=1)
    ]
    return "\n---\n\n".join(parts)


def _format_json(examples: list[EstimationExample]) -> str:
    payload = [ex.as_dict() for ex in examples]
    return "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```"


def _format_narrative(examples: list[EstimationExample]) -> str:
    parts: list[str] = []
    for i, ex in enumerate(examples, start=1):
        tareas = "; ".join(f"{tarea} ({horas} h)" for _, tarea, horas in ex.tareas)
        parts.append(
            f"Proyecto histórico {i}: {ex.title}. Solicitud del cliente: {ex.meeting_summary} "
            f"La estimación fue de {ex.total_hours} horas (rango recomendado "
            f"{ex.rango[0]}–{ex.rango[1]} horas), con el equipo {ex.equipo}, y una duración "
            f"aproximada de {ex.duracion}. Supuestos principales: {' '.join(ex.supuestos)} "
            f"Tareas principales: {tareas}. Riesgos: {' '.join(ex.riesgos)} "
            f"Preguntas abiertas: {' '.join(ex.preguntas)}"
        )
    return "\n\n".join(parts)
