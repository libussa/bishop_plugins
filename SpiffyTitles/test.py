###
# Copyright (c) 2015, butterscotchstallion
# All rights reserved.
#
#
###

from supybot.test import *
import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse


def response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload))


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

    def testDefaultHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        html = '<html><head><title>Example title</title></head></html>'

        with patch.object(plugin, 'get_source_by_url',
                          return_value=(html, False, None)):
            self.assertEqual(plugin.handler_default('https://example.com', self.channel),
                             '^ Example title')

    def testYoutubeHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.youtubeDeveloperKey.setValue('test-key')
        payload = {
            'pageInfo': {'totalResults': 1},
            'items': [{
                'snippet': {
                    'title': 'Video title',
                    'channelTitle': 'Channel name',
                },
                'statistics': {
                    'viewCount': '1234',
                    'likeCount': '12',
                    'favoriteCount': '0',
                    'commentCount': '3',
                },
                'contentDetails': {'duration': 'PT1M05S'},
            }],
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_youtube(
                'https://www.youtube.com/watch?v=abc12345678&t=65',
                urlparse('https://www.youtube.com/watch?v=abc12345678').netloc,
                self.channel)

        self.assertIn('Video title', title)
        self.assertIn('@ 01:05', title)
        self.assertIn('01:05', title)
        self.assertIn('Views: 1,234', title)

    def testDailymotionHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = {
            'id': 'x7abc',
            'title': 'Daily title',
            'owner.screenname': 'daily-user',
            'duration': 65,
            'views_total': 1234,
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_dailymotion(
                'https://www.dailymotion.com/video/x7abc_slug',
                urlparse('https://www.dailymotion.com/video/x7abc_slug'),
                self.channel)

        self.assertEqual(title, '^ [daily-user] Daily title :: Duration: 01:05 :: 1,234 views')

    def testVimeoHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = [{
            'title': 'Vimeo title',
            'duration': 125,
            'stats_number_of_plays': 1234,
            'stats_number_of_comments': 5,
        }]

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_vimeo('https://vimeo.com/123456',
                                         'vimeo.com',
                                         self.channel)

        self.assertEqual(title, '^ Vimeo title :: Duration: 02:05 :: 1,234 plays :: 5 comments')

    def testCoubHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = {
            'not_safe_for_work': False,
            'channel': {'title': 'Coub channel'},
            'title': 'Coub title',
            'views_count': 1234,
            'likes_count': 12,
            'recoubs_count': 3,
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_coub('https://coub.com/view/abc',
                                        'coub.com',
                                        self.channel)

        self.assertEqual(title,
                         '^  [Coub channel] Coub title :: 1,234 views :: 12 likes :: 3 recoubs')

    def testImdbHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = {
            'Response': 'True',
            'Title': 'Movie title',
            'Year': '2020',
            'Country': 'FR',
            'imdbRating': '7.1',
            'Plot': 'Movie plot.',
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_imdb('https://www.imdb.com/title/tt1234567/',
                                        urlparse('https://www.imdb.com/title/tt1234567/'),
                                        self.channel)

        self.assertEqual(title, '^ Movie title (2020, FR) - Rating: 7.1 ::  Movie plot.')

    def testWikipediaHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = {
            'query': {
                'pages': {
                    '1': {'extract': 'Article extract (ignored) with enough text.'},
                },
            },
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_wikipedia('https://en.wikipedia.org/wiki/Article',
                                             'wikipedia.org',
                                             self.channel)

        self.assertEqual(title, '^ Article extract with enough text.')

    def testRedditThreadHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        payload = [{
            'data': {
                'children': [{
                    'data': {
                        'id': 'abc',
                        'created_utc': datetime.datetime.now().timestamp(),
                        'is_self': False,
                        'author': 'poster',
                        'subreddit': 'testing',
                        'url': 'https://example.com/item',
                        'title': 'Reddit title',
                        'domain': 'example.com',
                        'score': 42,
                        'upvote_ratio': 0.91,
                        'num_comments': 7,
                    },
                }],
            },
        }]

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_reddit(
                'https://www.reddit.com/r/testing/comments/abc/reddit_title/',
                'reddit.com',
                self.channel)

        self.assertIn('/r/testing :: Reddit title :: 42 points (91%)', title)
        self.assertIn('7 comments', title)
        self.assertIn('https://example.com/item (example.com)', title)

    def testImgurAlbumHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        plugin.imgur_client = SimpleNamespace(
            get_album=lambda album_id: SimpleNamespace(
                title='Album title',
                section='cats',
                views=1234,
                images_count=5,
                nsfw=False,
            )
        )

        title = plugin.handler_imgur_album('https://imgur.com/a/abc',
                                           urlparse('https://imgur.com/a/abc'),
                                           self.channel)

        self.assertIn('Album title', title)
        self.assertIn('5 images', title)
        self.assertIn('1,234 views', title)

    def testImgurHandlerDispatchesAlbumLinks(self):
        plugin = self.irc.getCallback('SpiffyTitles')

        with patch.object(plugin, 'handler_imgur_album', return_value='album title') as handler:
            title = plugin.handler_imgur('https://imgur.com/a/abc',
                                         urlparse('https://imgur.com/a/abc'),
                                         self.channel)

        self.assertEqual(title, 'album title')
        handler.assert_called_once()

    def testImgurImageHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        plugin.imgur_client = SimpleNamespace(
            get_image=lambda image_id: SimpleNamespace(
                title='Image title',
                type='image/jpeg',
                nsfw=False,
                width=640,
                height=480,
                views=1234,
                size=2048,
                section='cats',
            )
        )

        title = plugin.handler_imgur_image('https://i.imgur.com/abc.jpg',
                                           urlparse('https://i.imgur.com/abc.jpg'),
                                           self.channel)

        self.assertIn('Image title', title)
        self.assertIn('image/jpeg 640x480 2.0KiB', title)
        self.assertIn('1,234 views', title)

    def testGazelleHandlers(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        api = SimpleNamespace(request=lambda **args: {
            'group': {
                'categoryName': 'Movies',
                'name': 'Gazelle title',
            },
        })
        plugin.api_red = api
        plugin.api_apl = api

        self.assertEqual(plugin.handler_redacted(
            'https://redacted.sh/torrents.php?id=123',
            urlparse('https://redacted.sh/torrents.php?id=123'),
            self.channel),
            '^ Gazelle title')
        self.assertEqual(plugin.handler_apl(
            'https://orpheus.network/torrents.php?id=123',
            urlparse('https://orpheus.network/torrents.php?id=123'),
            self.channel),
            '^ Gazelle title')

    
# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
