"""Config flow for Superlight."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.const import CONF_TARGET, CONF_ALIAS, CONF_NAME

from .const import DOMAIN
from .light import Superlight


class SuperlightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Superlight."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
        self._discovered_alias = None
        self._discovered_id = None

    async def async_step_discovered_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self.async_create_entry(
                title=self._discovered_alias,
                data={CONF_TARGET: self._discovered_id},
            )

        placeholders = {
            "label": self._discovered_alias,
            # "group": discovered.group,
        }
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="discovered_light",
            description_placeholders=placeholders,
        )

    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        self._discovered_alias = discovery_info[CONF_ALIAS]
        self._discovered_id = discovery_info[CONF_TARGET]
        return await self.async_step_discovered_light()
