###
# Copyright (c) 2006, Ilya Kuznetsov
# Copyright (c) 2008,2012 Kevin Funk
# Copyright (c) 2014-2016 James Lu
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

from __future__ import unicode_literals
import supybot.utils as utils
from supybot.commands import *
import supybot.conf as conf
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.world as world
import supybot.log as log
import supybot.ircdb as ircdb

from collections import Counter
import json
from datetime import datetime
import pickle
import humanize
from urllib import parse
from apiclient.discovery import build
from apiclient.errors import HttpError
import logging

logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

class LastFMDB():
    """
    Holds the database LastFM IDs of all known LastFM IDs.

    This stores users by their bot account first, falling back to their
    ident@host if they are not logged in.
    """

    def __init__(self, filename):
        """
        Loads the existing database, creating a new one in memory if none
        exists.
        """
        self.filename = filename
        self.flush_enabled = True
        self.db = {}
        try:
            with open(self.filename, 'rb') as f:
                db = pickle.load(f)
            if not isinstance(db, dict):
                raise ValueError("database did not contain a dict")
            self.db = db
        except FileNotFoundError:
            log.debug('LastFM: database does not exist yet, creating a new one')
        except (EOFError, pickle.PickleError, AttributeError, TypeError,
                ValueError, OSError) as e:
            self.flush_enabled = False
            log.warning('LastFM: unable to load database %s; keeping it '
                        'untouched: %s', self.filename, e)

    def flush(self):
        """Exports the database to a file."""
        if not self.flush_enabled:
            return
        try:
            with open(self.filename, 'wb') as f:
                pickle.dump(self.db, f, 2)
        except Exception as e:
            log.warning('LastFM: Unable to write database: %s', e)

    def set(self, prefix, newId):
        """Sets a user ID given the user's prefix."""

        try:  # Try to first look up the caller as a bot account.
            userobj = ircdb.users.getUser(prefix)
        except KeyError:  # If that fails, store them by nick@host.
            user = prefix.split('!', 1)[1]
        else:
            user = userobj.name

        self.db[user] = newId

    def get(self, prefix):
        """Gets a user ID given the user's prefix."""

        try:  # Try to first look up the caller as a bot account.
            userobj = ircdb.users.getUser(prefix)
        except KeyError:  # If that fails, store them by nick@host.
            user = prefix.split('!', 1)[1]
        else:
            user = userobj.name

        # Automatically returns None if entry does not exist
        return self.db.get(user)


class LastFM(callbacks.Plugin):
    threaded = True
    duration_labels = {
            'overall' : 'since forever',
            '7day'    : 'for the last week',
            '1month'  : 'for the last month',
            '3month'  : 'for the last 3 months',
            '6month'  : 'for the last 6 months',
            '12month' : 'for the last year'}

    def __init__(self, irc):
        self.__parent = super(LastFM, self)
        self.__parent.__init__(irc)
        self.db = LastFMDB(filename)
        world.flushers.append(self.db.flush)

        # 2.0 API (see https://www.last.fm/api/intro)
        self.APIURL = "https://ws.audioscrobbler.com/2.0/?"
        self.youtube = None
        self.youtube_api_key = None
        self.youtube_disabled_api_key = None

    def die(self):
        world.flushers.remove(self.db.flush)
        self.db.flush()
        self.__parent.die()

    def get_apiKey(self, irc):
        apiKey = self.registryValue("apiKey")
        if not apiKey:
            irc.error("The API Key is not set. Please set it via "
                      "'config plugins.lastfm.apikey' and reload the plugin. "
                      "You can sign up for an API Key using "
                      "https://www.last.fm/api/account/create", Raise=True)

        return apiKey

    def lastfm_request(self, irc, method, quiet=False, **params):
        apiKey = self.get_apiKey(irc)
        request_params = dict(params)
        request_params.update({
            'api_key': apiKey,
            'method': method,
            'format': 'json',
        })
        url = self.APIURL + parse.urlencode(request_params)
        safe_params = {k: v for k, v in request_params.items()
                       if k != 'api_key'}
        self.log.debug("LastFM.%s: params %r", method, safe_params)

        try:
            raw = utils.web.getUrl(url).decode("utf-8")
        except utils.web.Error as e:
            return self.lastfm_error(
                irc, method, "Last.fm is not responding right now. Try again later.",
                e, quiet)
        except UnicodeDecodeError as e:
            return self.lastfm_error(
                irc, method, "Last.fm returned an invalid response. Try again later.",
                e, quiet)

        try:
            data = json.loads(raw)
        except ValueError as e:
            return self.lastfm_error(
                irc, method, "Last.fm returned an invalid response. Try again later.",
                e, quiet)

        if isinstance(data, dict) and data.get('error'):
            message = data.get('message') or 'unknown API error'
            return self.lastfm_error(
                irc, method, "Last.fm error: %s" % message, None, quiet)

        return data

    def lastfm_error(self, irc, method, user_message, exception=None, quiet=False):
        if exception is not None:
            self.log.warning("LastFM.%s failed: %s", method, exception)
        else:
            self.log.warning("LastFM.%s failed: %s", method, user_message)
        if quiet:
            return None
        irc.error(user_message, Raise=True)

    def malformed_lastfm_response(self, irc, method, quiet=False):
        return self.lastfm_error(
            irc, method, "Last.fm returned an unexpected response. Try again later.",
            None, quiet)

    def as_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def text_value(self, value):
        if isinstance(value, dict):
            value = value.get('#text', '')
        if value is None:
            return ''
        return str(value).strip()

    def get_artist_tags(self, artist, irc):
        data = self.lastfm_request(
            irc, 'artist.getinfo', quiet=True, artist=artist)
        if not data:
            return []

        try:
            tags = data['artist']['tags']['tag']
        except (KeyError, TypeError):
            self.malformed_lastfm_response(irc, 'artist.getinfo', quiet=True)
            return []

        return [tag['name'] for tag in self.as_list(tags)
                if isinstance(tag, dict) and tag.get('name')]

    def get_track_info(self, irc, user, artist, track):
        data = self.lastfm_request(
            irc, 'track.getInfo', quiet=True, user=user, artist=artist,
            track=track)
        if not data:
            return {}

        try:
            return data['track']
        except (KeyError, TypeError):
            self.malformed_lastfm_response(irc, 'track.getInfo', quiet=True)
            return {}

    def get_topartists(self, irc, user, duration):
        data = self.lastfm_request(
            irc, 'user.gettopartists', user=user, limit=10, period=duration)
        try:
            artist_data = data['topartists']['artist']
        except (KeyError, TypeError):
            self.malformed_lastfm_response(irc, 'user.gettopartists')

        artists = []
        for artist in self.as_list(artist_data):
            if not isinstance(artist, dict):
                continue
            name = artist.get('name')
            playcount = artist.get('playcount')
            if name and playcount:
                artists.append({'name': name, 'playcount' : playcount})

        return artists

    def get_recent_track(self, irc, user, quiet=False):
        data = self.lastfm_request(
            irc, 'user.getrecenttracks', quiet=quiet, user=user, limit=2)
        if not data:
            return None, None

        try:
            recent = data['recenttracks']
            user = recent['@attr']['user']
            tracks = self.as_list(recent.get('track'))
        except (KeyError, TypeError):
            self.malformed_lastfm_response(irc, 'user.getrecenttracks', quiet=quiet)
            return None, None

        if not tracks:
            if quiet:
                return None, user
            irc.error("%s doesn't seem to have listened to anything." % user,
                      Raise=True)

        trackdata = tracks[0]
        if not isinstance(trackdata, dict):
            self.malformed_lastfm_response(irc, 'user.getrecenttracks', quiet=quiet)
            return None, user

        return trackdata, user

    def get_youtube_client(self):
        youtubeApiKey = self.registryValue("youtubeApiKey")
        if not youtubeApiKey:
            self.disable_youtube(
                youtubeApiKey, "fetchYouTubeLink is enabled but youtubeApiKey is not set")
            return None

        if self.youtube_disabled_api_key == youtubeApiKey:
            return None

        if self.youtube is None or self.youtube_api_key != youtubeApiKey:
            try:
                self.youtube = build(
                    "youtube", "v3", developerKey=youtubeApiKey,
                    cache_discovery=False)
                self.youtube_api_key = youtubeApiKey
                self.youtube_disabled_api_key = None
            except Exception as e:
                self.disable_youtube(
                    youtubeApiKey, "unable to initialize YouTube API client: %s" % e)
        return self.youtube

    def disable_youtube(self, api_key, reason):
        if self.youtube_disabled_api_key != api_key:
            self.log.warning(
                "LastFM: disabling YouTube links for current API key: %s", reason)
        self.youtube = None
        self.youtube_api_key = None
        self.youtube_disabled_api_key = api_key

    def youtube_http_error(self, error):
        status = getattr(error.resp, 'status', 'unknown')
        reason = getattr(error, 'reason', None)
        if reason is None:
            reason = getattr(error.resp, 'reason', None)
        if reason is None:
            reason = 'HTTP error'
        return "HTTP %s: %s" % (status, reason)

    def is_permanent_youtube_error(self, error):
        status = getattr(error.resp, 'status', None)
        if status in (400, 401):
            return True

        if status != 403:
            return False

        error_text = self.youtube_http_error(error).lower()
        content = getattr(error, 'content', b'')
        if isinstance(content, bytes):
            content = content.decode('utf-8', 'replace')
        error_text += ' ' + str(content).lower()

        permanent_markers = (
            'api key not valid',
            'api key has an ip address restriction',
            'api key has referer restrictions',
            'accessnotconfigured',
            'api has not been used',
        )
        for marker in permanent_markers:
            if marker in error_text:
                return True
        return False

    def get_youtube_link(self, artist, track):
        youtube = self.get_youtube_client()
        if youtube is None:
            return ''
        youtubeApiKey = self.youtube_api_key

        try:
            search_response = youtube.search().list(
                q=f"{artist} {track}",
                part="id",
                maxResults=5,
                type="video"
            ).execute()
        except HttpError as e:
            error = self.youtube_http_error(e)
            if self.is_permanent_youtube_error(e):
                self.disable_youtube(youtubeApiKey, "YouTube API error %s" % error)
            else:
                self.log.warning("LastFM: YouTube API error %s", error)
            return ''
        except BrokenPipeError as e:
            self.log.warning("LastFM: YouTube API error: %s", e)
            return ''
        except Exception as e:
            self.log.warning("LastFM: YouTube API error: %s", e)
            return ''

        for item in search_response.get("items", []):
            id_info = item.get("id", {})
            if id_info.get("kind") == "youtube#video" and "videoId" in id_info:
                return f"https://youtu.be/{id_info['videoId']}"
        return ''

    def get_channel_user(self, irc, channel, nick):
        resolved = self.resolve_channel_user(irc, channel, nick)
        if resolved is None:
            return None
        return resolved[1]

    def resolve_channel_user(self, irc, channel, nick):
        if not irc.isChannel(channel):
            return None

        try:
            state = irc.state.channels[channel]
        except KeyError:
            return None

        channel_nick = None
        for candidate in state.users:
            if ircutils.strEqual(candidate, nick):
                channel_nick = candidate
                break
        if channel_nick is None:
            return None

        try:
            hostmask = irc.state.nickToHostmask(channel_nick)
        except KeyError:
            return None

        user = self.db.get(hostmask)
        if not user:
            return None
        return channel_nick, user

    def get_np_user(self, irc, msg, user):
        if user is None:
            user = self.db.get(msg.prefix)
            if not user:
                irc.error("use .set <LastFM username> first.", Raise=True)
            return user

        channel_user = self.get_channel_user(irc, msg.args[0], user)
        if channel_user:
            return channel_user
        return user

    def parse_user_duration(self, irc, tokens):
        if len(tokens) > 2:
            irc.error("Usage: [<nick|LastFM user>] [<duration>]", Raise=True)

        user = None
        duration = None
        for token in tokens:
            normalized = token.lower()
            if normalized in self.duration_labels:
                if duration is not None:
                    irc.error("Only one duration may be given.", Raise=True)
                duration = normalized
            else:
                if user is not None:
                    irc.error("Only one LastFM user may be given.", Raise=True)
                user = token

        return user, duration or '6month'

    def resolve_display_user(self, irc, msg, user):
        if user is None:
            user = self.db.get(msg.prefix)
            if user is None:
                irc.error("use .set <LastFM username> first.", Raise=True)
            return msg.nick, user

        resolved = self.resolve_channel_user(irc, msg.args[0], user)
        if resolved is not None:
            return resolved
        return user, user

    @wrap([optional("something")])
    def np(self, irc, msg, args, user):
        """[<user>]

        Announces the track currently being played by <user>. If <user>
        matches a registered nick in the current channel, uses that nick's
        LastFM user. Otherwise, treats <user> as a LastFM username. If <user>
        is not given, defaults to the LastFM user configured for your current
        nick.
        """
        user = self.get_np_user(irc, msg, user)

        trackdata, user = self.get_recent_track(irc, user)
        artist = self.text_value(trackdata.get("artist"))
        track = self.text_value(trackdata.get("name"))
        if not artist or not track:
            self.malformed_lastfm_response(irc, 'user.getrecenttracks')

        tags = self.get_artist_tags(artist, irc)
        tags = [tag for tag in tags if tag.lower() != 'seen live']
        tag_list = ', '.join(tags)

        data_track = self.get_track_info(irc, user, artist, track)
        playcount = self.text_value(data_track.get("userplaycount"))
        if playcount:
            playcount += "x"

        try:
            timestamp = int(trackdata["date"]["uts"])
            time = "%s" % humanize.naturaltime(
                datetime.now() - datetime.fromtimestamp(timestamp))
        except (KeyError, TypeError, ValueError):
            time = ""

        public_url = ''
        if self.registryValue("fetchYouTubeLink"):
            public_url = self.get_youtube_link(artist, track)

        response = [artist, track, tag_list, public_url, time, playcount]
        s = ' \u2014 '.join(filter(None, response))

        irc.reply(utils.str.normalizeWhitespace(s))

    @wrap
    def wp(self, irc, msg, args):
        """[]
        Announces the track currently being played by current channel users.
        """
        self.get_apiKey(irc)
        channel = msg.args[0]
        L = list(irc.state.channels[channel].users)
        wp_data = []

        for nick in L:
            user = self.get_channel_user(irc, channel, nick)
            if not user:
                continue

            trackdata, _ = self.get_recent_track(irc, user, quiet=True)
            if not trackdata or "date" in trackdata:
                continue

            artist = self.text_value(trackdata.get("artist"))
            track = self.text_value(trackdata.get("name"))
            if not artist or not track:
                self.malformed_lastfm_response(irc, 'user.getrecenttracks', quiet=True)
                continue

            nickquiet = nick[0] + u"\u2063" + nick[1:]
            wp_data.append({'nick': nickquiet, 'artist': artist, 'track': track})

        if not wp_data:
            s = "No one is playing anything right now."
            irc.reply(s, prefixNick=False)
        else:
            user_max_length = min(max(len(item['nick']) for item in wp_data), 25)
            artist_max_length = min(max(len(item['artist']) for item in wp_data), 40)
            for wp_user in wp_data:
                nick = wp_user['nick'].ljust(user_max_length)[:user_max_length]
                artist = wp_user['artist'].ljust(artist_max_length)[:artist_max_length]
                s = f"{nick}  {artist}  {wp_user['track']}"
                irc.reply(s, prefixNick=False)

    @wrap(["something"])
    def set(self, irc, msg, args, newId):
        """<user>

        Sets the LastFM username for the caller and saves it in a database.
        """

        self.db.set(msg.prefix, newId)
        irc.reply("you are now https://www.last.fm/user/%s" % newId)

    @wrap([any("something")])
    def topartists(self, irc, msg, args, query):
        """[<nick|LastFM user>] [<duration>]

        Reports the top 10 artists for the current user or the one specified.
        Duration: overall | 7day | 1month | 3month | 6month | 12month
        (default: 6 months). The user and duration may be given in either
        order.
        """
        user, duration = self.parse_user_duration(irc, query)
        nick, user = self.resolve_display_user(irc, msg, user)
        artists = self.get_topartists(irc, user, duration)
        if not artists:
            irc.reply("No top artists for %s" % nick)
            return

        outstr = "%s's top artists %s are:" % (
            nick, self.duration_labels[duration])
        for artist in artists:
            outstr = outstr + (" %s [%s]," % (ircutils.bold(artist['name']), artist['playcount']))

        outstr = outstr[:-1]

        irc.reply(outstr)

    @wrap([any("something")])
    def toptags(self, irc, msg, args, query):
        """[<nick|LastFM user>] [<duration>]

        Reports the top 10 tags for the user. Duration: overall | 7day |
        1month | 3month | 6month | 12month (default: 6 months). The user and
        duration may be given in either order.
        """

        user, duration = self.parse_user_duration(irc, query)
        nick, user = self.resolve_display_user(irc, msg, user)
        artists = self.get_topartists(irc, user, duration)
        tags = []
        for artist in artists:
            tags += self.get_artist_tags(artist['name'], irc)

        tag_counts = Counter(
            tag.lower() for tag in tags if tag.lower() != 'seen live')
        if not tag_counts:
            irc.reply('No top tags for {}'.format(nick))
            return

        outstr = "{nick}'s top tags {duration} are:".format(
            nick=nick, duration=self.duration_labels[duration])
        counts = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))
        for tag, count in counts[:10]:
            outstr += ' {tag} [{count}],'.format(tag=tag.title(), count=count)
        outstr = outstr[:-1]

        irc.reply(outstr)

filename = conf.supybot.directories.data.dirize("LastFM.db")

Class = LastFM
