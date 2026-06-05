"""Plugin registry — central store for all loaded domain plugins."""

from typing import Dict, Optional, Type
from openclaw.plugins.base_plugin import BasePlugin


class PluginRegistry:
    """Singleton-style registry for domain plugins."""

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        self._plugins[plugin.domain] = plugin

    def get(self, domain: str) -> Optional[BasePlugin]:
        return self._plugins.get(domain)

    def all_domains(self):
        return list(self._plugins.keys())

    def __iter__(self):
        return iter(self._plugins.values())
