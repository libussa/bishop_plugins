"""
Generic API to be used with Gazelle sites.

Now supports two authentication methods:
1. **API token** (preferred): simply put the token in the
   `Authorization` header for every request.
2. Legacy *username/password* form‑login (kept for backwards compatibility).

Example *gazelle.conf* section for token auth::

    [redacted]
    url = https://redacted.site
    api_token = YOUR_TOKEN_HERE

If *api_token* is present the username/password keys are ignored.
"""
import configparser
import requests
from typing import Optional, Dict, Any

HEADERS: Dict[str, str] = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.8",
    "Accept-Charset": "utf-8, ISO-8859-1;q=0.7,*;q=0.3",
}


class LoginException(Exception):
    """Raised when form‑login fails."""


class RequestException(Exception):
    """Raised when *ajax.php* returns anything but `{status: 'success'}`."""


class GazAPI:
    """Simple helper around the Gazelle JSON API.

    Two mutually‑exclusive authentication flows are supported:

    * **Token‑based** – If the *gazelle.conf* stanza contains
      `api_token`, that token will be sent in an `Authorization` header
      for *every* request. No further login is performed.
    * **Form‑login** – Fallback when `api_token` is absent. Performs the
      traditional POST to `/login.php`, then uses the returned cookies.
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

        # Preferred auth method – API token.
        self.api_token: Optional[str] = section.get("api_token")

        # Legacy creds (only used when no token present)
        self.username: Optional[str] = section.get("username")
        self.password: Optional[str] = section.get("password")

        self.session: Optional[requests.Session] = None
        self.user_id: Optional[int] = None
        self.authkey: Optional[str] = None  # Only relevant after form‑login

        self.connect()

    # ---------------------------------------------------------------------
    # Connection / authentication helpers
    # ---------------------------------------------------------------------
    def _set_default_headers(self) -> None:
        """Apply *static* headers + optional token to the current session."""
        self.session.headers.update(HEADERS)
        if self.api_token:
            # Gazelle expects raw token, without schemes like "Bearer "
            self.session.headers.update({"Authorization": self.api_token})

    def connect(self) -> None:
        """Open an HTTP session and authenticate if necessary."""
        self.session = requests.Session()
        self._set_default_headers()

        if self.api_token:
            # Token auth needs no further handshake.
            return

        # Fallback to legacy username/password login.
        if not (self.username and self.password):
            raise LoginException(
                "No 'api_token' found and username/password missing"
            )
        self._login_with_form()

    def _login_with_form(self) -> None:
        """Perform the classic POST-login flow for sites without token."""
        login_url = f"{self.site_url}/login.php"
        data = {"username": self.username, "password": self.password}
        resp = self.session.post(login_url, data=data, allow_redirects=True)

        if resp.status_code != 200:
            raise LoginException(f"HTTP {resp.status_code} during login")
        if resp.url.rstrip("/") == login_url.rstrip("/"):
            raise LoginException("Invalid username/password combination")

        # Acquire user_id + authkey – some endpoints still want them.
        try:
            account_info = self.request("index")
        except RequestException as exc:
            raise LoginException("Login succeeded but index request failed") from exc

        self.user_id = account_info.get("id")
        self.authkey = account_info.get("authkey")

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def request(self, action: str, **kwargs: Any):
        """Perform a JSON request to `/ajax.php`.

        The function automatically adds the `Authorization` header (token) or
        the `auth` query param (legacy flow) where appropriate.
        """
        ajax_url = f"{self.site_url}/ajax.php"
        params = {"action": action, **kwargs}
        if self.authkey:
            params["auth"] = self.authkey

        response = self.session.get(
            ajax_url, params=params, allow_redirects=False, timeout=30
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
