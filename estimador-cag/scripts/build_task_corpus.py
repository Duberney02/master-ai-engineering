#!/usr/bin/env python3
"""Genera un corpus histórico con granularidad de TAREA y, opcionalmente, lo ingesta (Sesión 9).

El corpus de la Sesión 8 (`data/budgets_sample.json`) es grueso: un chunk por *componente* de presupuesto. La
estimación de la Sesión 9 se desglosa en módulos → tareas, así que para fundamentar tareas finas hace falta evidencia
histórica con esa misma granularidad.

El script sintetiza proyectos históricos realistas, cada uno descompuesto en MÓDULOS funcionales y, dentro de cada
módulo, TAREAS concretas con horas. Cada tarea es un `BudgetComponent` con su `module`, de modo que el chunker
estructural emite un chunk por tarea, con `chunk_type="historical_task"`. La generación es offline y DETERMINISTA
(con semilla): repetirla produce el mismo corpus y, como cada proyecto se ingesta con un `source_path` estable, la
ingesta es idempotente (`POST /embeddings/ingest` responde 409 a los ya ingestados y no se duplica nada).

Uso, con el stack raíz levantado (`docker compose up -d --build`)::

    # generar e ingestar (embeddings con la OPENAI_API_KEY del servicio); repetirlo no duplica
    docker compose exec estimador-cag python scripts/build_task_corpus.py --ingest

    # solo generar el JSON para revisarlo
    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/build_task_corpus.py --generate-only --out /tmp/task_corpus.json

Para retirar el corpus (es opcional y va etiquetado por `document_type`)::

    DELETE FROM documents WHERE document_type = 'historical_task_breakdown';
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

DOCUMENT_TYPE = "historical_task_breakdown"
CHUNK_TYPE = "historical_task"
SOURCE_PREFIX = "data/task_corpus.json#"
DEFAULT_API = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
DEFAULT_SEED = 90
DEFAULT_COUNT = 60
# Cada solicitud embebe las tareas de un proyecto: tarda unos segundos.
TIMEOUT_SECONDS = 120


# --- Plantillas de tareas ----------------------------------------------------------------------------------------
# Cada plantilla: (nombre, descripción, tecnologías posibles, (horas mín., horas máx.), complejidad). Módulos comunes
# a todos los sectores más bloques propios de cada sector. Una tarea es un `BudgetComponent` con su `module`. Los
# textos están en inglés, como el resto del corpus que se embebe.

Template = tuple[str, str, list[str], tuple[int, int], str]

COMMON_MODULES: dict[str, list[Template]] = {
    "Authentication & Access": [
        (
            "OAuth2 / OIDC login",
            "Authorization-code flow with refresh tokens and session handling.",
            ["python", "postgresql", "redis"],
            (24, 56),
            "high",
        ),
        (
            "Role-based access control",
            "Roles, permissions and policy checks across the API.",
            ["python", "postgresql"],
            (16, 40),
            "medium",
        ),
        (
            "SSO integration",
            "SAML/OIDC single sign-on against the client identity provider.",
            ["python", "saml"],
            (16, 32),
            "medium",
        ),
        (
            "Password & MFA flows",
            "Reset, lockout and TOTP-based multi-factor authentication.",
            ["python", "redis"],
            (12, 28),
            "medium",
        ),
    ],
    "Data & Integrations": [
        (
            "Third-party API integration",
            "Resilient client with retries, backoff and idempotency.",
            ["python", "httpx"],
            (16, 40),
            "medium",
        ),
        (
            "ETL / data sync job",
            "Scheduled extract-transform-load between systems.",
            ["python", "airflow", "postgresql"],
            (24, 56),
            "high",
        ),
        (
            "Webhook ingestion",
            "Signed-webhook receiver with replay protection.",
            ["python", "redis"],
            (12, 24),
            "low",
        ),
        (
            "Reporting data model",
            "Star-schema tables and aggregation views for analytics.",
            ["postgresql", "dbt"],
            (16, 40),
            "medium",
        ),
    ],
    "Frontend / UX": [
        (
            "Core SPA scaffolding",
            "App shell, routing, state management and design system.",
            ["typescript", "react"],
            (24, 48),
            "medium",
        ),
        (
            "Dashboard & charts",
            "Operational dashboard with filters and exportable charts.",
            ["typescript", "react", "d3"],
            (24, 56),
            "high",
        ),
        (
            "Form flows & validation",
            "Multi-step forms with client and server validation.",
            ["typescript", "react"],
            (12, 32),
            "medium",
        ),
        (
            "Accessibility & i18n",
            "WCAG pass and internationalisation of the UI.",
            ["typescript"],
            (12, 24),
            "low",
        ),
    ],
    "Infrastructure & DevOps": [
        (
            "CI/CD pipeline",
            "Build, test and deploy pipeline with environments.",
            ["docker", "github_actions"],
            (16, 36),
            "medium",
        ),
        (
            "IaC provisioning",
            "Infrastructure-as-code for the cloud footprint.",
            ["terraform", "aws"],
            (24, 48),
            "high",
        ),
        (
            "Observability stack",
            "Structured logs, metrics and alerting.",
            ["prometheus", "grafana"],
            (16, 32),
            "medium",
        ),
        (
            "Container orchestration",
            "Kubernetes manifests, autoscaling and rollout strategy.",
            ["kubernetes", "docker"],
            (24, 56),
            "high",
        ),
    ],
    "Security & Compliance": [
        (
            "Audit logging",
            "Tamper-evident audit trail of sensitive operations.",
            ["python", "postgresql"],
            (12, 28),
            "medium",
        ),
        (
            "Data encryption",
            "Encryption at rest and in transit, key rotation.",
            ["python", "kms"],
            (12, 32),
            "medium",
        ),
        (
            "Pentest remediation",
            "Fixing findings from a third-party security review.",
            ["python"],
            (16, 40),
            "high",
        ),
    ],
    "QA & Testing": [
        (
            "Automated test suite",
            "Unit and integration coverage for the core flows.",
            ["pytest"],
            (24, 56),
            "medium",
        ),
        (
            "End-to-end tests",
            "Browser-level E2E of the critical user journeys.",
            ["playwright"],
            (16, 36),
            "medium",
        ),
        (
            "Load & performance testing",
            "Throughput and latency benchmarks under load.",
            ["k6"],
            (12, 28),
            "medium",
        ),
    ],
    "Project Management": [
        (
            "Discovery & requirements",
            "Workshops, scope definition and acceptance criteria.",
            ["confluence"],
            (16, 40),
            "low",
        ),
        (
            "Coordination & reporting",
            "Sprint ceremonies, stakeholder reporting and risk tracking.",
            ["jira"],
            (24, 60),
            "low",
        ),
        (
            "UAT & handover",
            "User-acceptance test rounds, training and documentation handover.",
            ["confluence"],
            (16, 36),
            "low",
        ),
    ],
    "Analytics & Reporting": [
        (
            "Event tracking & instrumentation",
            "Product analytics events with a tracking plan.",
            ["segment", "typescript"],
            (16, 36),
            "medium",
        ),
        (
            "BI dashboards",
            "Self-service dashboards and scheduled report delivery.",
            ["metabase", "postgresql"],
            (24, 48),
            "medium",
        ),
        (
            "Data warehouse modelling",
            "Modelled marts and transformations for analytics.",
            ["dbt", "bigquery"],
            (24, 56),
            "high",
        ),
    ],
    "Notifications & Messaging": [
        (
            "Transactional email & SMS",
            "Templated multi-channel notifications with delivery tracking.",
            ["python", "sendgrid", "twilio"],
            (12, 28),
            "low",
        ),
        (
            "Push notifications",
            "Mobile/web push with topic subscriptions and opt-out.",
            ["python", "firebase"],
            (12, 28),
            "medium",
        ),
        (
            "In-app notification centre",
            "Real-time in-app inbox with read/unread state.",
            ["typescript", "websocket", "redis"],
            (16, 36),
            "medium",
        ),
    ],
    "Search & Discovery": [
        (
            "Full-text search service",
            "Indexing pipeline and query API with ranking.",
            ["elasticsearch", "python"],
            (24, 56),
            "high",
        ),
        (
            "Recommendations engine",
            "Collaborative/content-based recommendations.",
            ["python", "scikit_learn"],
            (24, 56),
            "high",
        ),
        (
            "Autocomplete & typeahead",
            "Low-latency suggestions with synonyms.",
            ["elasticsearch", "redis"],
            (12, 28),
            "medium",
        ),
    ],
    "Admin & Back-office": [
        (
            "Admin console",
            "CRUD back-office with auditing and bulk actions.",
            ["typescript", "react", "python"],
            (24, 48),
            "medium",
        ),
        (
            "Feature flags & config",
            "Runtime feature flags and remote configuration.",
            ["python", "redis"],
            (12, 28),
            "medium",
        ),
        (
            "Bulk import/export",
            "CSV/Excel import-export with validation and previews.",
            ["python", "pandas"],
            (12, 32),
            "medium",
        ),
    ],
    "Integrations Platform": [
        (
            "Public REST/GraphQL API",
            "Versioned public API with rate limiting and docs.",
            ["python", "fastapi"],
            (24, 56),
            "high",
        ),
        (
            "OAuth provider / API keys",
            "Issue and manage third-party API credentials.",
            ["python", "postgresql"],
            (16, 40),
            "high",
        ),
        (
            "Event streaming bus",
            "Internal event bus with schemas and dead-letter handling.",
            ["python", "kafka"],
            (24, 56),
            "high",
        ),
    ],
}

SECTOR_MODULES: dict[str, dict[str, list[Template]]] = {
    "finance": {
        "Payments & Billing": [
            (
                "Payment gateway integration",
                "Card payments via a PSP with 3-D Secure.",
                ["python", "stripe"],
                (24, 56),
                "high",
            ),
            (
                "Ledger & reconciliation",
                "Double-entry ledger and daily reconciliation.",
                ["python", "postgresql"],
                (32, 72),
                "high",
            ),
            (
                "Subscription billing",
                "Plans, proration and dunning for recurring billing.",
                ["python", "stripe"],
                (24, 48),
                "medium",
            ),
        ],
        "Regulatory Reporting": [
            (
                "KYC / AML onboarding",
                "Identity verification and sanction-list screening.",
                ["python", "onfido"],
                (32, 64),
                "high",
            ),
            (
                "Regulatory report export",
                "Scheduled regulator-format report generation.",
                ["python", "postgresql"],
                (16, 40),
                "medium",
            ),
        ],
    },
    "ecommerce": {
        "Catalog & Search": [
            (
                "Product catalog model",
                "Categories, variants and inventory tracking.",
                ["python", "postgresql"],
                (24, 48),
                "medium",
            ),
            (
                "Faceted search",
                "Search with filters, facets and relevance tuning.",
                ["elasticsearch"],
                (24, 56),
                "high",
            ),
        ],
        "Checkout & Cart": [
            (
                "Cart & checkout flow",
                "Cart, address, shipping and payment steps.",
                ["typescript", "react", "stripe"],
                (24, 56),
                "high",
            ),
            (
                "Promotions & coupons",
                "Discount rules, coupons and loyalty points.",
                ["python", "redis"],
                (16, 36),
                "medium",
            ),
            (
                "Order management",
                "Order lifecycle, fulfilment and returns.",
                ["python", "postgresql"],
                (24, 48),
                "medium",
            ),
        ],
    },
    "healthcare": {
        "Clinical Records": [
            (
                "Patient records (EHR)",
                "Encrypted patient records with access controls.",
                ["python", "postgresql"],
                (32, 72),
                "high",
            ),
            (
                "HL7 / FHIR integration",
                "Interoperability with hospital systems via FHIR.",
                ["python", "fhir"],
                (32, 64),
                "high",
            ),
        ],
        "Scheduling": [
            (
                "Appointment scheduling",
                "Calendars, availability and reminders.",
                ["python", "postgresql"],
                (24, 48),
                "medium",
            ),
            (
                "Telemedicine session",
                "Video consultation with waiting room.",
                ["typescript", "webrtc"],
                (24, 56),
                "high",
            ),
        ],
    },
    "industrial": {
        "Telemetry & IoT": [
            (
                "Device telemetry ingestion",
                "High-throughput sensor data ingestion.",
                ["python", "kafka"],
                (32, 64),
                "high",
            ),
            (
                "Time-series storage",
                "Downsampling and retention of time-series data.",
                ["timescaledb"],
                (16, 40),
                "medium",
            ),
        ],
        "Operations": [
            (
                "Production scheduling",
                "Job scheduling and shop-floor sequencing.",
                ["python", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Predictive maintenance",
                "Anomaly detection on equipment signals.",
                ["python", "scikit_learn"],
                (24, 48),
                "high",
            ),
        ],
    },
    "logistics": {
        "Fleet & Routing": [
            (
                "Route optimization engine",
                "Vehicle routing with time windows and constraints.",
                ["python", "or_tools"],
                (32, 72),
                "high",
            ),
            (
                "Live fleet tracking",
                "Real-time GPS tracking and ETA computation.",
                ["python", "kafka", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Driver mobile app integration",
                "Job dispatch and proof-of-delivery capture.",
                ["typescript", "react_native"],
                (24, 48),
                "medium",
            ),
        ],
        "Warehouse & Inventory": [
            (
                "Inventory & stock control",
                "Multi-warehouse stock levels and reservations.",
                ["python", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Barcode / scanning workflow",
                "Pick-pack-ship flows with handheld scanners.",
                ["python", "redis"],
                (16, 40),
                "medium",
            ),
            (
                "Carrier & label integration",
                "Multi-carrier rates, labels and tracking sync.",
                ["python", "httpx"],
                (16, 40),
                "medium",
            ),
        ],
    },
    "education": {
        "Courses & LMS": [
            (
                "Course authoring & catalog",
                "Course builder, modules, lessons and catalog.",
                ["typescript", "react", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Video lessons & progress",
                "Lesson player with resume and progress tracking.",
                ["typescript", "webrtc"],
                (24, 48),
                "medium",
            ),
            (
                "Certificates & badges",
                "Completion certificates and shareable badges.",
                ["python", "postgresql"],
                (12, 28),
                "low",
            ),
        ],
        "Assessments": [
            (
                "Quiz & exam engine",
                "Question banks, timed exams and auto-grading.",
                ["python", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Plagiarism & proctoring",
                "Similarity checks and remote proctoring hooks.",
                ["python", "scikit_learn"],
                (24, 48),
                "high",
            ),
            (
                "Grades & feedback",
                "Gradebook with rubric-based feedback.",
                ["python", "postgresql"],
                (16, 36),
                "medium",
            ),
        ],
    },
    "media": {
        "Content & Publishing": [
            (
                "Headless CMS",
                "Structured content modelling with a publishing workflow.",
                ["typescript", "graphql", "postgresql"],
                (24, 56),
                "high",
            ),
            (
                "Digital asset management",
                "Media library with transcoding and metadata.",
                ["python", "ffmpeg", "s3"],
                (24, 56),
                "high",
            ),
            (
                "Editorial workflow",
                "Draft-review-publish with roles and scheduling.",
                ["typescript", "react"],
                (16, 40),
                "medium",
            ),
        ],
        "Streaming & Playback": [
            (
                "Adaptive video streaming",
                "HLS/DASH packaging and adaptive bitrate playback.",
                ["python", "ffmpeg"],
                (32, 72),
                "high",
            ),
            (
                "Live streaming pipeline",
                "Low-latency live ingest and distribution.",
                ["python", "webrtc"],
                (32, 64),
                "high",
            ),
            (
                "DRM & entitlements",
                "Content protection and subscription entitlements.",
                ["python"],
                (16, 40),
                "high",
            ),
        ],
    },
    "government": {
        "Citizen Services": [
            (
                "Online application portal",
                "Multi-step citizen forms with eligibility checks.",
                ["typescript", "react", "python"],
                (24, 56),
                "high",
            ),
            (
                "Identity & eID integration",
                "National eID / verified identity onboarding.",
                ["python", "oauth"],
                (24, 56),
                "high",
            ),
            (
                "Appointment & case tracking",
                "Public-service appointments and case status.",
                ["python", "postgresql"],
                (16, 40),
                "medium",
            ),
        ],
        "Records & Compliance": [
            (
                "Public records registry",
                "Authoritative registry with versioning and search.",
                ["python", "postgresql", "elasticsearch"],
                (24, 64),
                "high",
            ),
            (
                "Accessibility & compliance",
                "WCAG 2.1 AA conformance and accessibility audit.",
                ["typescript"],
                (16, 36),
                "medium",
            ),
            (
                "Open-data publishing",
                "Datasets, APIs and transparency portals.",
                ["python", "fastapi"],
                (16, 40),
                "medium",
            ),
        ],
    },
}

SECTOR_TECH = {
    "finance": "ruby_on_rails",
    "ecommerce": "django",
    "healthcare": "python_fastapi",
    "industrial": "java_spring",
    "logistics": "go_gin",
    "education": "django",
    "media": "node_nestjs",
    "government": "java_spring",
}
SECTOR_COUNTRY = {
    "finance": "DE",
    "ecommerce": "ES",
    "healthcare": "FR",
    "industrial": "US",
    "logistics": "NL",
    "education": "GB",
    "media": "US",
    "government": "ES",
}
CLIENT_PREFIX = {
    "finance": ["NordBank", "PagoSeguro", "FinNova", "CapitalFlow"],
    "ecommerce": ["ShopHub", "MercadoVivo", "CartLabs", "TiendaUno"],
    "healthcare": ["SaludRed", "MediCore", "ClinicaPlus", "VitalCare"],
    "industrial": ["IndusTech", "FabricaSmart", "MaqExpert", "PlantaCore"],
    "logistics": ["CargoLink", "RutaViva", "FleetCore", "TransSmart"],
    "education": ["EduNova", "AulaViva", "LearnHub", "CampusOne"],
    "media": ["StreamLabs", "MediaForge", "PressVivo", "PlayCore"],
    "government": ["CivicaRed", "GobDigital", "PublicaOne", "EstadoSmart"],
}
ABBREV = {
    "Authentication & Access": "AUTH",
    "Data & Integrations": "DATA",
    "Frontend / UX": "FE",
    "Infrastructure & DevOps": "INFRA",
    "Security & Compliance": "SEC",
    "QA & Testing": "QA",
    "Project Management": "PM",
    "Analytics & Reporting": "ANL",
    "Notifications & Messaging": "NOTIF",
    "Search & Discovery": "SRCH",
    "Admin & Back-office": "ADMIN",
    "Integrations Platform": "INTG",
    "Payments & Billing": "PAY",
    "Regulatory Reporting": "REG",
    "Catalog & Search": "CAT",
    "Checkout & Cart": "CHK",
    "Clinical Records": "EHR",
    "Scheduling": "SCH",
    "Telemetry & IoT": "IOT",
    "Operations": "OPS",
    "Fleet & Routing": "FLEET",
    "Warehouse & Inventory": "WMS",
    "Courses & LMS": "LMS",
    "Assessments": "ASMT",
    "Content & Publishing": "CMS",
    "Streaming & Playback": "STRM",
    "Citizen Services": "CIT",
    "Records & Compliance": "REC",
}


def _modules_for(sector: str) -> dict[str, list[Template]]:
    """Módulos comunes más los propios del sector."""
    return {**COMMON_MODULES, **SECTOR_MODULES[sector]}


def _build_project(rng: random.Random, index: int) -> dict:
    """Sintetiza un proyecto histórico como un `Budget` (tareas = componentes)."""
    sector = rng.choice(list(SECTOR_MODULES))
    year = rng.choice([2022, 2023, 2024, 2025])
    catalog = _modules_for(sector)

    # Siempre los módulos del sector y una muestra de los comunes.
    sector_modules = list(SECTOR_MODULES[sector])
    common_pick = rng.sample(list(COMMON_MODULES), k=rng.randint(4, len(COMMON_MODULES)))
    chosen_modules = sector_modules + [m for m in common_pick if m not in sector_modules]

    components: list[dict] = []
    counters: dict[str, int] = {}
    for module in chosen_modules:
        templates = catalog[module]
        k = min(len(templates), rng.randint(2, 4))
        for name, desc, tech, (lo, hi), complexity in rng.sample(templates, k=k):
            counters[module] = counters.get(module, 0) + 1
            hours = rng.randint(lo, hi)
            tech_stack = rng.sample(tech, k=min(len(tech), rng.randint(1, len(tech))))
            components.append(
                {
                    "component_id": f"{ABBREV[module]}-{counters[module]:03d}",
                    "name": name,
                    "description": desc,
                    "module": module,
                    "tech_stack": tech_stack,
                    "estimated_hours": hours,
                    "complexity": complexity,
                    "dependencies": [],
                }
            )

    client = rng.choice(CLIENT_PREFIX[sector])
    summary_modules = ", ".join(chosen_modules[:3]).lower()
    return {
        "budget_id": f"TASK-{year}-{index:04d}",
        "client_metadata": {
            "name": f"{client} {rng.choice(['GmbH', 'S.L.', 'Inc.', 'SAS'])}",
            "sector": sector,
            "country": SECTOR_COUNTRY[sector],
        },
        "project_summary": f"{sector.capitalize()} platform covering {summary_modules}",
        "main_technology": SECTOR_TECH[sector],
        "year": year,
        "total_estimated_hours": sum(c["estimated_hours"] for c in components),
        "components": components,
    }


def generate_corpus(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> list[dict]:
    """`count` proyectos históricos, deterministas a partir de `seed`; cada uno valida contra `Budget`."""
    rng = random.Random(seed)
    return [_build_project(rng, i + 1) for i in range(count)]


def ingest_body(project: dict) -> dict:
    """Cuerpo de `POST /embeddings/ingest`: `source_path` estable por proyecto (base de la idempotencia)."""
    return {
        "source_path": f"{SOURCE_PREFIX}{project['budget_id']}",
        "document_type": DOCUMENT_TYPE,
        "chunk_type": CHUNK_TYPE,
        "content": project,
    }


def ingest_corpus(corpus: list[dict], client: httpx.Client) -> tuple[int, int]:
    """Un documento por proyecto; 409 = ya ingestado (se omite). Devuelve `(creados, omitidos)`."""
    created = skipped = 0
    for project in corpus:
        response = client.post("/embeddings/ingest", json=ingest_body(project))
        if response.status_code == 200:
            created += 1
        elif response.status_code == 409:
            skipped += 1
        else:
            raise RuntimeError(f"{project['budget_id']}: HTTP {response.status_code}")
    return created, skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera e ingesta el corpus de tareas históricas (Sesión 9).")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Número de proyectos.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Semilla (reproducible).")
    parser.add_argument("--out", type=Path, default=None, help="Ruta donde escribir el JSON generado.")
    parser.add_argument("--api", default=DEFAULT_API, help="URL base de la API (por defecto ESTIMATOR_API_BASE_URL).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--generate-only", action="store_true", help="Generar (y escribir con --out), sin ingestar.")
    mode.add_argument("--ingest", action="store_true", help="Generar e ingestar.")
    args = parser.parse_args(argv)

    corpus = generate_corpus(count=args.count, seed=args.seed)
    tasks = sum(len(project["components"]) for project in corpus)
    print(f"Corpus de tareas: {len(corpus)} proyectos / {tasks} tareas (semilla {args.seed}).")
    if args.out:
        args.out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Escrito en {args.out}.")
    if not args.ingest:
        if not args.generate_only:
            print("(solo generación; usa --ingest para cargarlo en pgvector)")
        return 0

    try:
        with httpx.Client(base_url=args.api, timeout=TIMEOUT_SECONDS) as client:
            created, skipped = ingest_corpus(corpus, client)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"ERROR al ingestar: {exc}", file=sys.stderr)
        return 1
    print(f"{created} ingestados, {skipped} ya presentes (chunk_type={CHUNK_TYPE}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
