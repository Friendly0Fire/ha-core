"""Superlight consts."""

from enum import StrEnum

from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.util.hass_dict import HassKey

from .light import Superlight

DOMAIN = "superlight"
ATTR_PRIORITY = "priority"
ATTR_TURN_ON = "turn_on"
ATTR_UNLATCH = "unlatch"

DATA_COMPONENT: HassKey[EntityComponent[Superlight]] = HassKey(DOMAIN)


class SuperlightService(StrEnum):
    """Store keys for Superlight services."""

    PUSH_STATE = "push_state"
    POP_STATE = "pop_state"
