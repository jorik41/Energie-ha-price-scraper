import logging
import requests
import io
import re
from datetime import datetime, timedelta

from pdfminer.high_level import extract_text
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME, CONF_URL

_LOGGER = logging.getLogger(__name__)
DOMAIN = "engie_gas"

# Houd de laatste opgehaalde waarden bij zodat we niet te vaak naar de PDF
# hoeven te vragen. In de eerste vijf dagen van een nieuwe maand proberen we
# dagelijks op nieuwe gegevens te controleren. Zodra de prijzen voor de huidige
# maand zijn opgehaald of de eerste week voorbij is, beperken we de verzoeken
# tot maximaal één keer per week totdat de maand verandert.
_CACHE = None
_LAST_FETCH_ATTEMPT = None
_LAST_SUCCESS_MONTH = None

# Home Assistant roept ``update`` standaard iedere 30 seconden aan. Door een
# scan interval van een dag te definiëren beperken we dit tot maximaal één
# aanroep per dag.
SCAN_INTERVAL = timedelta(days=1)


def parse_pdf(url):
    """Download de PDF, extraheer de tekst en parse de gewenste waarden.

    Om blokkades door te veel verzoeken te voorkomen wordt in de eerste vijf
    dagen van een nieuwe maand hooguit eenmaal per dag een poging gedaan om de
    PDF op te halen. Buiten deze periode proberen we slechts één keer per week.
    Zodra voor de huidige maand gegevens beschikbaar zijn, wordt de cache
    gebruikt totdat de maand verandert.

    Geeft een dictionary terug met de volgende keys:
      - maandelijkse_prijs
      - fluvius_zenne_dijle_afname
      - fluvius_zenne_dijle_vergoeding
      - energiebijdrage
      - verbruik_0_12000
      - totaal  (berekend als maandelijkse_prijs + fluvius_zenne_dijle_afname +
                 fluvius_zenne_dijle_vergoeding + energiebijdrage + verbruik_0_12000)
    """
    global _CACHE, _LAST_FETCH_ATTEMPT, _LAST_SUCCESS_MONTH

    now = datetime.utcnow()
    current_month = (now.year, now.month)

    # Als we al data voor de huidige maand hebben, gebruik deze dan.
    if _CACHE is not None and _LAST_SUCCESS_MONTH == current_month:
        return _CACHE

    # Bepaal het minimale interval tussen fetches: dagelijks in de eerste vijf
    # dagen van de maand, daarna maximaal wekelijks.
    min_interval = timedelta(days=1) if now.day <= 5 else timedelta(days=7)

    if _LAST_FETCH_ATTEMPT and (now - _LAST_FETCH_ATTEMPT) < min_interval:
        return _CACHE

    _LAST_FETCH_ATTEMPT = now

    result = {}
    try:
        response = requests.get(url)
        response.raise_for_status()
        pdf_bytes = response.content

        with io.BytesIO(pdf_bytes) as pdf_file:
            text = extract_text(pdf_file)

        if not text:
            _LOGGER.error("Geen tekst gevonden in de PDF.")
            return _CACHE

        _LOGGER.debug("Extracted text: %s", text)

        # Maandelijkse prijs: zoekt naar "Maandelijkse prijzen" gevolgd door een regel met getal
        m_price = re.search(r'Maandelijkse prijzen\s*\n\s*([\d,]+)', text)
        if m_price:
            try:
                result["maandelijkse_prijs"] = float(m_price.group(1).replace(',', '.'))
            except ValueError:
                _LOGGER.error("Kon de maandelijkse prijs niet omzetten: %s", m_price.group(1))
        else:
            _LOGGER.error("Geen maandelijkse prijs gevonden.")

        # FLUVIUS ZENNE-DIJLE: verwacht een regel als:
        # FLUVIUS ZENNE-DIJLE 16,66 2,391 88,46 0,955 598,01 0,616 18,56 0,165
        flz_match = re.search(
            r'FLUVIUS ZENNE-DIJLE\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+([\d,]+)\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+([\d,]+)',
            text)
        if flz_match:
            try:
                result["fluvius_zenne_dijle_afname"] = float(flz_match.group(1).replace(',', '.'))
                result["fluvius_zenne_dijle_vergoeding"] = float(flz_match.group(2).replace(',', '.'))
            except ValueError:
                _LOGGER.error("Kon de FLUVIUS ZENNE-DIJLE waarden niet omzetten: %s, %s",
                              flz_match.group(1), flz_match.group(2))
        else:
            _LOGGER.error("Geen waarden voor FLUVIUS ZENNE-DIJLE gevonden.")

        # Verwerk het toeslagen-blok: we zoeken naar het gedeelte na "Toeslagen (€cent/kWh)"
        toeslagen_match = re.search(r'Toeslagen\s*\(.*?\)(.*)', text, re.DOTALL)
        if toeslagen_match:
            block = toeslagen_match.group(1)
            lines = block.splitlines()
            # Verzamel alleen lijnen die volledig bestaan uit cijfers en komma's
            numbers_in_block = [line.strip() for line in lines if re.fullmatch(r'[\d,]+', line.strip())]
            _LOGGER.debug("Getallen in toeslagen-blok: %s", numbers_in_block)
            if len(numbers_in_block) >= 2:
                try:
                    result["energiebijdrage"] = float(numbers_in_block[0].replace(',', '.'))
                    result["verbruik_0_12000"] = float(numbers_in_block[1].replace(',', '.'))
                except ValueError:
                    _LOGGER.error("Fout bij het omzetten van getallen in toeslagen-blok: %s", numbers_in_block)
            else:
                _LOGGER.error("Niet genoeg getallen gevonden in toeslagen-blok voor Energiebijdrage en Verbruik tussen 0 & 12.000 kWh.")
        else:
            _LOGGER.error("Toeslagen-blok niet gevonden.")

        # Bereken totaal als alle vereiste waarden beschikbaar zijn
        required_keys = [
            "maandelijkse_prijs",
            "fluvius_zenne_dijle_afname",
            "fluvius_zenne_dijle_vergoeding",
            "energiebijdrage",
            "verbruik_0_12000",
        ]

        missing_keys = [key for key in required_keys if key not in result]

        if not missing_keys:
            result["totaal"] = sum(result[key] for key in required_keys)
        else:
            _LOGGER.error(
                "Niet alle waarden beschikbaar voor totaal berekening. Ontbrekend: %s",
                ", ".join(missing_keys),
            )

        # Alleen bij een wijziging werken we de cache bij en noteren we dat de
        # huidige maand succesvol is opgehaald. Zo proberen we dagelijks opnieuw
        # tot de PDF daadwerkelijk verandert.
        if result and result != _CACHE:
            _CACHE = result
            _LAST_SUCCESS_MONTH = current_month

        return _CACHE

    except Exception as e:
        _LOGGER.error("Fout bij ophalen of parsen van de PDF: %s", e)
        return _CACHE


class EngieGasSensor(SensorEntity):
    """Sensor voor een specifiek getal uit de Engie PDF."""

    def __init__(self, name, url, unique_id, sensor_type):
        """
        sensor_type moet één van de volgende zijn:
          - maandelijkse_prijs
          - fluvius_zenne_dijle_afname
          - fluvius_zenne_dijle_vergoeding
          - energiebijdrage
          - verbruik_0_12000
          - totaal
        """
        self._name = name
        self._url = url
        self._unique_id = unique_id + "_" + sensor_type
        self._sensor_type = sensor_type
        self._state = None

    @property
    def name(self):
        """Geef de sensor een duidelijke naam gebaseerd op het type."""
        names = {
            "maandelijkse_prijs": "Maandelijkse Prijs",
            "fluvius_zenne_dijle_afname": "FL Zenne-Dijle Afname",
            "fluvius_zenne_dijle_vergoeding": "FL Zenne-Dijle Vergoeding",
            "energiebijdrage": "Energiebijdrage",
            "verbruik_0_12000": "Verbruik 0-12kWh",
            "totaal": "Totaal"
        }
        return f"{self._name} {names.get(self._sensor_type, self._sensor_type)}"

    @property
    def state(self):
        """De huidige waarde van de sensor."""
        return self._state

    @property
    def unique_id(self):
        """Uniek ID zodat de sensor correct geregistreerd wordt."""
        return self._unique_id

    @property
    def device_info(self):
        """Koppel de sensor aan een apparaat zodat deze onder de integratie verschijnt."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._name,
            "manufacturer": "Engie",
            "model": "Gas Price PDF Sensor",
        }

    @property
    def state_class(self):
        """Geef aan dat het een meetwaarde betreft voor Historie."""
        return "measurement"

    @property
    def unit_of_measurement(self):
        """Bepaal de eenheid op basis van het sensor_type."""
        unit_mapping = {
            "maandelijkse_prijs": "€cent/kWh",
            "fluvius_zenne_dijle_afname": "€cent/kWh",
            "fluvius_zenne_dijle_vergoeding": "€cent/kWh",
            "energiebijdrage": "€cent/kWh",
            "verbruik_0_12000": "€cent/kWh",
            "totaal": "€cent/kWh",
        }
        return unit_mapping.get(self._sensor_type)

    def update(self):
        """Update de sensor door de PDF te downloaden en de gewenste waarden te parsen."""
        values = parse_pdf(self._url)
        if not values:
            return

        if self._sensor_type == "maandelijkse_prijs":
            self._state = values.get("maandelijkse_prijs")
        elif self._sensor_type == "fluvius_zenne_dijle_afname":
            self._state = values.get("fluvius_zenne_dijle_afname")
        elif self._sensor_type == "fluvius_zenne_dijle_vergoeding":
            self._state = values.get("fluvius_zenne_dijle_vergoeding")
        elif self._sensor_type == "energiebijdrage":
            self._state = values.get("energiebijdrage")
        elif self._sensor_type == "verbruik_0_12000":
            self._state = values.get("verbruik_0_12000")
        elif self._sensor_type == "totaal":
            self._state = values.get("totaal")
        else:
            _LOGGER.error("Onbekend sensor type: %s", self._sensor_type)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Stel de sensoren in vanuit een config entry."""
    name = config_entry.data.get(CONF_NAME, "Engie Prijzen")
    url = config_entry.data.get(CONF_URL)
    unique_id = config_entry.entry_id
    entities = [
        EngieGasSensor(name, url, unique_id, "maandelijkse_prijs"),
        EngieGasSensor(name, url, unique_id, "fluvius_zenne_dijle_afname"),
        EngieGasSensor(name, url, unique_id, "fluvius_zenne_dijle_vergoeding"),
        EngieGasSensor(name, url, unique_id, "energiebijdrage"),
        EngieGasSensor(name, url, unique_id, "verbruik_0_12000"),
        EngieGasSensor(name, url, unique_id, "totaal"),
    ]
    async_add_entities(entities, True)
