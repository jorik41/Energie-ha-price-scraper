# Engie Gas Sensor

Home Assistant custom integration (HACS) to fetch Engie gas price data from a PDF and expose them as sensors.

## Installation

1. Copy the `custom_components/engie_gas` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration via the UI and provide the name and URL to the Engie PDF.

## Sensors

The integration creates the following sensors:
- Maandelijkse Prijs
- FL Zenne-Dijle Afname
- FL Zenne-Dijle Vergoeding
- Energiebijdrage
- Verbruik 0-12kWh
- Totaal (som van maandelijkse prijs, FL Zenne-Dijle afname en vergoeding, energiebijdrage en verbruik 0-12kWh)

## Update strategie

Om blokkades bij Engie te voorkomen probeert de integratie in de eerste vijf
dagen van een nieuwe maand maximaal één keer per dag de PDF op te halen. Zodra
de prijzen voor de nieuwe maand beschikbaar zijn, worden die waarden voor de
rest van de maand hergebruikt. Na de eerste week wordt het ophaalinterval
verruimd naar één verzoek per week totdat de volgende maand aanbreekt.

## Development

This repository is intended as a starting point for the Engie gas price sensor integration.
