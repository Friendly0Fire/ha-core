"""Services for the Superlight integration."""

from homeassistant.core import HomeAssistant, callback

from .const import DATA_COMPONENT, SuperlightService


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register."""
    component = hass.data[DATA_COMPONENT]

    component.async_register_entity_service(
        SuperlightService.PUSH_STATE, None, "push_state"
    )
    component.async_register_entity_service(
        SuperlightService.POP_STATE, None, "pop_state"
    )
