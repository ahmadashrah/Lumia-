"""Connector discovery.

Drop a module in this package that defines a Connector subclass and it
registers itself — no edits to a central list, which is what makes adding
the next platform cheap.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterator

from .base import Connector

_cache: dict[str, Connector] | None = None


def _discover() -> dict[str, Connector]:
    found: dict[str, Connector] = {}
    package = importlib.import_module(__package__)
    for mod in pkgutil.iter_modules(package.__path__):
        if mod.name.startswith("_") or mod.name in {"base", "models", "registry", "outbox", "store"}:
            continue
        try:
            m = importlib.import_module(f"{__package__}.{mod.name}")
        except Exception as exc:                      # a broken connector must not break the app
            print(f"[integrations] skipped {mod.name}: {exc}")
            continue
        for attr in vars(m).values():
            if (isinstance(attr, type) and issubclass(attr, Connector)
                    and attr is not Connector and not getattr(attr, "__abstractmethods__", None)):
                try:
                    inst = attr()
                except Exception as exc:
                    print(f"[integrations] {attr.__name__} would not construct: {exc}")
                    continue
                found[inst.name] = inst
    return found


def all_connectors(refresh: bool = False) -> dict[str, Connector]:
    global _cache
    if _cache is None or refresh:
        _cache = _discover()
    return _cache


def get(name: str) -> Connector | None:
    return all_connectors().get(name)


def configured() -> Iterator[Connector]:
    for c in all_connectors().values():
        if c.is_configured():
            yield c
