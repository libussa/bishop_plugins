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
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.world as world
import supybot.log as log
import supybot.ircdb as ircdb

import json
from datetime import datetime, timedelta
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

    def __init__(self, *args, **kwargs):
        """
        Loads the existing database, creating a new one in memory if none
        exists.
        """
        self.db = {}
        try:
            with open(filename, 'rb') as f:
               self.db = pickle.load(f)
        except Exception as e:
            log.debug('LastFM: Unable to load database, creating '
                      'a new one: %s', e)

    def flush(self):
        """Exports the database to a file."""
        try:
            with open(filename, 'wb') as f:
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
        """Sets a user ID given the user's prefix."""

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

        # 2.0 API (see http://www.lastfm.de/api/intro)
        self.APIURL = "http://ws.audioscrobbler.com/2.0/?"

        youtubeApiKey = self.get_youtubeApiKey(irc)
        self.youtube = build("youtube", "v3", developerKey=youtubeApiKey)

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
                      "http://www.last.fm/api/account/create", Raise=True)

        return apiKey

    def get_user(self, msg, user, irc):
        if user != None:
            nick = user
            try:
                # To find last.fm id in plugin database
                hostmask = irc.state.nickToHostmask(user)
                userx = self.db.get(hostmask)
                if userx != None:
                    user = userx
                else:
                    irc.reply("%s is not registered with the bot" % user)
                    irc.error("Bot only supports top artists for registered users", Raise=True)

            except:
                irc.reply("%s is not registered with the bot" % user)
                irc.error("Bot only supports top artist for registered users", Raise=True)
        else:
            nick = msg.nick
            user = self.db.get(msg.prefix)
        return nick, user


    def get_artist_tags(self, artist, irc):
        """
       Retourne les tags pour un artiste donné
       :param artist: Nom de l'artiste
       :param irc: irc
       :return: liste de tags
       """
        apiKey = self.get_apiKey(irc)
        url = "%sapi_key=%s&method=artist.getinfo&artist=%s&format=json" % (self.APIURL, apiKey, artist)
        tags = []

        try:
            f = utils.web.getUrl(url).decode("utf-8")
            data = json.loads(f)['artist']['tags']['tag']
            for tag in data:
                tags.append(tag['name'])
        except utils.web.Error:
            return None
        except KeyError:
            return None

        self.log.debug("LastFM.artist.getinfos: url %s", url)

        return tags


    def get_topartists(self, irc, msg, user, duration):
        apiKey = self.get_apiKey(irc)

        if duration in ['overall', '7day', '1month', '3month', '6month', '12month']:
            duration = duration
        else:
            duration = "6month"

        duration_dict = {
                'overall' : 'since forever',
                '7day'    : 'for the last week',
                '1month'  : 'for the last month',
                '3month'  : 'for the last 3 months',
                '6month'  : 'for the last 6 months',
                '12month' : 'for the last year'}

        # Get library information for user
        limit = 10 # specify artists to return per page (api supports max of 1000)
        # Get list of artists for each library
        url = "%sapi_key=%s&method=library.getArtists&user=%s&limit=%d&period=%s&format=json" % (self.APIURL, apiKey, user, limit, duration)
        self.log.debug("LastFM.library: url %s", url)

        try:
            f = utils.web.getUrl(url).decode("utf-8")
        except utils.web.Error:
            irc.error("Unknown LastFM user '%s'." % user, Raise=True)
        libraryList = json.loads(f)
        artists = []

        for artist in libraryList["artists"]["artist"]:
            artists.append({'name': artist['name'], 'playcount' : artist['playcount']})

        return artists, duration, duration_dict


    @wrap([optional("something")])
    def np(self, irc, msg, args, user):
        """[<user>]

        Announces the track currently being played by <user>. If <user>
        is not given, defaults to the LastFM user configured for your
        current nick.
        """
        apiKey = self.get_apiKey(irc)
        user = (user or self.db.get(msg.prefix))
        if not user:
            irc.error("use .set <LastFM username> first.", Raise=True)

        # see http://www.lastfm.de/api/show/user.getrecenttracks
        url = "%sapi_key=%s&method=user.getrecenttracks&user=%s&format=json&limit=2" \
                % (self.APIURL, apiKey, user)
        try:
            f = utils.web.getUrl(url).decode("utf-8")
        except utils.web.Error:
            irc.error("Unknown user %s." % user, Raise=True)
        self.log.debug("LastFM.nowPlaying: url %s", url)

        try:
            data = json.loads(f)["recenttracks"]
        except KeyError:
            irc.error("Unknown user %s." % user, Raise=True)

        user = data["@attr"]["user"]
        tracks = data["track"]

        # Work with only the first track.
        try:
            trackdata = tracks[0]
        except IndexError:
            irc.error("%s doesn't seem to have listened to anything." % user, Raise=True)

        artist = trackdata["artist"]["#text"].strip()  # Artist name
        track = trackdata["name"].strip()  # Track name
        # Album name (may or may not be present)
        album = trackdata["album"]["#text"].strip()
        tags = self.get_artist_tags(artist, irc)

        url_track = "%sapi_key=%s&method=track.getInfo&user=%s&artist=%s&track=%s&format=json" \
                % (self.APIURL, apiKey, user, parse.quote(artist), parse.quote(track))

        try:
            ans = utils.web.getUrl(url_track).decode("utf-8")
        except:
            pass

        try:
            data_track = json.loads(ans)["track"]
        except:
            pass

        try:
            playcount = data_track["userplaycount"].strip() + "x"
        except:
            playcount = ""

        try:
            tags.remove('seen live') # remove ce tag de merde
        except:
            pass

        try:
            tag_list = ', '.join(tags)
        except TypeError:
            tag_list = ''

        try:
            time = int(trackdata["date"]["uts"])  # Time of last listen
            # Format this using the preferred time format.
            tformat = conf.supybot.reply.format.time()
            time = "%s" % humanize.naturaltime(datetime.now() - datetime.fromtimestamp(time))
        except KeyError:  # Nothing given by the API?
            time = ""

        public_url = ''
        # Fetch a youtube link with google api
        if self.registryValue("fetchYouTubeLink"):

          try:
            search_response = self.youtube.search().list(
                                    q="%s %s" % (artist, track),
                                    part="id",
                                    maxResults=1,
                                    type="video"
                                ).execute()

            videoID = search_response["items"][0]["id"]["videoId"]
            public_url = "https://youtu.be/" + videoID
          except HttpError as e:
            print("An HTTP error %d occurred:\n%s" % (e.resp.status, e.content))
          except IndexError:
            print("No video found")

        response = [artist, track, tag_list, public_url, time, playcount]
        s = ' \u2014 '.join(filter(None, response))

        irc.reply(utils.str.normalizeWhitespace(s))


    @wrap
    def wp(self, irc, msg, args):
        """[]
        Announces the track currently being played by current channel users.
        """
        apiKey = self.get_apiKey(irc)
        channel = msg.args[0]
        L = list(irc.state.channels[channel].users)
        wp_data = []

        for nick in L:
            hostmask = irc.state.nickToHostmask(nick)
            user = self.db.get(hostmask)
            if user:
            # see http://www.lastfm.de/api/show/user.getrecenttracks
                url = "%sapi_key=%s&method=user.getrecenttracks&user=%s&format=json" % (self.APIURL, apiKey, user)
                try:
                    f = utils.web.getUrl(url).decode("utf-8")
                except utils.web.Error:
                    continue
#                    irc.error("Unknown user %s." % user, Raise=True)
                self.log.debug("LastFM.nowPlaying: url %s", url)

                try:
                    data = json.loads(f)["recenttracks"]
                except KeyError:
                    continue
#                    irc.error("Unknown user %s." % user, Raise=True)

                user = data["@attr"]["user"]
                tracks = data["track"]

                # Work with only the first track.
                try:
                    trackdata = tracks[0]
                except IndexError:
                    irc.error("%s doesn't seem to have listened to anything." % user, Raise=True)

                artist = trackdata["artist"]["#text"].strip()  # Artist name
                track = trackdata["name"].strip()  # Track name
                # Album name (may or may not be present)
                album = trackdata["album"]["#text"].strip()
                if album:
                    album = ircutils.bold("[%s]" % album)

                try:
                    time = int(trackdata["date"]["uts"])  # Time of last listen
                except KeyError:
                    # Nothing given by the API = now playing,
                    # this is what we want
                    nickquiet = nick[0] + u"\u2063" + nick[1:]
                    wp_data.append({'nick': nickquiet, 'artist': artist, 'track': track})

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
        irc.reply("you are now http://www.last.fm/user/%s" % newId)


    @wrap([optional("something"), optional("something")])
    def topartists(self, irc, msg, args, user, duration):
        """[<user>] [<duration>]

        Reports the top 10 artists for the user. Duration: overall | 7day | 1month | 3month | 6month | 12month (default: 6 months)
        """
        #irc.error("This command is not ready yet. Stay tuned!", Raise=True)
        nick, user = self.get_user(msg, user, irc)
        artists, duration, duration_dict = self.get_topartists(irc, msg, user, duration)
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
        # Get topartists and then get their tags
        artists, duration, duration_dict = self.get_topartists(irc, msg, user, duration)
        tags = []
        for artist in artists:
            try:
                tags += self.get_artist_tags(artist['name'], irc)
            except:
                pass

        if not tags:
            irc.reply('No top tags for {}'.format(nick))
            return

        # Count each tag's occurence
        tags = [tag.lower() for tag in tags]
        try:
            tags.remove('seen live') # remove ce tag de merde
        except:
            pass
        counts = [[tag, tags.count(tag)] for tag in set(tags)]
        counts = sorted(counts, key=lambda x: -x[1])

        # And build the string
        outstr = "{nick}'s top tags {duration} are:".format(nick=nick, duration=duration_dict[duration])
        for tag, count in counts[:10]:
            outstr += ' {tag} [{count}],'.format(tag=tag.title(), count=count)
        outstr = outstr[:-1]

        irc.reply(outstr)

filename = conf.supybot.directories.data.dirize("LastFM.db")

Class = LastFM
