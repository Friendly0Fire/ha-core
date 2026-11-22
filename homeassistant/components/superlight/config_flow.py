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
from homeassistant.const import CONF_ENTITY_ID, CONF_ALIAS, CONF_UNIQUE_ID

from .const import DOMAIN
from .light import Superlight


class SuperlightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Superlight."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_device: Superlight | None = None

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_device.name,
                data={CONF_ENTITY_ID: self._discovered_device.light_entity_id},
            )

        self._set_confirm_only()
        placeholders = {"name": self._discovered_device.name}
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=placeholders,
        )

    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        """Handle automatic discovery."""
        self._discovered_device = Superlight(self.hass, discovery_info[CONF_ENTITY_ID])
        await self.async_set_unique_id(
            self._discovered_device.unique_id, raise_on_progress=False
        )
        return await self.async_step_discovery_confirm()
