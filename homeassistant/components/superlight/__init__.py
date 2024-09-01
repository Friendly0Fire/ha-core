"""Advanced virtual light."""

from __future__ import annotations

from collections.abc import Iterable
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    discovery_flow,
    entity_registry as er,
)
from homeassistant.helpers.event import async_track_entity_registry_updated_event
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

PLATFORMS = [Platform.LIGHT, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


@callback
def async_add_to_device(
    hass: HomeAssistant, entry: ConfigEntry, entity_id: str
) -> str | None:
    """Add our config entry to the tracked entity's device."""
    registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    device_id = None

    if (
        not (wrapped_light := registry.async_get(entity_id))
        or not (device_id := wrapped_light.device_id)
        or not (device_registry.async_get(device_id))
    ):
        return device_id

    device_registry.async_update_device(device_id, add_config_entry_id=entry.entry_id)

    return device_id


@callback
def async_trigger_discovery(
    hass: HomeAssistant,
    discovered_entity_ids: Iterable[str],
) -> None:
    """Trigger config flows for discovered devices."""

    for entity_id in discovered_entity_ids:
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_ENTITY_ID: entity_id},
        )


async def async_discover_devices(
    hass: HomeAssistant, entity_id: str | None
) -> Iterable[str]:
    """Discover available lights."""
    ereg = er.async_get(hass)

    async def _async_get_superlight_id(entity: er.RegistryEntry) -> str | None:
        if not entity.entity_id:
            return None
        superlight_entry = ereg.async_get(entity.entity_id)
        if superlight_entry is None or superlight_entry.domain != DOMAIN:
            return None
        return superlight_entry.entity_id

    if entity_id is not None:
        entity = ereg.async_get(entity_id)
        if (
            entity is not None
            and entity.domain == LIGHT_DOMAIN
            and entity.platform != DOMAIN
        ):
            superlight_id = await _async_get_superlight_id(entity)
            _LOGGER.debug("Detected new light %s", entity_id)
            if superlight_id is None:
                return [entity_id]
            _LOGGER.debug("New light %s already has superlight, skipping", entity_id)
        return []

    devices: Iterable[str] = []

    for eid, entity in ereg.entities.items():
        if entity.domain == LIGHT_DOMAIN and entity.platform != DOMAIN:
            _LOGGER.debug("Detected light %s", eid)
            if await _async_get_superlight_id(entity) is None:
                devices.append(eid)
            else:
                _LOGGER.debug("Light %s already has superlight", eid)

    return devices


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Superlight from a config entry."""
    registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    try:
        entity_id = er.async_validate_entity_id(registry, entry.options[CONF_ENTITY_ID])
    except vol.Invalid:
        # The entity is identified by an unknown entity registry ID
        _LOGGER.error(
            "Failed to setup superlight for unknown entity %s",
            entry.options[CONF_ENTITY_ID],
        )
        return False

    async def async_registry_updated(
        event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        """Handle entity registry update."""
        data = event.data
        if data["action"] == "remove":
            await hass.config_entries.async_remove(entry.entry_id)

        if data["action"] != "update":
            return

        if "entity_id" in data["changes"]:
            # Entity_id changed, reload the config entry
            await hass.config_entries.async_reload(entry.entry_id)

        if device_id and "device_id" in data["changes"]:
            # If the tracked light is no longer in the device, remove our config entry
            # from the device
            if (
                not (entity_entry := registry.async_get(data[CONF_ENTITY_ID]))
                or not device_registry.async_get(device_id)
                or entity_entry.device_id == device_id
            ):
                # No need to do any cleanup
                return

            device_registry.async_update_device(
                device_id, remove_config_entry_id=entry.entry_id
            )

    entry.async_on_unload(
        async_track_entity_registry_updated_event(
            hass, entity_id, async_registry_updated
        )
    )
    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))

    device_id = async_add_to_device(hass, entry, entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload a config entry.

    This will unhide the wrapped entity and restore assistant expose settings.
    """
    registry = er.async_get(hass)
    try:
        light_entity_id = er.async_validate_entity_id(
            registry, entry.options[CONF_ENTITY_ID]
        )
    except vol.Invalid:
        # The source entity has been removed from the entity registry
        return

    if not (light_entity_entry := registry.async_get(light_entity_id)):
        return

    # Unhide the wrapped entity
    if light_entity_entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
        registry.async_update_entity(light_entity_id, hidden_by=None)

    superlight_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    if not superlight_entries:
        return

    superlight_entry = superlight_entries[0]

    # Restore assistant expose settings
    expose_settings = exposed_entities.async_get_entity_settings(
        hass, superlight_entry.entity_id
    )
    for assistant, settings in expose_settings.items():
        if (should_expose := settings.get("should_expose")) is None:
            continue
        exposed_entities.async_expose_entity(
            hass, assistant, light_entity_id, should_expose
        )


async def async_setup(hass: HomeAssistant, hass_config: ConfigType) -> bool:
    """Set up Superlight."""

    async def _async_discovery(evt: Event) -> None:
        entity_id = None
        should_trigger_discovery = False
        if (
            evt.event_type == er.EVENT_ENTITY_REGISTRY_UPDATED
            and evt.data.get("action") == "create"
        ):
            should_trigger_discovery = True
            entity_id = evt.data.get("entity_id")
        elif evt.event_type == EVENT_HOMEASSISTANT_STARTED:
            should_trigger_discovery = True

        if should_trigger_discovery:
            async_trigger_discovery(hass, await async_discover_devices(hass, entity_id))

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_discovery)
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _async_discovery)

    return True
