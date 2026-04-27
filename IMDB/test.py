###
# Copyright (c) 2015, butterscotchstallion
# All rights reserved.
#
#
###

from supybot.test import *
import json
from types import SimpleNamespace
from unittest.mock import patch


def response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload))


class IMDBTestCase(PluginTestCase):
    plugins = ('IMDB',)

    def testImdbSearch(self):
        payload = {
            'd': [{
                'id': 'tt0111161',
                'l': 'The Shawshank Redemption',
                'q': 'feature',
                's': 'Tim Robbins, Morgan Freeman',
                'y': 1994,
            }],
        }

        with patch('IMDB.plugin.requests.get', return_value=response(payload)):
            self.assertResponse(
                'imdb shawshank',
                'The Shawshank Redemption (1994) - feature :: '
                'Tim Robbins, Morgan Freeman :: '
                'https://www.imdb.com/title/tt0111161/')


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
