"""Superlight."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.light import LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import CONF_TARGET
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Superlight(LightEntity):
    light_entity_id: str

    def __init__(self, hass: HomeAssistant, underlying_id: str) -> None:
        """Initialize Superlight."""

        registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        wrapped_light = registry.async_get(underlying_id)
        device_id = wrapped_light.device_id if wrapped_light else None
        entity_category = wrapped_light.entity_category if wrapped_light else None
        has_entity_name = wrapped_light.has_entity_name if wrapped_light else False
        unique_id = wrapped_light.unique_id if wrapped_light else None

        name = None
        if wrapped_light:
            name = wrapped_light.original_name + "*"

        self._device_id = device_id
        if device_id and (device := device_registry.async_get(device_id)):
            self._attr_device_info = DeviceInfo(
                connections=device.connections,
                identifiers=device.identifiers,
            )
        self._attr_entity_category = entity_category
        self._attr_has_entity_name = has_entity_name
        self._attr_name = name
        self._attr_unique_id = f"{unique_id}_superlight"
        self.light_entity_id = underlying_id

        self._is_new_entity = (
            registry.async_get_entity_id(LIGHT_DOMAIN, DOMAIN, unique_id) is None
        )

    @property
    def brightness(self) -> int:
        return 100

    @property
    def is_on(self) -> bool | None:
        return True

    def turn_on(self, **kwargs: Any) -> None:
        pass

    def turn_off(self, **kwargs: Any) -> None:
        pass


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Superlight from a config entry."""

    entity = Superlight(hass, entry.data[CONF_TARGET])
    async_add_entities([entity])
