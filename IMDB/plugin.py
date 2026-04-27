###
# Copyright (c) 2015, butterscotchstallion
# All rights reserved.
#
#
###
import sys
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.ircmsgs as ircmsgs
import supybot.callbacks as callbacks
import requests
import json
import re


try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('IMDB')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x

class IMDB(callbacks.Plugin):
    """Queries IMDb suggestions for information about IMDB titles"""
    threaded = True

    def imdb(self, irc, msg, args, query):
        """
        Queries IMDb suggestions for query
        """
        suggestion_query = self.get_suggestion_query(query)
        channel = msg.args[0]
        result = None

        if not suggestion_query:
            irc.error(self.registryValue("noResultsMessage"))
            return

        suggestion_url = "https://v3.sg.media-imdb.com/suggestion/%s/%s.json" % (
            suggestion_query[0], suggestion_query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.60 Safari/537.36"
        }
        
        self.log.info("IMDB: requesting %s" % suggestion_url)
        
        try:
            request = requests.get(suggestion_url, timeout=10, headers=headers)
            
            if request.status_code == requests.codes.ok:
                response = json.loads(request.text)
                items = response.get("d", [])

                if items:
                    result = self.format_result(items[0])
            else:
                self.log.error("IMDB suggestion API %s - %s" %
                               (request.status_code, request.text))
        
        except requests.exceptions.Timeout as e:
            self.log.error("IMDB Timeout: %s" % (str(e)))
        except requests.exceptions.ConnectionError as e:
            self.log.error("IMDB ConnectionError: %s" % (str(e)))
        except requests.exceptions.HTTPError as e:
            self.log.error("IMDB HTTPError: %s" % (str(e)))
        finally:
            if result is not None:
                irc.sendMsg(ircmsgs.privmsg(channel, result))
            else:
                irc.error(self.registryValue("noResultsMessage"))
    
    imdb = wrap(imdb, ['text'])

    def get_suggestion_query(self, query):
        query = query.strip().lower()
        query = re.sub(r"[^a-z0-9]+", "_", query)

        return query.strip("_")

    def format_result(self, item):
        imdb_template = self.registryValue("template")
        replacements = {
            "$title": item.get("l", ""),
            "$year": str(item.get("y", "")),
            "$type": item.get("q", ""),
            "$cast": item.get("s", ""),
            "$imdbID": item.get("id", ""),
            "$country": "",
            "$director": "",
            "$plot": "",
            "$imdbRating": "",
            "$tomatoMeter": "",
            "$metascore": "",
        }

        for variable, value in replacements.items():
            imdb_template = imdb_template.replace(variable, value)

        return imdb_template
        
Class = IMDB


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
