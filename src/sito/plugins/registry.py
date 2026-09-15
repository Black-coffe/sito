"""Plugin discovery.

Plugins are found in three places, in this order:

1. built-in modules shipped with sito (``BUILTIN_MODULES``);
2. installed packages exposing a ``sito.plugins`` entry point (value = module);
3. ``*.py`` files dropped into the plugins folder (``SITO_PLUGINS_DIR``).

A module registers every :class:`Stage` / :class:`Connector` subclass it
*defines* that has a non-empty ``id``. Errors never crash the app: they are
collected and shown on the Plugins page.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType

from sito.plugins.base import Connector, PluginError, Stage

log = logging.getLogger("sito.plugins")

BUILTIN_MODULES = (
    "sito.connectors.llm",
    "sito.connectors.serp",
    "sito.connectors.suggest",
    "sito.connectors.demo",
    "sito.stages.sources",
    "sito.stages.transform",
    "sito.stages.ai",
    "sito.stages.serp",
    "sito.stages.clustering",
    "sito.stages.output",
)


@dataclass
class PluginRegistry:
    stages: dict[str, type[Stage]] = field(default_factory=dict)
    connectors: dict[str, type[Connector]] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_stage(self, cls: type[Stage], origin: str) -> None:
        if cls.id in self.stages:
            self.errors.append(f"Stage id '{cls.id}' from {origin} is already taken; ignored.")
            return
        self.stages[cls.id] = cls
        self.origins[f"stage:{cls.id}"] = origin

    def add_connector(self, cls: type[Connector], origin: str) -> None:
        if cls.id in self.connectors:
            self.errors.append(f"Connector id '{cls.id}' from {origin} is already taken; ignored.")
            return
        self.connectors[cls.id] = cls
        self.origins[f"connector:{cls.id}"] = origin

    def register_module(self, module: ModuleType, origin: str) -> None:
        for obj in list(vars(module).values()):
            if not isinstance(obj, type) or obj.__module__ != module.__name__:
                continue
            if issubclass(obj, Stage) and obj.id:
                self.add_stage(obj, origin)
            elif issubclass(obj, Connector) and obj.id:
                self.add_connector(obj, origin)

    def stage(self, stage_id: str) -> type[Stage]:
        try:
            return self.stages[stage_id]
        except KeyError:
            raise PluginError(f"The stage plugin '{stage_id}' is not installed.") from None

    def connector(self, connector_id: str) -> type[Connector]:
        try:
            return self.connectors[connector_id]
        except KeyError:
            raise PluginError(f"The connector plugin '{connector_id}' is not installed.") from None

    def connectors_of_kind(self, kind: str) -> list[type[Connector]]:
        return [c for c in self.connectors.values() if c.kind == kind]


def load_registry(plugins_dir: Path | None = None, builtin: bool = True) -> PluginRegistry:
    registry = PluginRegistry()
    if builtin:
        for name in BUILTIN_MODULES:
            try:
                registry.register_module(importlib.import_module(name), "built-in")
            except Exception as exc:  # noqa: BLE001 - report, never crash
                registry.errors.append(f"Built-in module {name} failed to load: {exc}")
                log.exception("built-in plugin module %s failed", name)

    for ep in entry_points(group="sito.plugins"):
        try:
            registry.register_module(ep.load(), f"package {ep.value}")
        except Exception as exc:  # noqa: BLE001
            registry.errors.append(f"Plugin package {ep.value} failed to load: {exc}")
            log.exception("plugin entry point %s failed", ep.value)

    if plugins_dir and plugins_dir.is_dir():
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod_name = f"sito_local_plugins.{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is None or spec.loader is None:
                    raise ImportError("cannot create module spec")
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
                registry.register_module(module, f"file {path.name}")
            except Exception as exc:  # noqa: BLE001
                registry.errors.append(f"Plugin file {path.name} failed to load: {exc}")
                log.exception("plugin file %s failed", path)
    return registry
