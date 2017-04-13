"""
Generic API to be used with Gazelle sites.

Logging in is done during instantiation which uses a single config file
for all sites.
"""
import configparser
import requests
from html import unescape

HEADERS = {
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_7_3) '
                  'AppleWebKit/535.11 (KHTML, like Gecko) Chrome/17.0.963.79 '
                  'Safari/535.11',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9 '
              ',*/*;q=0.8',
    'Accept-Encoding': 'gzip,deflate,sdch',
    'Accept-Language': 'en-US,en;q=0.8',
    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3'
    }


class LoginException(Exception):
    """
    Exception for when we hit an error logging in.

    (either bad page response, or invalid login credentials).
    """

    pass


class RequestException(Exception):
    """Exception when we hit a page error when making a request to ajax.php."""

    pass


class GazAPI(object):
    """
    API for various gazelle sites.

    Handles connections, authentication and simple ajax requests.
    """

    def __init__(self, config_file=None, site=None):
        """API constructor. Reads values from config file."""
        config = configparser.ConfigParser()
        config.read(config_file)
        if site in config:
            self.username = config[site]['username']
            self.password = config[site]['password']
            self.site_url = config[site]['url'].rstrip('/')
        else:
            raise ValueError("Site %s missing from configuration file" % site)

        self.session = None
        self.user_id = None
        self.authkey = None
        self.connect()

    def connect(self):
        """Connect to the tracker if not already logged in."""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        try:
            self.auth()
        except RequestException:
            self.login()
        else:
            self.login()

    def auth(self):
        """
        Test Authentication for a user against the "index" API.

        :raises: RequestException
        """
        account_info = self.request('index')
        self.user_id = account_info['id']
        self.authkey = account_info['authkey']

    def login(self):
        """
        Log the user into the tracker by going through the login page.

        Will not work with a captcha.
        :raises: LoginException
        """
        login_url = self.site_url + '/login.php'
        data = {'username': self.username, 'password': self.password}
        req = self.session.post(login_url, data=data)
        if req.status_code != 200:
            raise LoginException("Issue communicating with the server...")
        elif req.url == login_url:
            raise LoginException("Could not authenticate that \
                                                username/password combo")
        account_info = self.request('index')
        self.user_id = account_info['id']
        self.authkey = account_info['authkey']

    def request(self, action, **kwargs):
        """
        Make an AJAX request against the server to ajax.php.

        The available actions are located on WhatCD's github page for gazelle
        https://github.com/WhatCD/Gazelle/wiki/JSON-API-Documentation
        If the request fails for whatever reason, a RequestException is raised.
        :param action:
        :param kwargs:
        :return: dictionary representing json response
        :raises: RequestException
        """
        ajax_url = self.site_url + "/ajax.php"
        params = {'action': action}
        if self.authkey:
            params['auth'] = self.authkey
        params.update(kwargs)
        req = self.session.get(ajax_url, params=params, allow_redirects=False)
        try:
            json_response = unescape(req.json())
            if json_response['status'] != 'success':
                raise RequestException("Failed ajax request for " + action)
            return json_response['response']
        except ValueError:
            raise RequestException("Failed ajax request for " + action)
