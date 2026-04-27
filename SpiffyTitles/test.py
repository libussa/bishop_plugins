###
# Copyright (c) 2015, butterscotchstallion
# All rights reserved.
#
#
###

from supybot.test import *


class SpiffyTitlesTestCase(ChannelPluginTestCase):
    plugins = ('SpiffyTitles',)

    def setUp(self):
        ChannelPluginTestCase.setUp(self)
        
        self.assertNotError('reload SpiffyTitles')

    def testGetsAllUrlsFromMessage(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        message = 'one https://example.com/a two http://example.org/b'

        self.assertEqual(plugin.get_urls_from_message(message),
                         ['https://example.com/a', 'http://example.org/b'])

    def testGetUrlFromMessageKeepsFirstUrlBehavior(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        message = 'one https://example.com/a two http://example.org/b'

        self.assertEqual(plugin.get_url_from_message(message),
                         'https://example.com/a')

    def testNumberedTitleResponse(self):
        plugin = self.irc.getCallback('SpiffyTitles')

        self.assertEqual(plugin.get_numbered_title_response(['^ First', 'Second']),
                         '[1] First | [2] Second')

    
# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
