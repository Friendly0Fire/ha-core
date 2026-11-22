"""Advanced virtual light."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_TARGET,
    CONF_ALIAS,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_STARTED,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry, discovery_flow
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN

from .light import Superlight
from .const import DOMAIN

PLATFORMS = [Platform.LIGHT]


@callback
def async_trigger_discovery(
    hass: HomeAssistant,
    discovered_devices: Iterable[Superlight],
) -> None:
    """Trigger config flows for discovered devices."""

    for device in discovered_devices:
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_TARGET: device.light_entity_id},
        )


async def async_discover_devices(hass: HomeAssistant) -> Iterable[Superlight]:
    """Discover available lights."""

    ereg = er.async_get(hass)

    devices: Iterable[Superlight] = []

    for id, entity in ereg.entities.items():
        if entity.domain == LIGHT_DOMAIN and entity.platform != DOMAIN:
            devices.append(Superlight(hass, id))

    return devices
    ##return [
    ##    Superlight(devices. underlying_id)
    ##    for underlying_id in hass.states.async_entity_ids("light")
    ##]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Superlight from a config entry."""

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_setup(hass: HomeAssistant, hass_config: ConfigType) -> bool:
    """Set up Superlight."""

    async def _async_discovery(*_: Any) -> None:
        async_trigger_discovery(hass, await async_discover_devices(hass))

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_discovery)

    return True
