from typing import Any

from homeassistant import config_entries
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, ButtonEntity
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, ATTR_ID, CONF_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SERVICE_SUPERLIGHT_POP_STATE


class SuperlightManualButton(ButtonEntity):
    def __init__(self, underlying_entity_id: str) -> None:
        self._light_id = f"{underlying_entity_id}_superlight"
        self.entity_id = (
            BUTTON_DOMAIN + self._light_id.removeprefix(LIGHT_DOMAIN) + "_manual"
        )

    async def async_press(self, **kwargs: Any) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_SUPERLIGHT_POP_STATE,
            {ATTR_ID: "__manual", ATTR_ENTITY_ID: self._light_id},
            True,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Superlight from a config entry."""
    registry = er.async_get(hass)
    entity_id = er.async_validate_entity_id(
        registry, config_entry.options[CONF_ENTITY_ID]
    )
    async_add_entities([SuperlightManualButton(entity_id)])
