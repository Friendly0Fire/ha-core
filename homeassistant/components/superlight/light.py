"""Superlight."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import sys
import logging
from typing import Any
import voluptuous as vol
from dataclasses import dataclass, field
from sortedcontainers import SortedSet
import funcy

from homeassistant.components.button import ButtonEntity
from homeassistant.components.homeassistant import exposed_entities
from homeassistant import config_entries
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT_LIST,
    ATTR_HS_COLOR,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
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
    State,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
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
    STATE_OFF,
    STATE_UNAVAILABLE,
    CONF_ENTITY_ID,
)
from homeassistant.helpers.event import async_track_state_change_event
from .const import (
    DOMAIN,
    SERVICE_SUPERLIGHT_PUSH_STATE,
    SERVICE_SUPERLIGHT_POP_STATE,
    ATTR_PRIORITY,
    ATTR_TURN_ON,
    ATTR_UNLATCH,
)

_LOGGER = logging.getLogger(__name__)

SUPERLIGHT_PUSH_STATE_SCHEMA = {
    **LIGHT_TURN_ON_SCHEMA,
    ATTR_PRIORITY: vol.Coerce(int),
    ATTR_ID: vol.Coerce(str),
    ATTR_TURN_ON: vol.Coerce(bool),
    ATTR_UNLATCH: vol.Coerce(bool),
}

SUPERLIGHT_POP_STATE_SCHEMA = {
    ATTR_ID: vol.Coerce(str),
}

SUPERLIGHT_GET_STATES_SCHEMA = {}

VALID_LIGHT_ATTRIBUTES = [str(attr) for attr in LIGHT_TURN_ON_SCHEMA]


@dataclass(order=True)
class PrioritizedState:
    priority: int
    id: str = field(compare=False)
    state: bool = field(compare=False)
    unlatch: bool = field(compare=False)
    attributes: dict[str, Any] = field(compare=False)

    def __init__(
        self,
        light: LightEntity,
        attributes: Mapping[str, Any],
        state: str | bool | None = None,
        priority: int | None = None,
        id: str | None = None,
        pop: bool = False,
    ):
        self.id = id if id is not None else attributes[ATTR_ID]
        if not pop:
            self.unlatch = attributes.get(ATTR_UNLATCH, False)
            self.priority = (
                priority if priority is not None else attributes[ATTR_PRIORITY]
            )
            if not self.unlatch:
                if state is not None:
                    self.state = state == "on" or state
                else:
                    self.state = (
                        attributes[ATTR_TURN_ON] or attributes[ATTR_TURN_ON] == "on"
                    )
                self.attributes = funcy.project(attributes, VALID_LIGHT_ATTRIBUTES)
            else:
                self.state = None
                self.attributes = None
        else:
            self.priority = 0
            self.state = None
            self.attributes = None
            self.unlatch = False

    def __eq__(self, value: PrioritizedState) -> bool:
        return self.id == value.id

    def __hash__(self) -> int:
        return self.id.__hash__()


MAX_PRIORITY: int = sys.maxsize
MANUAL_ID: str = "__manual"


class Superlight(LightEntity):
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_title: str,
        underlying_entity_id: str,
        unique_id: str,
    ) -> None:
        """Initialize Superlight."""

        registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        wrapped_light = registry.async_get(underlying_entity_id)
        device_id = wrapped_light.device_id if wrapped_light else None
        entity_category = wrapped_light.entity_category if wrapped_light else None
        has_entity_name = wrapped_light.has_entity_name if wrapped_light else False
        name: str | None = config_entry_title
        if wrapped_light:
            name = wrapped_light.original_name

        self._device_id = device_id
        if device_id and (device := device_registry.async_get(device_id)):
            self._attr_device_info = DeviceInfo(
                connections=device.connections,
                identifiers=device.identifiers,
            )
        self._attr_entity_category = entity_category
        self._attr_has_entity_name = has_entity_name
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._light_entity_id = underlying_entity_id
        self._is_new_entity = (
            registry.async_get_entity_id(LIGHT_DOMAIN, DOMAIN, unique_id) is None
        )
        self.entity_id = f"{underlying_entity_id}_superlight"

        self._attr_supported_color_modes = (
            wrapped_light.capabilities[ATTR_SUPPORTED_COLOR_MODES]
            if wrapped_light
            else None
        )

        if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
            self._attr_min_color_temp_kelvin = (
                wrapped_light.capabilities[ATTR_MIN_COLOR_TEMP_KELVIN]
                if wrapped_light
                else None
            )

            self._attr_max_color_temp_kelvin = (
                wrapped_light.capabilities[ATTR_MAX_COLOR_TEMP_KELVIN]
                if wrapped_light
                else None
            )

        self._attr_effect_list = (
            wrapped_light.capabilities[ATTR_EFFECT_LIST]
            if wrapped_light and ATTR_EFFECT_LIST in wrapped_light.capabilities
            else None
        )

        self.states = SortedSet()
        self._attr_extra_state_attributes = {"states": {}}

    def _make_context(self):
        return Context(parent_id=self.unique_id)

    async def _apply_state(self):
        state: PrioritizedState | None = None
        if len(self.states) > 0:
            state = self.states[-1]

        if (state is not None) and state.unlatch:
            return

        if (state is not None) and state.state:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: self._light_entity_id, **state.attributes},
                blocking=True,
                context=self._make_context(),
            )
        else:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self._light_entity_id},
                blocking=True,
                context=self._make_context(),
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn device on."""

        if ATTR_COLOR_TEMP in kwargs and ATTR_COLOR_TEMP_KELVIN in kwargs:
            del kwargs[ATTR_COLOR_TEMP]

        await self._add_state(
            PrioritizedState(
                self, kwargs, state=True, priority=MAX_PRIORITY, id=MANUAL_ID
            )
        )

    async def push_state(self, **kwargs: Any) -> None:
        await self._add_state(PrioritizedState(self, kwargs))

    async def pop_state(self, **kwargs: Any) -> None:
        await self._remove_state(kwargs["id"])

    def _update_states(self):
        self._attr_extra_state_attributes["states"] = {
            s.id: {
                "priority": s.priority,
                "unlatch": s.unlatch,
                "state": STATE_ON if s.state else STATE_OFF,
                "attributes": s.attributes,
            }
            for s in self.states
        }

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn device off."""

        await self._add_state(
            PrioritizedState(self, {}, state=False, priority=MAX_PRIORITY, id=MANUAL_ID)
        )

    def _sync_state(self, state: State):
        self._attr_is_on = state.state == STATE_ON
        self._attr_color_mode = state.attributes.get(ATTR_COLOR_MODE)
        self._attr_brightness = state.attributes.get(ATTR_BRIGHTNESS)
        self._attr_hs_color = state.attributes.get(ATTR_HS_COLOR)
        self._attr_xy_color = state.attributes.get(ATTR_XY_COLOR)
        self._attr_rgb_color = state.attributes.get(ATTR_RGB_COLOR)
        self._attr_rgbw_color = state.attributes.get(ATTR_RGBW_COLOR)
        self._attr_rgbww_color = state.attributes.get(ATTR_RGBWW_COLOR)
        self._attr_color_temp = state.attributes.get(ATTR_COLOR_TEMP)

    @callback
    def async_state_changed_listener(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Handle child updates."""

        if (
            state := self.hass.states.get(self._light_entity_id)
        ) is None or state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            return

        self._attr_available = True

        # Skip events if we have no stack: we let the underlying light do what it wants
        if len(self.states) == 0 or self.states[-1].unlatch:
            self._sync_state(state)
            return

        # Skip events spawned by this Superlight
        if (
            (event is not None)
            and (event.context is not None)
            and ((orgevt := event.context.origin_event) is not None)
        ):
            if (
                orgevt.event_type == EVENT_CALL_SERVICE
                and orgevt.data.get(ATTR_DOMAIN) == LIGHT_DOMAIN
                and orgevt.data.get(ATTR_SERVICE) in [SERVICE_TURN_ON, SERVICE_TURN_OFF]
            ):
                if orgevt.context.parent_id == self.unique_id:
                    # We can reflect the underlying light state after it's been translated and applied by HA
                    self._sync_state(state)
                    return

            # Skip events not caused by a light domain service call or a state change (e.g., from an external app)
            if (
                orgevt.event_type != EVENT_CALL_SERVICE
                or orgevt.data.get(ATTR_DOMAIN) != LIGHT_DOMAIN
            ) and (orgevt.event_type != EVENT_STATE_CHANGED):
                return

        asyncio.run_coroutine_threadsafe(self._apply_state(), self.hass.loop)

    async def _add_state(self, state: PrioritizedState):
        self.states.discard(state)
        self.states.add(state)
        await self._apply_state()
        self._update_states()

    async def _remove_state(self, id: str):
        dummy = PrioritizedState(self, {}, id=id, pop=True)
        for s in self.states:
            if s == dummy:
                self.states.remove(s)
                break
        await self._apply_state()
        self._update_states()

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
                self.hass, [self._light_entity_id], _async_state_changed_listener
            )
        )

        # Call once on adding
        _async_state_changed_listener()

        # Update entity options
        registry = er.async_get(self.hass)
        if registry.async_get(self.entity_id) is not None:
            registry.async_update_entity_options(
                self.entity_id,
                DOMAIN,
                self.async_generate_entity_options(),
            )

        if not self._is_new_entity or not (
            wrapped_light := registry.async_get(self._light_entity_id)
        ):
            return

        def copy_custom_name(wrapped_light: er.RegistryEntry) -> None:
            """Copy the name set by user from the wrapped entity."""
            if wrapped_light.name is None:
                return
            registry.async_update_entity(self.entity_id, name=wrapped_light.name)

        def copy_expose_settings() -> None:
            """Copy assistant expose settings from the wrapped entity.

            Also unexpose the wrapped entity if exposed.
            """
            expose_settings = exposed_entities.async_get_entity_settings(
                self.hass, self._light_entity_id
            )
            for assistant, settings in expose_settings.items():
                if (should_expose := settings.get("should_expose")) is None:
                    continue
                exposed_entities.async_expose_entity(
                    self.hass, assistant, self.entity_id, should_expose
                )
                exposed_entities.async_expose_entity(
                    self.hass, assistant, self._light_entity_id, False
                )

        copy_custom_name(wrapped_light)
        copy_expose_settings()

    @callback
    def async_generate_entity_options(self) -> dict[str, Any]:
        """Generate entity options."""
        return {"entity_id": self._light_entity_id}


class SuperlightManualButton(ButtonEntity):
    def __init__(self, superlight: Superlight):
        self._light_id = superlight.entity_id
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
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SUPERLIGHT_PUSH_STATE,
        SUPERLIGHT_PUSH_STATE_SCHEMA,
        "push_state",
    )
    platform.async_register_entity_service(
        SERVICE_SUPERLIGHT_POP_STATE,
        SUPERLIGHT_POP_STATE_SCHEMA,
        "pop_state",
    )

    sl = Superlight(hass, config_entry.title, entity_id, config_entry.entry_id)

    async_add_entities(
        [
            sl,
            SuperlightManualButton(sl),
        ]
    )
