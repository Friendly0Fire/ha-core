"""Config flow for Superlight."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.const import CONF_ENTITY_ID, Platform
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.schema_config_entry_flow import (
    wrapped_entity_config_entry_title,
)
from homeassistant.data_entry_flow import AbortFlow

from .const import DOMAIN

SUPERLIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=Platform.LIGHT),
        )
    }
)


class SuperlightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Superlight."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_entity_id: str | None = None

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""

        title = wrapped_entity_config_entry_title(self.hass, self._discovered_entity_id)

        registry = er.async_get(self.hass)
        entity_entry = registry.async_get(self._discovered_entity_id)
        if entity_entry is None:
            raise AbortFlow("underlying_entity_missing")

        if user_input is not None:
            if not entity_entry.hidden:
                registry.async_update_entity(
                    self._discovered_entity_id,
                    hidden_by=er.RegistryEntryHider.INTEGRATION,
                )
            return self.async_create_entry(
                data={},
                options={CONF_ENTITY_ID: self._discovered_entity_id},
                title=title,
            )

        self._set_confirm_only()
        placeholders = {"name": title}
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=placeholders,
        )

    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        """Handle automatic discovery."""
        self._discovered_entity_id = discovery_info[CONF_ENTITY_ID]
        return await self.async_step_discovery_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Get configuration from the user."""
        if user_input is not None:
            self._discovered_entity_id = user_input[CONF_ENTITY_ID]
            return await self.async_step_discovery_confirm(user_input)

        return self.async_show_form(step_id="user", data_schema=SUPERLIGHT_SCHEMA)
