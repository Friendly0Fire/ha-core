"""Superlight."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import sys
from typing import Any, override

import funcy
import probatio
from sortedcontainers import SortedSet

from homeassistant import config_entries
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT_LIST,
    ATTR_HS_COLOR,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_XY_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    LIGHT_TURN_ON_SCHEMA,
    ColorMode,
    LightEntity,
)
from homeassistant.const import (
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_ID,
    ATTR_SERVICE,
    CONF_ENTITY_ID,
    EVENT_CALL_SERVICE,
    EVENT_STATE_CHANGED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import (
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import ATTR_PRIORITY, ATTR_TURN_ON, ATTR_UNLATCH, DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPERLIGHT_PUSH_STATE_SCHEMA = {
    **LIGHT_TURN_ON_SCHEMA,
    ATTR_PRIORITY: probatio.Coerce(int),
    ATTR_ID: probatio.Coerce(str),
    ATTR_TURN_ON: probatio.Coerce(bool),
    ATTR_UNLATCH: probatio.Coerce(bool),
}

SUPERLIGHT_POP_STATE_SCHEMA = {
    ATTR_ID: probatio.Coerce(str),
}

# SUPERLIGHT_GET_STATES_SCHEMA = {}

VALID_LIGHT_ATTRIBUTES = [str(attr) for attr in LIGHT_TURN_ON_SCHEMA]


@dataclass(order=True)
class PrioritizedState:
    """Prioritized State."""

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
    ) -> None:
        """Init."""
        self.id = id if id is not None else attributes[ATTR_ID]
        if not pop:
            self.unlatch = attributes.get(ATTR_UNLATCH, False)
            self.priority = (
                priority if priority is not None else attributes[ATTR_PRIORITY]
            )
            if not self.unlatch:
                if state is not None:
                    self.state = state in {"on", True}
                else:
                    self.state = (
                        attributes[ATTR_TURN_ON] or attributes[ATTR_TURN_ON] == "on"
                    )
                self.attributes = funcy.project(attributes, VALID_LIGHT_ATTRIBUTES)
            else:
                self.state = False
                self.attributes = {}
        else:
            self.priority = 0
            self.state = False
            self.attributes = {}
            self.unlatch = False

    @override
    def __eq__(self, value: object) -> bool:
        """Q."""
        return isinstance(value, PrioritizedState) and self.id == value.id

    @override
    def __hash__(self) -> int:
        """Hash."""
        return self.id.__hash__()


MAX_PRIORITY: int = sys.maxsize
MANUAL_ID: str = "__manual"


class Superlight(LightEntity):
    """Superlight."""

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
                connections=device.connections
                if isinstance(device, dr.DeviceEntry)
                else set[tuple[str, str]](),
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
            if wrapped_light is not None and wrapped_light.capabilities is not None
            else None
        )

        if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
            self._attr_min_color_temp_kelvin = (
                wrapped_light.capabilities[ATTR_MIN_COLOR_TEMP_KELVIN]
                if wrapped_light is not None and wrapped_light.capabilities is not None
                else None
            )

            self._attr_max_color_temp_kelvin = (
                wrapped_light.capabilities[ATTR_MAX_COLOR_TEMP_KELVIN]
                if wrapped_light is not None and wrapped_light.capabilities is not None
                else None
            )

        self._attr_effect_list = (
            wrapped_light.capabilities[ATTR_EFFECT_LIST]
            if wrapped_light is not None
            and wrapped_light.capabilities is not None
            and ATTR_EFFECT_LIST in wrapped_light.capabilities
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

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn device on."""

        await self._add_state(
            PrioritizedState(
                self, kwargs, state=True, priority=MAX_PRIORITY, id=MANUAL_ID
            )
        )

    async def push_state(self, **kwargs: Any) -> None:
        """Push state."""
        await self._add_state(PrioritizedState(self, kwargs))

    async def pop_state(self, **kwargs: Any) -> None:
        """Pop state."""
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

    @override
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
        self._attr_color_temp_kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)

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

    @override
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Superlight from a config entry."""
    registry = er.async_get(hass)
    entity_id = er.async_validate_entity_id(
        registry, config_entry.options[CONF_ENTITY_ID]
    )

    async_add_entities(
        [Superlight(hass, config_entry.title, entity_id, config_entry.entry_id)]
    )
