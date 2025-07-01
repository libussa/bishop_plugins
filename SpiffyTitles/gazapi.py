"""
Generic API to be used with Gazelle sites.
Authentication is done via an API token.
Example *gazelle.conf* section for token auth::
    [redacted]
    url = https://redacted.site
    api_token = YOUR_TOKEN_HERE
"""
import configparser
import requests
from typing import Optional, Dict, Any


class LoginException(Exception):
    """Raised when form‑login fails."""


class RequestException(Exception):
    """Raised when *ajax.php* returns anything but `{status: 'success'}`."""


class GazAPI:
    """Simple helper around the Gazelle JSON API.
    Authentication is done via an API token.
    """

    def __init__(self, config_file: str, site: str):
        cfg = configparser.ConfigParser()
        if not cfg.read(config_file):
            raise FileNotFoundError(
                f"Unable to read configuration file: {config_file}"
            )

        if site not in cfg:
            raise ValueError(f"Site '{site}' missing from configuration file")

        section = cfg[site]
        self.site_url: str = section["url"].rstrip("/")

        self.api_token: Optional[str] = section.get("api_token")
        if not self.api_token:
            raise LoginException(f"api_token missing from '{site}' section")

    def request(self, action: str, **kwargs: Any):
        """Perform a JSON request to `/ajax.php`."""
        ajax_url = f"{self.site_url}/ajax.php"
        params = {"action": action, **kwargs}
        headers = {"Authorization": self.api_token}

        response = requests.get(
            ajax_url, params=params, headers=headers, allow_redirects=False, timeout=30
        )
        try:
            payload = response.json()
        except ValueError as err:
            raise RequestException("Invalid JSON in ajax response") from err

        if payload.get("status") != "success":
            raise RequestException(
                f"Gazelle API call '{action}' failed: {payload.get('status')}"
            )
        return payload["response"]
