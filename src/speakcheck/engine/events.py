"""Minimal synchronous pub/sub so frontends can show progress without the engine knowing about them."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


Listener = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[tuple[Listener, frozenset[str] | None]] = []

    def subscribe(self, listener: Listener, types: Iterable[str] | None = None) -> Callable[[], None]:
        entry = (listener, frozenset(types) if types is not None else None)
        self._listeners.append(entry)
        return lambda: self._listeners.remove(entry)

    def emit(self, type: str, **data: Any) -> None:
        event = Event(type, data)
        for listener, types in list(self._listeners):
            if types is None or type in types:
                listener(event)
