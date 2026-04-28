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
import os
import tempfile
from urllib import parse
from unittest.mock import patch
from apiclient.errors import HttpError
from LastFM.plugin import LastFMDB
import supybot.irclib as irclib
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


def topartists_payload(*artists):
    return {
        "topartists": {
            "artist": [
                {"name": name, "playcount": str(playcount)}
                for name, playcount in artists
            ],
        },
    }


class FakeHttpResponse(dict):
    def __init__(self, status=403, reason="Forbidden"):
        super().__init__()
        self.status = status
        self.reason = reason


class FailingYouTube:
    def __init__(self, counter, error):
        self.counter = counter
        self.error = error

    def search(self):
        return self

    def list(self, **kwargs):
        return self

    def execute(self):
        self.counter["execute"] += 1
        raise self.error


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

    def add_channel_user(self, channel, nick, lastfm_user=None):
        state = self.irc.state.channels.setdefault(
            channel, irclib.ChannelState())
        state.addUser(nick)
        hostmask = "%s!user@example.invalid" % nick
        self.irc.state.nicksToHostmasks[nick] = hostmask
        if lastfm_user is not None:
            plugin = self.irc.getCallback('LastFM')
            plugin.db.set(hostmask, lastfm_user)

    def set_lastfm_user(self, prefix, lastfm_user):
        plugin = self.irc.getCallback('LastFM')
        plugin.db.set(prefix, lastfm_user)

    def testDatabaseCorruptionIsNotOverwritten(self):
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(b'not a pickle')

            db = LastFMDB(path)
            self.assertEqual(db.db, {})
            self.assertFalse(db.flush_enabled)
            db.db["user"] = "lastfm-user"
            db.flush()

            with open(path, 'rb') as f:
                self.assertEqual(f.read(), b'not a pickle')
        finally:
            os.remove(path)

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

    def testNowPlayingResolvesRegisteredChannelNick(self):
        self.add_channel_user("#test", "Alice", "alice_lfm")

        def recent_tracks(query):
            self.assertEqual(query["user"], ["alice_lfm"])
            return recent_track_payload(artist="Mapped Artist", track="Mapped Track")

        handlers = {
            "user.getrecenttracks": recent_tracks,
            "artist.getinfo": lambda query: {"artist": {"tags": {"tag": []}}},
            "track.getInfo": lambda query: {"track": {}},
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "@np Alice", "test: Mapped Artist \u2014 Mapped Track",
                to="#test")

    def testNowPlayingFallsBackToLastfmUserWhenChannelNickIsUnregistered(self):
        self.add_channel_user("#test", "Alice")

        def recent_tracks(query):
            self.assertEqual(query["user"], ["Alice"])
            return recent_track_payload(artist="Raw Artist", track="Raw Track")

        handlers = {
            "user.getrecenttracks": recent_tracks,
            "artist.getinfo": lambda query: {"artist": {"tags": {"tag": []}}},
            "track.getInfo": lambda query: {"track": {}},
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse("@np Alice", "test: Raw Artist \u2014 Raw Track",
                                to="#test")

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

    def testYoutubeKeyRestrictionDisablesFurtherYoutubeLookups(self):
        conf.supybot.plugins.LastFM.fetchYouTubeLink.setValue(True)
        conf.supybot.plugins.LastFM.youtubeApiKey.setValue('bad-key')
        counter = {"execute": 0}
        error = HttpError(
            FakeHttpResponse(
                reason="The provided API key has an IP address restriction."),
            b'{"error": {"status": "PERMISSION_DENIED"}}')
        handlers = {
            "user.getrecenttracks": lambda query: recent_track_payload(
                artist="Artist", track="Track"),
            "artist.getinfo": lambda query: {"artist": {"tags": {"tag": []}}},
            "track.getInfo": lambda query: {"track": {}},
        }

        with patch('LastFM.plugin.build',
                   return_value=FailingYouTube(counter, error)):
            with patch('LastFM.plugin.utils.web.getUrl',
                       side_effect=self.lastfm_get_url(handlers)):
                self.assertResponse("np krf", "Artist \u2014 Track")
                self.assertResponse("np krf", "Artist \u2014 Track")

        self.assertEqual(counter["execute"], 1)

    def testYoutubeTransientHttpErrorDoesNotDisableFurtherLookups(self):
        conf.supybot.plugins.LastFM.fetchYouTubeLink.setValue(True)
        conf.supybot.plugins.LastFM.youtubeApiKey.setValue('test-youtube-key')
        counter = {"execute": 0}
        error = HttpError(
            FakeHttpResponse(status=503, reason="Service Unavailable"),
            b'{"error": {"status": "UNAVAILABLE"}}')
        handlers = {
            "user.getrecenttracks": lambda query: recent_track_payload(
                artist="Artist", track="Track"),
            "artist.getinfo": lambda query: {"artist": {"tags": {"tag": []}}},
            "track.getInfo": lambda query: {"track": {}},
        }

        with patch('LastFM.plugin.build',
                   return_value=FailingYouTube(counter, error)):
            with patch('LastFM.plugin.utils.web.getUrl',
                       side_effect=self.lastfm_get_url(handlers)):
                self.assertResponse("np krf", "Artist \u2014 Track")
                self.assertResponse("np krf", "Artist \u2014 Track")

        self.assertEqual(counter["execute"], 2)

    def testWhoPlayingSkipsUsersWithoutHostmasks(self):
        state = self.irc.state.channels.setdefault(
            "#test", irclib.ChannelState())
        state.addUser("Ghost")

        self.assertResponse("@wp", "No one is playing anything right now.",
                            to="#test")

    def testTopartistsUsesCurrentUserByDefault(self):
        self.set_lastfm_user(self.prefix, "caller_lfm")

        def topartists(query):
            self.assertEqual(query["user"], ["caller_lfm"])
            self.assertEqual(query["period"], ["6month"])
            return topartists_payload(("Rocker", 9))

        handlers = {"user.gettopartists": topartists}

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "topartists",
                "test's top artists for the last 6 months are: "
                "\x02Rocker\x02 [9]")

    def testTopartistsResolvesRegisteredChannelNick(self):
        self.add_channel_user("#test", "Alice", "alice_lfm")

        def topartists(query):
            self.assertEqual(query["user"], ["alice_lfm"])
            self.assertEqual(query["period"], ["7day"])
            return topartists_payload(("Rocker", 9))

        handlers = {"user.gettopartists": topartists}

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "@topartists Alice 7day",
                "test: Alice's top artists for the last week are: "
                "\x02Rocker\x02 [9]",
                to="#test")

    def testTopartistsAcceptsDurationBeforeUser(self):
        self.add_channel_user("#test", "Alice", "alice_lfm")

        def topartists(query):
            self.assertEqual(query["user"], ["alice_lfm"])
            self.assertEqual(query["period"], ["7day"])
            return topartists_payload(("Rocker", 9))

        handlers = {"user.gettopartists": topartists}

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "@topartists 7day Alice",
                "test: Alice's top artists for the last week are: "
                "\x02Rocker\x02 [9]",
                to="#test")

    def testToptagsResolvesRegisteredChannelNick(self):
        self.add_channel_user("#test", "Alice", "alice_lfm")

        def topartists(query):
            self.assertEqual(query["user"], ["alice_lfm"])
            self.assertEqual(query["period"], ["7day"])
            return topartists_payload(("Artist A", 3), ("Artist B", 2))

        def artist_info(query):
            tags = {
                "Artist A": [{"name": "indie"}, {"name": "seen live"}],
                "Artist B": [{"name": "indie"}, {"name": "rock"}],
            }
            return {"artist": {"tags": {"tag": tags[query["artist"][0]]}}}

        handlers = {
            "user.gettopartists": topartists,
            "artist.getinfo": artist_info,
        }

        with patch('LastFM.plugin.utils.web.getUrl',
                   side_effect=self.lastfm_get_url(handlers)):
            self.assertResponse(
                "@toptags Alice 7day",
                "test: Alice's top tags for the last week are: "
                "Indie [2], Rock [1]",
                to="#test")

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
