"""Superlight."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SERVICE_DATA,
    CONF_TARGET,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.helpers.event import async_track_state_change_event
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
            name = wrapped_light.original_name + "+"

        self._device_id = f"{device_id}_superlight"
        if device_id and (device := device_registry.async_get(device_id)):
            self._attr_device_info = DeviceInfo(
                connections=device.connections,
                identifiers=device.identifiers,
            )
        self._attr_entity_category = entity_category
        self._attr_has_entity_name = has_entity_name
        self._attr_name = name
        self._attr_unique_id = f"{unique_id}_superlight"
        self._attr_supported_color_modes = (
            wrapped_light.capabilities["supported_color_modes"]
            if wrapped_light
            else None
        )
        self._attr_supported_features = (
            wrapped_light.supported_features if wrapped_light else 0
        )
        self.light_entity_id = underlying_id

        self._is_new_entity = (
            registry.async_get_entity_id(LIGHT_DOMAIN, DOMAIN, unique_id) is None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn device on."""
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.light_entity_id, **kwargs},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn device off."""
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self.light_entity_id, **kwargs},
        )

    @callback
    def async_state_changed_listener(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Handle child updates."""

        if (
            state := self.hass.states.get(self.light_entity_id)
        ) is None or state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            return

        self._attr_available = True
        self._attr_color_mode = state.attributes[ATTR_COLOR_MODE]
        self._attr_is_on = state.state == STATE_ON
        self._attr_brightness = state.attributes[ATTR_BRIGHTNESS]
        self._attr_hs_color = state.attributes[ATTR_HS_COLOR]
        self._attr_xy_color = state.attributes[ATTR_XY_COLOR]
        self._attr_rgb_color = state.attributes[ATTR_RGB_COLOR]
        self._attr_rgbw_color = state.attributes[ATTR_RGBW_COLOR]

        if ATTR_RGBWW_COLOR in state.attributes:
            self._attr_rgbww_color = state.attributes[ATTR_RGBWW_COLOR]

        if ATTR_COLOR_TEMP in state.attributes:
            self._attr_color_temp = state.attributes[ATTR_COLOR_TEMP]

    async def async_added_to_hass(self) -> None:
        """Register callbacks and copy the wrapped entity's custom name if set."""

        @callback
        def _async_state_changed_listener(
            event: Event[EventStateChangedData] | None = None,
        ) -> None:
            """Handle child updates."""
            self.async_state_changed_listener(event)
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.light_entity_id], _async_state_changed_listener
            )
        )

        # Call once on adding
        _async_state_changed_listener()

    @callback
    def async_generate_entity_options(self) -> dict[str, Any]:
        """Generate entity options."""
        return {"entity_id": self.light_entity_id}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Superlight from a config entry."""

    entity = Superlight(hass, entry.data[CONF_TARGET])
    async_add_entities([entity])
