"""Engie Gas integratie."""
import logging

_LOGGER = logging.getLogger(__name__)
DOMAIN = "engie_gas"


async def async_setup(hass, config):
    """Stel de integratie in vanuit YAML-configuratie (wordt niet gebruikt)."""
    _LOGGER.info("Engie Gas async_setup aangeroepen")
    return True


async def async_setup_entry(hass, entry):
    """Stel de integratie in vanuit een config entry."""
    _LOGGER.info("Engie Gas async_setup_entry aangeroepen")
    # Gebruik async_forward_entry_setups en geef de sensor als een lijst door
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass, entry):
    """Ruim de integratie op bij verwijderen van de config entry."""
    _LOGGER.info("Engie Gas async_unload_entry aangeroepen")
    return await hass.config_entries.async_forward_entry_unload(entry, "sensor")
