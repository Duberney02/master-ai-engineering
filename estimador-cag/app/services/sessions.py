"""Memoria conversacional en el proceso: historial con ventana deslizante, metadatos del proyecto y sesiones.

Las sesiones viven en un diccionario del proceso (`SessionStore`), sin base de datos ni Redis. Se
acepta su volatilidad de forma deliberada:

- Es contexto auxiliar, no un registro: las estimaciones completadas ya se guardan de forma durable
  en el historial PostgreSQL, y perder una sesión solo obliga a volver a explicar el contexto.
- Se pierde al reiniciar el servicio y no se comparte entre procesos o réplicas, por lo que el
  servicio debe ejecutarse como un único proceso (como hace Docker Compose). Los clientes detectan
  el 404 de una sesión desconocida y abren una conversación nueva.
- El crecimiento está acotado: número máximo de sesiones, caducidad por inactividad y ventana de
  turnos por sesión.
"""

import asyncio
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

Message = dict[str, str]

# Turnos (pares usuario+asistente) que conserva y envía una sesión por defecto.
MAX_TURNS = 6

MAX_TECHNOLOGIES = 30
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
# Los metadatos se reinyectan en el prompt de sistema: sin marcado que pueda cerrar o abrir bloques.
_MARKUP_CHARS = re.compile(r"[<>`]")
_SPACES = re.compile(r"\s+")


def _clean(value: object) -> object:
    """Una sola línea, sin caracteres de control ni de marcado; vacío equivale a «desconocido»."""
    if not isinstance(value, str):
        return value
    text = _SPACES.sub(" ", _MARKUP_CHARS.sub(" ", _CONTROL_CHARS.sub(" ", value))).strip()
    return text or None


class ProjectMetadata(BaseModel):
    """Hechos conocidos del proyecto, acumulados a lo largo de la conversación.

    Los produce el LLM a partir de texto del usuario y se reinyectan en el prompt de sistema, de ahí
    la normalización (una línea, sin marcado) y los límites estrictos.
    """

    project_name: str | None = Field(default=None, max_length=120)
    assumed_team_size: int | None = Field(default=None, ge=1, le=1000)
    mentioned_technologies: list[Annotated[str, StringConstraints(max_length=60)]] = Field(
        default_factory=list, max_length=MAX_TECHNOLOGIES
    )
    agreed_scope: str | None = Field(default=None, max_length=1000)

    @field_validator("project_name", "agreed_scope", mode="before")
    @classmethod
    def _clean_text(cls, value: object) -> object:
        return _clean(value)

    @field_validator("mentioned_technologies", mode="before")
    @classmethod
    def _clean_technologies(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        cleaned = (_clean(item) for item in value)
        seen: dict[str, str] = {}
        for item in cleaned:
            if isinstance(item, str):
                seen.setdefault(item.casefold(), item)
            elif item is not None:
                return value  # tipo inválido: que lo rechace la validación estándar
        return list(seen.values())

    def is_empty(self) -> bool:
        return not (
            self.project_name or self.assumed_team_size or self.mentioned_technologies or self.agreed_scope
        )

    def merge(self, update: "ProjectMetadata") -> "ProjectMetadata":
        """Combina hechos nuevos con los conocidos: los valores nuevos no nulos sustituyen a los
        anteriores y las tecnologías se unen sin duplicados. Nunca se borra un hecho conocido."""
        technologies: dict[str, str] = {}
        for item in [*self.mentioned_technologies, *update.mentioned_technologies]:
            technologies.setdefault(item.casefold(), item)
        return ProjectMetadata(
            project_name=update.project_name or self.project_name,
            assumed_team_size=update.assumed_team_size or self.assumed_team_size,
            mentioned_technologies=list(technologies.values())[:MAX_TECHNOLOGIES],
            agreed_scope=update.agreed_scope or self.agreed_scope,
        )


class ConversationHistory:
    """Turnos recientes como pares completos usuario+asistente, con ventana deslizante.

    Al superar `max_turns` se descartan los pares más antiguos enteros (nunca un mensaje suelto, para
    que la conversación siga alternando roles). El system prompt no forma parte de los pares: se
    conserva siempre y se antepone en cada lista de mensajes.
    """

    def __init__(self, max_turns: int = MAX_TURNS, system_prompt: str = ""):
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.max_turns = max_turns
        self.system_prompt = system_prompt
        self._turns: deque[tuple[str, str]] = deque()

    def __len__(self) -> int:
        return len(self._turns)

    @property
    def turns(self) -> list[tuple[str, str]]:
        return list(self._turns)

    def add_turn(self, user: str, assistant: str) -> None:
        self._turns.append((user, assistant))
        while len(self._turns) > self.max_turns:
            self._turns.popleft()

    def messages(self, *, reserve: int = 0) -> list[Message]:
        """System prompt (si hay) y los últimos `max_turns - reserve` turnos. `reserve` deja hueco
        para el turno en curso, de modo que el total enviado, contándolo, respete `max_turns`."""
        keep = self.max_turns - reserve
        recent = list(self._turns)[-keep:] if keep > 0 else []
        messages: list[Message] = [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []
        for user, assistant in recent:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": assistant})
        return messages


@dataclass
class Session:
    """Una conversación: historial, metadatos del proyecto y un cerrojo que serializa sus peticiones."""

    session_id: str
    history: ConversationHistory
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def to_messages_list(
        self, render_system: Callable[[ProjectMetadata], str], user_message: str | None = None
    ) -> list[Message]:
        """Mensajes para el LLM: system prompt regenerado con los metadatos actuales, turnos
        recientes dentro de la ventana y, si se indica, el mensaje de usuario en curso.

        Con mensaje en curso solo se envían `max_turns - 1` turnos previos: el total de turnos que ve
        el modelo, contando el actual, nunca supera `max_turns`.
        """
        self.history.system_prompt = render_system(self.metadata)
        messages = self.history.messages(reserve=1 if user_message is not None else 0)
        if user_message is not None:
            messages.append({"role": "user", "content": user_message})
        return messages

    def record_turn(self, user: str, assistant: str, metadata: ProjectMetadata) -> None:
        """Confirma un turno completado: lo añade al historial y sustituye los metadatos."""
        self.history.add_turn(user, assistant)
        self.metadata = metadata


class SessionStore:
    """Sesiones por identificador (UUID v4) en un diccionario del proceso; ver el docstring del módulo."""

    def __init__(
        self,
        *,
        max_sessions: int = 200,
        ttl_seconds: float = 6 * 3600,
        max_turns: int = MAX_TURNS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def create(self) -> Session:
        self._evict()
        session = Session(
            session_id=str(uuid.uuid4()),
            history=ConversationHistory(self.max_turns),
            last_used=self._clock(),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """La sesión vigente (y la marca como usada) o None si no existe, caducó o el id no es un UUID v4."""
        try:
            parsed = uuid.UUID(session_id)
        except ValueError:
            return None
        if parsed.version != 4 or str(parsed) != session_id:
            return None
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._expired(session):
            del self._sessions[session_id]
            return None
        self.touch(session)
        return session

    def touch(self, session: Session) -> None:
        session.last_used = self._clock()

    def clear(self) -> None:
        self._sessions.clear()

    def _expired(self, session: Session) -> bool:
        return self._clock() - session.last_used > self.ttl_seconds

    def _evict(self) -> None:
        """Primero las caducadas; si sigue sin haber hueco, las menos recientes."""
        for key in [k for k, s in self._sessions.items() if self._expired(s)]:
            del self._sessions[key]
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda s: s.last_used)
            del self._sessions[oldest.session_id]


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Almacén único del proceso (dependencia de FastAPI; las pruebas lo sustituyen o lo reinician)."""
    global _store
    if _store is None:
        from app.config import get_settings

        settings = get_settings()
        _store = SessionStore(
            max_sessions=settings.session_max_count,
            ttl_seconds=settings.session_ttl_seconds,
            max_turns=settings.session_max_turns,
        )
    return _store


def reset_session_store() -> None:
    global _store
    _store = None
