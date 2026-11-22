"""Superlight."""

from __future__ import annotations

import sys
import logging
from typing import Any, Mapping
import voluptuous as vol
import heapq
from dataclasses import dataclass, field

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
    LIGHT_TURN_ON_SCHEMA,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    Context,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_ID,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    EVENT_CALL_SERVICE,
    EVENT_STATE_CHANGED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.helpers.event import async_track_state_change_event
from .const import DOMAIN, SERVICE_SUPERLIGHT_PUSH_STATE, ATTR_PRIORITY
import contextlib

_LOGGER = logging.getLogger(__name__)

SUPERLIGHT_PUSH_STATE_SCHEMA = {
    **LIGHT_TURN_ON_SCHEMA,
    ATTR_PRIORITY: vol.Coerce(int),
    ATTR_ID: vol.Coerce(str),
}


@dataclass(order=True)
class PrioritizedState:
    priority: int
    id: str = field(compare=False)
    state: str = field(compare=False)
    attributes: Mapping[str, Any] = field(compare=False)

    def __eq__(self, value: PrioritizedState) -> bool:
        return self.id == value.id


MAX_PRIORITY: int = sys.maxsize
MANUAL_ID: str = "__manual"


class Superlight(LightEntity):
    light_entity_id: str
    states: list[PrioritizedState]

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
            if wrapped_light.original_name:
                name = wrapped_light.original_name + "+"
            elif wrapped_light.name:
                name = wrapped_light.name + "+"
            else:
                name = f"<{underlying_id}>+"

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
        self.states = []

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn device on."""
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.light_entity_id, **kwargs},
            context=Context(parent_id=self.unique_id),
        )

    async def push_state(self, **kwargs: Any) -> None:
        pass

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
        self._attr_is_on = state.state == STATE_ON
        self._attr_color_mode = state.attributes.get(ATTR_COLOR_MODE)
        self._attr_brightness = state.attributes.get(ATTR_BRIGHTNESS)
        self._attr_hs_color = state.attributes.get(ATTR_HS_COLOR)
        self._attr_xy_color = state.attributes.get(ATTR_XY_COLOR)
        self._attr_rgb_color = state.attributes.get(ATTR_RGB_COLOR)
        self._attr_rgbw_color = state.attributes.get(ATTR_RGBW_COLOR)
        self._attr_rgbww_color = state.attributes.get(ATTR_RGBWW_COLOR)
        self._attr_color_temp = state.attributes.get(ATTR_COLOR_TEMP)

        # Skip events spawned by this Superlight
        orgevt = event.context.origin_event
        if (
            orgevt.event_type == EVENT_CALL_SERVICE
            and orgevt.data.get(ATTR_DOMAIN) == LIGHT_DOMAIN
            and orgevt.data.get(ATTR_SERVICE) == SERVICE_TURN_ON
        ):
            if orgevt.context.parent_id == self.unique_id:
                return

        # Skip events not caused by a light domain service call
        if (
            orgevt.event_type != EVENT_CALL_SERVICE
            or orgevt.data.get(ATTR_DOMAIN) != LIGHT_DOMAIN
        ):
            return

        self._add_state(
            PrioritizedState(MAX_PRIORITY, MANUAL_ID, state.state, state.attributes)
        )

    def _add_state(self, state: PrioritizedState):
        with contextlib.suppress(ValueError):
            self.states.remove(state)
        self.states.append(state)
        self.states.sort(reverse=True)

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

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
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Superlight from a config entry."""

    registry = er.async_get(hass)
    entity_id = er.async_validate_entity_id(
        registry, config_entry.options[CONF_ENTITY_ID]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SUPERLIGHT_PUSH_STATE,
        SUPERLIGHT_PUSH_STATE_SCHEMA,
        "push_state",
    )

    entity = Superlight(hass, entity_id)
    async_add_entities([entity])
