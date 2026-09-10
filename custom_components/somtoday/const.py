"""Constants for the Somtoday integration."""

from datetime import timedelta

DOMAIN = "somtoday"

AUTH_BASE_URL = "https://somtoday.nl"
ORGANIZATIONS_URL = (
    "https://raw.githubusercontent.com/NONtoday/organisaties.json/"
    "refs/heads/main/organisaties.json"
)
AUTHORIZE_URL = f"{AUTH_BASE_URL}/oauth2/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/oauth2/token"

CLIENT_ID = "somtoday-leerling-native"
REDIRECT_URI = "somtoday://nl.topicus.somtoday.leerling/oauth/callback"

CONF_ORGANIZATION = "organization"
CONF_PROVIDER = "provider"
CONF_TOKEN = "token"

UPDATE_INTERVAL = timedelta(minutes=15)
SCHEDULE_DAYS = 14
