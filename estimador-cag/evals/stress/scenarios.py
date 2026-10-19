"""Escenarios multi-turno del stress test y fact-tracker.

Cada escenario son 20 turnos `(turn_index, transcript, fact_to_remember)`. Los N = 1, 3, 6, 10 y 20 son
*checkpoints*: `Scenario.prefix(n)` devuelve los primeros n turnos, de modo que una sola sesión de 20 turnos
produce los puntos de todos los N sin repetir llamadas al LLM.

Los hechos son tokens distintivos (nombres propios, cifras) para que la coincidencia exacta de
`MemoryDriftMetric` no dependa de paráfrasis; `a|b` admite alternativas de formato. Todo es determinista.

- `growing`: añade requisitos coherentes; ¿sobrevive el nombre original (Atlas) hasta el turno 20?
- `pivot`: el turno 5 cambia el stack (Django -> NestJS); ¿los metadatos sustituyen o acumulan tecnologías?
- `contradiction`: presupuesto de 30.000 EUR en el turno 3 y de 80.000 EUR en el turno 8; ¿qué conservan
  metadatos, anclas y resumen?
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from evals.metrics import MetricResult
from evals.stress.metrics import MemoryDriftMetric, Snapshot

ALLOWED_N = (1, 3, 6, 10, 20)
TOTAL_TURNS = max(ALLOWED_N)
PROFILES = ("growing", "pivot", "contradiction")
PROJECT_TYPE = "web_saas"


class Turn(NamedTuple):
    turn_index: int
    transcript: str
    fact_to_remember: str | None


@dataclass(frozen=True)
class Fact:
    text: str
    introduced_at: int
    superseded_at: int | None = None

    def active_at(self, turn_index: int) -> bool:
        return self.superseded_at is None or turn_index < self.superseded_at


@dataclass(frozen=True)
class Scenario:
    profile: str
    turns: tuple[Turn, ...]
    # hecho -> turno en que otro lo sustituye (cambio de stack, presupuesto reemplazado)
    superseded: dict[str, int] = field(default_factory=dict)

    def prefix(self, n: int) -> tuple[Turn, ...]:
        if n not in ALLOWED_N:
            raise ValueError(f"N debe ser uno de {ALLOWED_N}, no {n}")
        return self.turns[:n]

    def facts(self) -> tuple[Fact, ...]:
        return tuple(
            Fact(t.fact_to_remember, t.turn_index, self.superseded.get(t.fact_to_remember))
            for t in self.turns
            if t.fact_to_remember
        )


def _turns(lines: Sequence[tuple[str, str | None]]) -> tuple[Turn, ...]:
    if len(lines) != TOTAL_TURNS:
        raise ValueError(f"un escenario tiene {TOTAL_TURNS} turnos, no {len(lines)}")
    return tuple(Turn(i, text, fact) for i, (text, fact) in enumerate(lines, start=1))


def growing() -> Scenario:
    return Scenario(
        "growing",
        _turns(
            [
                (
                    "Queremos construir el proyecto Atlas: un portal de gestión de pedidos para una distribuidora.",
                    "Atlas",
                ),
                ("Añade facturación electrónica con cobros mediante Stripe.", "Stripe"),
                ("Necesitamos autenticación corporativa con Keycloak y single sign-on.", "Keycloak"),
                ("Incluye un panel de analítica con Metabase para la dirección.", "Metabase"),
                ("Debe haber notificaciones a los clientes por WhatsApp Business.", "WhatsApp"),
                ("Soporte multi-idioma: español, inglés y portugués.", "portugués"),
                ("Hay que sincronizar el inventario con el ERP Zafiro cada 15 minutos.", "Zafiro"),
                ("Exportación de informes a Excel para el departamento de contabilidad.", "Excel"),
                ("Módulo de devoluciones con etiquetas de transporte de Correos Express.", "Correos Express"),
                ("Roles diferenciados para comerciales, personal de almacén y administradores.", "almacén"),
                ("La búsqueda de productos se hará con Elasticsearch.", "Elasticsearch"),
                ("App móvil de reparto para los conductores, desarrollada en Flutter.", "Flutter"),
                ("Firma electrónica de albaranes mediante DocuSign.", "DocuSign"),
                ("Cumplimiento del RGPD y registro de auditoría de accesos.", "RGPD"),
                ("Procesos pesados en segundo plano con colas RabbitMQ.", "RabbitMQ"),
                ("Pruebas automatizadas de extremo a extremo con Cypress.", "Cypress"),
                ("Despliegue en Kubernetes sobre Azure.", "Azure"),
                ("Hay que migrar 50.000 clientes desde hojas de cálculo antiguas.", "50.000"),
                ("Formación presencial de dos días para los equipos de ventas.", "Formación"),
                ("Con todo lo anterior, ajusta la estimación final del proyecto completo.", None),
            ]
        ),
    )


def pivot() -> Scenario:
    return Scenario(
        "pivot",
        _turns(
            [
                (
                    "Proyecto Helios: reservas para clínicas dentales, stack inicial Django, PostgreSQL y React.",
                    "Helios",
                ),
                ("El backend en Django expondrá una API REST para las reservas.", "Django"),
                ("Integración con el software de gestión clínica Gesden.", "Gesden"),
                ("Los pacientes recibirán recordatorios de la cita por SMS.", "SMS"),
                ("Cambio de stack: abandonamos Django y React; usaremos Node.js con NestJS, MongoDB y Vue.", "NestJS"),
                ("La autenticación de pacientes y personal será con Auth0.", "Auth0"),
                ("Pagos de los tratamientos con Redsys.", "Redsys"),
                ("Tareas programadas y recordatorios con colas BullMQ.", "BullMQ"),
                ("Pruebas de extremo a extremo con Playwright.", "Playwright"),
                ("Monitorización de la plataforma con Grafana.", "Grafana"),
                ("Chat de soporte para pacientes con Intercom.", "Intercom"),
                ("Cumplimiento de la normativa de datos de salud LOPDGDD.", "LOPDGDD"),
                ("Las radiografías se almacenarán en Amazon S3 cifrado.", "S3"),
                ("Videoconsulta integrada mediante Twilio.", "Twilio"),
                ("Facturación a pacientes con Holded.", "Holded"),
                ("Informes de gestión para la gerencia con Power BI.", "Power BI"),
                ("Alojamiento en AWS región Madrid.", "AWS"),
                ("Integración y despliegue continuos con GitHub Actions.", "GitHub Actions"),
                ("La aplicación móvil de pacientes funcionará sin conexión usando Ionic.", "Ionic"),
                ("Resume el alcance y confirma el stack tecnológico final del proyecto.", None),
            ]
        ),
        superseded={"Django": 5},
    )


def contradiction() -> Scenario:
    return Scenario(
        "contradiction",
        _turns(
            [
                ("Proyecto Orion: sistema de gestión de flotas para una empresa de transporte.", "Orion"),
                ("Necesitamos seguimiento GPS en tiempo real con mapas de Mapbox.", "Mapbox"),
                ("El presupuesto máximo acordado es de 30.000 EUR y no podemos superarlo.", "30.000|30000|30 000"),
                ("Alertas de mantenimiento preventivo según el kilometraje.", "kilometraje"),
                ("Integración con las tarjetas de combustible de Solred.", "Solred"),
                ("Panel de conductores con registro de tacógrafo digital.", "tacógrafo"),
                ("Informes de consumo con Looker Studio.", "Looker"),
                (
                    "La dirección ha aprobado un nuevo presupuesto de 80.000 EUR que sustituye al anterior.",
                    "80.000|80000|80 000",
                ),
                ("Añade un módulo de planificación de rutas con OptaPlanner.", "OptaPlanner"),
                ("Notificaciones a clientes por Telegram.", "Telegram"),
                ("Gestión de incidencias de vehículos con Jira Service Management.", "Jira"),
                ("Aplicación móvil para conductores en Kotlin.", "Kotlin"),
                ("Almacén de datos en ClickHouse para el histórico GPS.", "ClickHouse"),
                ("Autenticación con Okta.", "Okta"),
                ("Cumplimiento de la normativa europea de tiempos de conducción.", "tiempos de conducción"),
                ("Despliegue en Google Cloud con Terraform.", "Terraform"),
                ("Integración con el sistema de facturación SAP.", "SAP"),
                ("Pruebas de carga con k6 simulando 5.000 vehículos.", "k6"),
                ("Documentación técnica y manual de usuario en Confluence.", "Confluence"),
                ("Con todo lo anterior, ajusta la estimación final del proyecto completo.", None),
            ]
        ),
        superseded={"30.000|30000|30 000": 8},
    )


_BUILDERS = {"growing": growing, "pivot": pivot, "contradiction": contradiction}


def build_scenario(profile: str) -> Scenario:
    if profile not in _BUILDERS:
        raise ValueError(f"perfil desconocido {profile!r}; usa uno de {PROFILES}")
    return _BUILDERS[profile]()


@dataclass(frozen=True)
class FactCheck:
    fact: Fact
    result: MetricResult

    @property
    def retained(self) -> bool:
        return self.result.passed

    @property
    def active(self) -> bool:
        return self.fact.active_at(self.result.details["snapshot_turn"])  # type: ignore[arg-type]

    @property
    def stale_present(self) -> bool:
        """Hecho ya sustituido que sigue en la memoria (acumula en vez de reemplazar)."""
        return self.retained and not self.active


class FactTracker:
    """Evalúa, contra el snapshot de un turno, los hechos introducidos en turnos anteriores."""

    def __init__(self, scenario: Scenario, metric: MemoryDriftMetric | None = None):
        self.scenario = scenario
        self.metric = metric or MemoryDriftMetric()
        self._facts = scenario.facts()

    def facts_before(self, turn_index: int) -> list[Fact]:
        return [f for f in self._facts if f.introduced_at < turn_index]

    def evaluate(self, snapshot: Snapshot) -> list[FactCheck]:
        return [
            FactCheck(fact, self.metric.evaluate(fact.text, fact.introduced_at, snapshot))
            for fact in self.facts_before(snapshot.turn_index)
        ]

    @staticmethod
    def recall(checks: Sequence[FactCheck]) -> float | None:
        """Fracción de hechos vigentes que la memoria conserva; None si aún no hay ninguno que evaluar."""
        active = [c for c in checks if c.active]
        return sum(c.retained for c in active) / len(active) if active else None
