from homeassistant import config_entries
import voluptuous as vol
from homeassistant.const import CONF_NAME, CONF_URL

DOMAIN = "engie_gas"


class EngieGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow voor de Engie Gas integratie."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Initialiseer de config flow via de UI."""
        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="Engie Prijzen"): str,
            vol.Required(CONF_URL): str,
        })
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=data_schema)
