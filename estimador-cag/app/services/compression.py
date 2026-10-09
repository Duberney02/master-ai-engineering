"""Política de compresión de la memoria conversacional.

Se ejecuta tras completar cada turno y trabaja solo sobre los turnos que han salido de la ventana
reciente (`ConversationHistory.drain_retired`): los que contienen un compromiso relevante se
conservan como anclas literales y el resto se combina con el resumen anterior. La estructura del
historial y el detector de anclas son componentes independientes; esta clase solo los orquesta.

Un fallo del resumidor nunca falla la estimación: se conserva el resumen anterior (los turnos
retirados no se reintentan; los compromisos ya están protegidos por las anclas).
"""

from dataclasses import dataclass, field

import structlog

from app.services.anchors import AnchorDetector, AnchorMatch
from app.services.llm_wrapper import Completion
from app.services.sessions import AnchorTurn, ConversationHistory
from app.services.summarizer import Summarizer

logger = structlog.get_logger(__name__)


@dataclass
class CompressionReport:
    retired: int = 0
    anchors: list[AnchorTurn] = field(default_factory=list)
    summarized: int = 0
    summary_updated: bool = False
    summary_failed: bool = False
    completions: list[Completion] = field(default_factory=list)


class CompressionPolicy:
    def __init__(self, detector: AnchorDetector, summarizer: Summarizer):
        self.detector = detector
        self.summarizer = summarizer

    async def apply(self, history: ConversationHistory) -> CompressionReport:
        report = CompressionReport()
        retired = history.drain_retired()
        report.retired = len(retired)
        if not retired:
            return report

        to_summarize: list[tuple[str, str]] = []
        for user, assistant in retired:
            match = await self._detect(user, assistant)
            if match is None:
                to_summarize.append((user, assistant))
                continue
            anchor = AnchorTurn(user=user, assistant=assistant, rules=match.rules)
            history.add_anchor(anchor)
            report.anchors.append(anchor)
            logger.info("anchor_detected", anchor_rules=list(match.rules), source=match.source)

        report.summarized = len(to_summarize)
        if to_summarize:
            await self._summarize(history, to_summarize, report)
        return report

    async def _detect(self, user: str, assistant: str) -> AnchorMatch | None:
        try:
            return await self.detector.detect(user, assistant)
        except Exception as exc:
            logger.warning("anchor_detection_failed", error_type=type(exc).__name__)
            return None

    async def _summarize(
        self, history: ConversationHistory, turns: list[tuple[str, str]], report: CompressionReport
    ) -> None:
        try:
            summary, completions = await self.summarizer.summarize(history.summary, turns)
        except Exception as exc:
            logger.warning("summary_failed", error_type=type(exc).__name__)
            report.summary_failed = True
            return
        report.completions.extend(completions)
        if not summary:
            logger.warning("summary_failed", error_type="EmptySummary")
            report.summary_failed = True
            return
        history.summary = summary
        report.summary_updated = True
        logger.info("summary_updated", summarized_turns=len(turns))
