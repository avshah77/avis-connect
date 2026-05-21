"""
Connector plugin registry — auto-discovers connectors in connect/connectors/.
Any module containing a class that inherits BaseConnector is registered.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from connect.connectors.base import BaseConnector

_registry: dict[str, type["BaseConnector"]] = {}


def _load_connectors() -> None:
    import connect.connectors as pkg
    for _, module_name, _ in pkgutil.iter_modules(pkg.__path__):
        if module_name == "base":
            continue
        mod = importlib.import_module(f"connect.connectors.{module_name}")
        for attr in vars(mod).values():
            try:
                from connect.connectors.base import BaseConnector
                if (isinstance(attr, type)
                        and issubclass(attr, BaseConnector)
                        and attr is not BaseConnector
                        and hasattr(attr, "name")):
                    _registry[attr.name] = attr
            except ImportError:
                pass


def get_connector(connector_type: str) -> "BaseConnector":
    if not _registry:
        _load_connectors()
    cls = _registry.get(connector_type)
    if cls is None:
        available = list(_registry.keys())
        raise ValueError(f"No connector registered for '{connector_type}'. Available: {available}")
    return cls()


def list_connectors() -> list[str]:
    if not _registry:
        _load_connectors()
    return list(_registry.keys())
