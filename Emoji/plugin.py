###
# Copyright (c) 2017, libussa
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

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.ircmsgs as ircmsgs
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Emoji')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x
import emoji


class Emoji(callbacks.Plugin):
    """A plugin to deal with unicode Emojis"""
    def emoji(self, irc, msg, args, text):
        """<text>

         Returns the text with unicode emojis translated"""
        irc.reply(emoji.demojize(text))
    emoji = wrap(emoji, ['text'])

    def wat(self, irc, msg, args, nick):
        """<nick>

        Grabs the last line said by <nick> and returns it with emojis translated
        """
        chan = msg.args[0]
        selfCaller = False
        for m in reversed(irc.state.history):
            if m.command == 'PRIVMSG' and \
            ircutils.nickEqual(m.nick, nick) and \
            ircutils.strEqual(m.args[0], chan):
                if ircutils.nickEqual(nick, msg.nick) and selfCaller:
                    irc.reply(emoji.demojize(ircmsgs.prettyPrint(m)))
                    return
                elif ircutils.nickEqual(nick, msg.nick):
                    selfCaller = True
                    continue
                else:
                    irc.reply(emoji.demojize(ircmsgs.prettyPrint(m)))
                    return
        irc.error(_('I couldn\'t find a proper message to translate.'))
    wat = wrap(wat, ['seenNick'])

Class = Emoji


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
