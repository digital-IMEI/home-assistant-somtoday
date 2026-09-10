"""Constants for the Somtoday integration."""

from datetime import timedelta

DOMAIN = "somtoday"

AUTH_BASE_URL = "https://somtoday.nl"
ORGANIZATIONS_URL = "https://servers.somtoday.nl/organisaties.json"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/oauth2/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/oauth2/token"

CLIENT_ID = "D50E0C06-32D1-4B41-A137-A9A850C892C2"
REDIRECT_URI = "somtodayleerling://oauth/callback"

CONF_ORGANIZATION = "organization"
CONF_PROVIDER = "provider"
CONF_TOKEN = "token"

UPDATE_INTERVAL = timedelta(minutes=15)
SCHEDULE_DAYS = 14

