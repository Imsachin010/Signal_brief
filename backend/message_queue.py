"""
SignalBrief -- Message Queue (Deferred Queue)
===============================================
Protocol Section 3 -- Holds deferred messages and flushes them
intelligently when signal quality recovers.

Flush strategy
--------------
  1. Sort by triage_score DESC
  2. Deliver top 3 immediately (DELIVER_IMMEDIATE)
  3. Bundle remaining into digest (FLUSH_DIGEST) if count > 3
  4. Mark all others as summarized
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QueuedMessage:
    """Thin wrapper stored in the deferred queue."""
    message_id: str
    sender: str
    text: str
    triage_score: float
    urgency_score: float
    triage_action: str
    queued_at: str       # ISO timestamp


@dataclass
class FlushResult:
    """Outcome of a flush() call."""
    immediate: list[QueuedMessage]   # deliver right now
    digest_batch: list[QueuedMessage]  # roll into digest
    total_flushed: int
    trigger_reason: str


class DeferredQueue:
    """
    Thread-unsafe in-memory deferred message queue.
    The controller's asyncio.Lock() provides thread safety.

    Protocol thresholds
    -------------------
    immediate_threshold   : triage_score >= 0.50 gets delivered immediately
    max_immediate_per_flush: cap on how many get immediate delivery at once
    """

    def __init__(
        self,
        immediate_threshold: float = 0.50,
        max_immediate_per_flush: int = 3,
    ) -> None:
        self._items: list[QueuedMessage] = []
        self.immediate_threshold = immediate_threshold
        self.max_immediate_per_flush = max_immediate_per_flush

    # ---- Queue operations ---------------------------------------------------

    def enqueue(self, msg: QueuedMessage) -> None:
        """Add a message to the deferred queue."""
        self._items.append(msg)

    def remove(self, message_id: str) -> bool:
        """Remove a message by ID. Returns True if found."""
        before = len(self._items)
        self._items = [m for m in self._items if m.message_id != message_id]
        return len(self._items) < before

    def clear(self) -> None:
        self._items.clear()

    def is_empty(self) -> bool:
        return len(self._items) == 0

    @property
    def count(self) -> int:
        return len(self._items)

    def peek(self) -> list[QueuedMessage]:
        """Return a sorted snapshot (highest score first) without removing."""
        return sorted(self._items, key=lambda m: m.triage_score, reverse=True)

    # ---- Flush Logic ---------------------------------------------------------

    def flush(self, trigger_reason: str = "zone_recovery") -> FlushResult:
        """
        Flush the queue.

        Returns FlushResult with:
          - immediate: top N by score (delivered now)
          - digest_batch: remainder (bundled into a digest)
        """
        if self.is_empty():
            return FlushResult(
                immediate=[],
                digest_batch=[],
                total_flushed=0,
                trigger_reason=trigger_reason,
            )

        sorted_items = self.peek()
        self._items.clear()

        # Split: high-score messages get immediate delivery
        immediate = [
            m for m in sorted_items
            if m.triage_score >= self.immediate_threshold
        ][:self.max_immediate_per_flush]

        immediate_ids = {m.message_id for m in immediate}
        digest_batch = [m for m in sorted_items if m.message_id not in immediate_ids]

        return FlushResult(
            immediate=immediate,
            digest_batch=digest_batch,
            total_flushed=len(sorted_items),
            trigger_reason=trigger_reason,
        )

    def flush_critical_only(self, trigger_reason: str = "brief_window") -> FlushResult:
        """
        Only flush messages with urgency_score >= 0.75 (for RED zone recovery).
        Leaves lower-priority messages in queue.
        """
        critical = [m for m in self._items if m.urgency_score >= 0.75]
        non_critical = [m for m in self._items if m.urgency_score < 0.75]

        self._items = non_critical

        return FlushResult(
            immediate=critical,
            digest_batch=[],
            total_flushed=len(critical),
            trigger_reason=trigger_reason,
        )

    # ---- Stats ---------------------------------------------------------------

    def stats(self) -> dict:
        if self.is_empty():
            return {"count": 0, "avg_score": 0.0, "max_score": 0.0, "min_score": 0.0}
        scores = [m.triage_score for m in self._items]
        return {
            "count": len(self._items),
            "avg_score": round(sum(scores) / len(scores), 4),
            "max_score": round(max(scores), 4),
            "min_score": round(min(scores), 4),
        }

    def to_dict_list(self) -> list[dict]:
        return [
            {
                "message_id": m.message_id,
                "sender": m.sender,
                "text_preview": m.text[:60],
                "triage_score": m.triage_score,
                "urgency_score": m.urgency_score,
                "triage_action": m.triage_action,
                "queued_at": m.queued_at,
            }
            for m in self.peek()
        ]


# Module singleton
deferred_queue = DeferredQueue()
