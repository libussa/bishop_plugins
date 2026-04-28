###
# Copyright (c) 2008,2012 Kevin Funk
# Copyright (c) 2014-2015 James Lu
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

from supybot.test import *
import json
from urllib import parse
from unittest.mock import patch
import supybot.utils as utils


def response(payload):
    return json.dumps(payload).encode("utf-8")


def recent_track_payload(artist="Artist & Co", track="Song + Tune"):
    return {
        "recenttracks": {
            "@attr": {"user": "krf"},
            "track": [{
                "artist": {"#text": artist},
                "name": track,
                "album": {"#text": "Album"},
            }],
        },
    }


class LastFMTestCase(PluginTestCase):
    plugins = ('LastFM',)

    def setUp(self):
        PluginTestCase.setUp(self)
        conf.supybot.plugins.LastFM.apiKey.setValue('test-api-key')
        conf.supybot.plugins.LastFM.youtubeApiKey.setValue('')
        conf.supybot.plugins.LastFM.fetchYouTubeLink.setValue(False)

    def lastfm_get_url(self, handlers):
        def get_url(url):
            query = parse.parse_qs(parse.urlparse(url).query)
            self.assertEqual(query["api_key"], ["test-api-key"])
            method = query["method"][0]
            return response(handlers[method](query))
        return get_url

    def testNowPlaying(self):
        def track_info(query):
            self.assertEqual(query["artist"], ["Artist & Co"])
            self.assertEqual(query["track"], ["Song + Tune"])
            return {"track": {"userplaycount": "4"}}

        handlers = {
            "user.getrecenttracks": lambda query: recent_track_payload(),
            "artist.getinfo": lambda query: {
                "artist": {
                    "tags": {
                        "tag": [
                            {"name": "indie"},
                            {"name": "seen live"},
                            {"name": "rock"},
                        ],
                    },
                },
            },
            "track.getInfo": track_info,
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "np krf",
                "Artist & Co \u2014 Song + Tune \u2014 indie, rock \u2014 4x")

    def testNowPlayingSurvivesOptionalMetadataErrors(self):
        handlers = {
            "user.getrecenttracks": lambda query: recent_track_payload(
                artist="Artist", track="Track"),
            "artist.getinfo": lambda query: {
                "error": 6,
                "message": "temporary tag failure",
            },
            "track.getInfo": lambda query: {
                "error": 6,
                "message": "temporary track failure",
            },
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse("np krf", "Artist \u2014 Track")

    def testNowPlayingReturnsLastfmApiErrorsToIrc(self):
        handlers = {
            "user.getrecenttracks": lambda query: {
                "error": 6,
                "message": "User not found",
            },
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            msg = self.assertError("np krf")

        self.assertIn("Last.fm error: User not found", msg.args[1])
        self.assertNotIn("administrator", msg.args[1].lower())

    def testNowPlayingReturnsTransportErrorsToIrc(self):
        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=utils.web.Error("timeout")):
            msg = self.assertError("np krf")

        self.assertIn("Last.fm is not responding right now", msg.args[1])
        self.assertNotIn("administrator", msg.args[1].lower())

    def testYoutubeLinkWithoutKeyDoesNotBreakNowPlaying(self):
        conf.supybot.plugins.LastFM.fetchYouTubeLink.setValue(True)
        handlers = {
            "user.getrecenttracks": lambda query: recent_track_payload(
                artist="Artist", track="Track"),
            "artist.getinfo": lambda query: {"artist": {"tags": {"tag": []}}},
            "track.getInfo": lambda query: {"track": {}},
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse("np krf", "Artist \u2014 Track")


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
