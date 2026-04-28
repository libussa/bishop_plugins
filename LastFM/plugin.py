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
        self.db = {}
        try:
            with open(self.filename, 'rb') as f:
                self.db = pickle.load(f)
        except Exception as e:
            log.debug('LastFM: Unable to load database, creating '
                      'a new one: %s', e)

    def flush(self):
        """Exports the database to a file."""
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

    def __init__(self, irc):
        self.__parent = super(LastFM, self)
        self.__parent.__init__(irc)
        self.db = LastFMDB(filename)
        world.flushers.append(self.db.flush)

        # 2.0 API (see https://www.last.fm/api/intro)
        self.APIURL = "https://ws.audioscrobbler.com/2.0/?"
        self.youtube = None
        self.youtube_api_key = None

        # max length of fields for wp
        self.user_max_length = 16
        self.artist_max_length = 20

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

    def get_user(self, msg, user, irc):
        if user is not None:
            nick = user
            try:
                hostmask = irc.state.nickToHostmask(user)
            except KeyError:
                irc.error("%s is not registered with the bot" % user, Raise=True)
            userx = self.db.get(hostmask)
            if userx is None:
                irc.error("%s is not registered with the bot" % user, Raise=True)
            return nick, userx

        nick = msg.nick
        user = self.db.get(msg.prefix)
        if user is None:
            irc.error("use .set <LastFM username> first.", Raise=True)
        return nick, user

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

    def get_topartists(self, irc, msg, user, duration):
        valid_durations = ['overall', '7day', '1month', '3month', '6month', '12month']
        if duration is None:
            duration = '6month'
        elif duration not in valid_durations:
            irc.reply("Duration must be one of: overall | 7day | 1month | "
                      "3month | 6month | 12month. Using default.")
            duration = "6month"

        duration_dict = {
                'overall' : 'since forever',
                '7day'    : 'for the last week',
                '1month'  : 'for the last month',
                '3month'  : 'for the last 3 months',
                '6month'  : 'for the last 6 months',
                '12month' : 'for the last year'}

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

        return artists, duration, duration_dict

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
            self.log.warning("LastFM: fetchYouTubeLink is enabled but youtubeApiKey is not set")
            return None

        if self.youtube is None or self.youtube_api_key != youtubeApiKey:
            try:
                self.youtube = build(
                    "youtube", "v3", developerKey=youtubeApiKey,
                    cache_discovery=False)
                self.youtube_api_key = youtubeApiKey
            except Exception as e:
                self.log.warning("LastFM: unable to initialize YouTube API client: %s", e)
                self.youtube = None
                self.youtube_api_key = None
        return self.youtube

    def get_youtube_link(self, artist, track):
        youtube = self.get_youtube_client()
        if youtube is None:
            return ''

        try:
            search_response = youtube.search().list(
                q=f"{artist} {track}",
                part="id",
                maxResults=5,
                type="video"
            ).execute()
        except HttpError as e:
            self.log.warning("YouTube API error %s: %s", e.resp.status, e.content)
            return ''
        except BrokenPipeError as e:
            self.log.warning("YouTube API error: %s", e)
            return ''
        except Exception as e:
            self.log.warning("YouTube API error: %s", e)
            return ''

        for item in search_response.get("items", []):
            id_info = item.get("id", {})
            if id_info.get("kind") == "youtube#video" and "videoId" in id_info:
                return f"https://youtu.be/{id_info['videoId']}"
        return ''

    def get_channel_user(self, irc, channel, nick):
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

        return self.db.get(hostmask)

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
            hostmask = irc.state.nickToHostmask(nick)
            user = self.db.get(hostmask)
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
                s = f"{wp_user['nick'].ljust(user_max_length)[:user_max_length]}  {wp_user['artist'].ljust(artist_max_length)[:artist_max_length]}  {wp_user['track']}"
                irc.reply(s, prefixNick=False)

    @wrap(["something"])
    def set(self, irc, msg, args, newId):
        """<user>

        Sets the LastFM username for the caller and saves it in a database.
        """

        self.db.set(msg.prefix, newId)
        irc.reply("you are now https://www.last.fm/user/%s" % newId)

    @wrap([optional("something"), optional("something")])
    def topartists(self, irc, msg, args, duration, user):
        """[<duration>] [<user>]

        Reports the top 10 artists for the current user (or the one specified). Duration: overall | 7day | 1month | 3month | 6month | 12month (default: 6 months)
        """
        nick, user = self.get_user(msg, user, irc)
        artists, duration, duration_dict = self.get_topartists(irc, msg, user, duration)
        if not artists:
            irc.reply("No top artists for %s" % nick)
            return

        outstr = "%s's top artists %s are:" % (nick, duration_dict[duration])
        for artist in artists:
            outstr = outstr + (" %s [%s]," % (ircutils.bold(artist['name']), artist['playcount']))

        outstr = outstr[:-1]

        irc.reply(outstr)

    @wrap([optional("something"), optional("something")])
    def toptags(self, irc, msg, args, user, duration):
        """[<user>] [<duration>]

        Reports the top 10 tags for the user. Duration: overall | 7day | 1month | 3month | 6month | 12month (default: 6 months)
        """

        nick, user = self.get_user(msg, user, irc)
        artists, duration, duration_dict = self.get_topartists(irc, msg, user, duration)
        tags = []
        for artist in artists:
            tags += self.get_artist_tags(artist['name'], irc)

        tags = [tag.lower() for tag in tags if tag.lower() != 'seen live']
        if not tags:
            irc.reply('No top tags for {}'.format(nick))
            return

        counts = [[tag, tags.count(tag)] for tag in set(tags)]
        counts = sorted(counts, key=lambda x: -x[1])

        outstr = "{nick}'s top tags {duration} are:".format(nick=nick, duration=duration_dict[duration])
        for tag, count in counts[:10]:
            outstr += ' {tag} [{count}],'.format(tag=tag.title(), count=count)
        outstr = outstr[:-1]

        irc.reply(outstr)

filename = conf.supybot.directories.data.dirize("LastFM.db")

Class = LastFM
