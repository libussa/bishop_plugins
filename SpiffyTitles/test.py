###
# Copyright (c) 2015, butterscotchstallion
# All rights reserved.
#
#
###

from supybot.test import *
import datetime
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import requests
import timeout_decorator


def response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload))


class FakeCurl:
    def __init__(self, pycurl, payload, url='https://example.com',
                 status_code=200, content_type='text/html; charset=UTF-8',
                 error=None):
        self.pycurl = pycurl
        self.payload = payload
        self.url = url
        self.status_code = status_code
        self.content_type = content_type
        self.error = error
        self.options = {}
        self.closed = False

    def setopt(self, option, value):
        self.options[option] = value

    def perform(self):
        if self.error:
            raise self.error
        self.options[self.pycurl.WRITEDATA].write(self.payload)

    def getinfo(self, info):
        if info == self.pycurl.EFFECTIVE_URL:
            return self.url
        if info == self.pycurl.RESPONSE_CODE:
            return self.status_code
        if info == self.pycurl.CONTENT_TYPE:
            return self.content_type

    def close(self):
        self.closed = True


def fake_pycurl(payload=b'', url='https://example.com', error=None):
    fake = SimpleNamespace(
        URL='URL',
        HTTPHEADER='HTTPHEADER',
        WRITEDATA='WRITEDATA',
        FOLLOWLOCATION='FOLLOWLOCATION',
        TIMEOUT='TIMEOUT',
        NOSIGNAL='NOSIGNAL',
        EFFECTIVE_URL='EFFECTIVE_URL',
        RESPONSE_CODE='RESPONSE_CODE',
        CONTENT_TYPE='CONTENT_TYPE',
        E_OPERATION_TIMEDOUT=28,
    )
    fake.error = type('FakePycurlError', (Exception,), {})
    curl = FakeCurl(fake, payload, url=url, error=error)
    fake.Curl = lambda: curl
    return fake, curl


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

    def testNumberedTitleResponsePreservesOriginalUrlIndexes(self):
        plugin = self.irc.getCallback('SpiffyTitles')

        self.assertEqual(
            plugin.get_numbered_title_response([(2, '^ Second'), (4, 'Fourth')]),
            '[2] Second | [4] Fourth')

    def testMultiUrlMessagePreservesIndexWhenFirstUrlFails(self):
        plugin = self.irc.getCallback('SpiffyTitles')

        with patch.object(plugin, 'get_title_by_message_url',
                          side_effect=[None, '^ Amazon.fr']):
            titles = plugin.get_titles_by_urls([
                'https://dead.example',
                'https://www.amazon.fr/dp/B0CTH7CVGB',
            ], self.channel)

        self.assertEqual(titles, [(2, '^ Amazon.fr')])
        self.assertEqual(plugin.get_numbered_title_response(titles),
                         '[2] Amazon.fr')

    def testDeadDefaultUrlDoesNotLogAsError(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        fake, curl = fake_pycurl()
        curl.error = fake.error(6, 'no dns')

        with patch('SpiffyTitles.plugin.pycurl', fake):
            with patch('SpiffyTitles.plugin.log.error') as error_log:
                self.assertEqual(plugin.get_source_by_url('https://dead.example'),
                                 (None, False, None))

        error_log.assert_not_called()

    def testDefaultHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        html = '<html><head><title>Example title</title></head></html>'

        with patch.object(plugin, 'get_source_by_url',
                          return_value=(html, False, None)):
            self.assertEqual(plugin.handler_default('https://example.com', self.channel),
                             '^ Example title')

    def testAmazonUrlUsesDefaultHandlerTitle(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        html = '''
            <html>
              <head><title>by Amazon Spaghetti Au Blé Complet, 500g</title></head>
            </html>
        '''

        with patch.object(plugin, 'get_source_by_url',
                          return_value=(html, False, None)):
            self.assertEqual(
                plugin.get_title_by_url(
                    'https://www.amazon.fr/dp/B0CTH7CVGB',
                    self.channel),
                '^ by Amazon Spaghetti Au Blé Complet, 500g')

    def testSourceFetchUsesPycurlWithoutRequestsDefaultHeaders(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.language.setValue('fr-FR')

        html = b'<html><head><title>Example title</title></head></html>'
        url = 'https://www.amazon.fr/dp/B0CTH7CVGB'
        fake, curl = fake_pycurl(html, url=url)
        with patch('SpiffyTitles.plugin.pycurl', fake):
            self.assertEqual(
                plugin.get_source_by_url(url),
                (html, False, None))

        headers = curl.options[fake.HTTPHEADER]
        self.assertIn(
            'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:140.0) '
            'Gecko/20100101 Firefox/140.0',
            headers)
        self.assertFalse(any(header.lower().startswith('accept-encoding:')
                             for header in headers))
        self.assertTrue(curl.closed)

    def testGetHeadersUsesBrowserNavigationHeaders(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.language.setValue('fr-FR')

        headers = plugin.get_headers()

        self.assertEqual(headers['User-Agent'],
                         'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) '
                         'Gecko/20100101 Firefox/140.0')
        self.assertIn('text/html', headers['Accept'])
        self.assertEqual(headers['Accept-Language'],
                         'fr-FR,fr;q=0.9,en-US;q=0.5,en;q=0.3')
        self.assertNotIn('Accept-Encoding', headers)
        self.assertEqual(headers['DNT'], '1')
        self.assertEqual(headers['Upgrade-Insecure-Requests'], '1')

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
            'd': [{
                'id': 'tt1234567',
                'l': 'Suggestion title',
                'q': 'feature',
                's': 'Actor One, Actor Two',
                'y': 2020,
            }],
        }

        with patch('SpiffyTitles.plugin.requests.get', return_value=response(payload)):
            title = plugin.handler_imdb('https://www.imdb.com/title/tt1234567/',
                                        urlparse('https://www.imdb.com/title/tt1234567/'),
                                        self.channel)

        self.assertEqual(title,
                         '^ Suggestion title (2020) - feature :: Actor One, Actor Two :: '
                         'https://www.imdb.com/title/tt1234567/')

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

    def testHandlerWhitelistAllowsGazelleAlias(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.handlerWhitelist.get(
            self.channel).setValue(['gazelle'])
        plugin.api_red = SimpleNamespace(request=lambda **args: {
            'group': {
                'categoryName': 'Movies',
                'name': 'Gazelle title',
            },
        })
        plugin.handlers['redacted.sh'] = plugin.handler_redacted

        self.assertEqual(plugin.get_title_by_url(
            'https://redacted.sh/torrents.php?id=123', self.channel),
            '^ Gazelle title')

    def testHandlerWhitelistBlocksDisallowedHandlerBeforeCache(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.handlerWhitelist.get(
            self.channel).setValue(['gazelle'])
        plugin.link_cache.append({
            'url': 'https://youtube.com/watch?v=abc12345678',
            'timestamp': datetime.datetime.now(),
            'title': '^ Cached YouTube title',
        })

        self.assertIsNone(plugin.get_title_by_url(
            'https://youtube.com/watch?v=abc12345678', self.channel))


class SpiffyTitlesLiveTestCase(ChannelPluginTestCase):
    plugins = ('SpiffyTitles',)

    def setUp(self):
        if os.environ.get('SPIFFYTITLES_LIVE') != '1':
            raise unittest.SkipTest('set SPIFFYTITLES_LIVE=1 to run live upstream tests')

        ChannelPluginTestCase.setUp(self)
        self.assertNotError('reload SpiffyTitles')
        conf.supybot.plugins.SpiffyTitles.linkCacheLifetimeInSeconds.setValue(0)

        youtube_key = os.environ.get('SPIFFYTITLES_YOUTUBE_DEVELOPER_KEY')
        if youtube_key:
            conf.supybot.plugins.SpiffyTitles.youtubeDeveloperKey.setValue(youtube_key)

        imgur_client_id = os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_ID')
        if imgur_client_id:
            conf.supybot.plugins.SpiffyTitles.imgurClientID.setValue(imgur_client_id)

        imgur_client_secret = os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_SECRET')
        if imgur_client_secret:
            conf.supybot.plugins.SpiffyTitles.imgurClientSecret.setValue(imgur_client_secret)

    def live_url(self, name, default=None):
        return os.environ.get('SPIFFYTITLES_LIVE_%s_URL' % name, default)

    def live_call(self, callback):
        seconds = int(os.environ.get('SPIFFYTITLES_LIVE_TIMEOUT', '20'))
        return timeout_decorator.timeout(seconds)(callback)()

    def assertLiveTitleContains(self, title, *needles):
        self.assertTrue(title)
        for needle in needles:
            self.assertIn(needle, title)

    def testLiveDefaultHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('DEFAULT', 'https://example.com/')

        title = self.live_call(lambda: plugin.handler_default(url, self.channel))

        self.assertLiveTitleContains(title, 'Example Domain')

    def testLiveYoutubeHandler(self):
        if not os.environ.get('SPIFFYTITLES_YOUTUBE_DEVELOPER_KEY'):
            raise unittest.SkipTest('set SPIFFYTITLES_YOUTUBE_DEVELOPER_KEY')

        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('YOUTUBE', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        title = self.live_call(lambda: plugin.handler_youtube(url, urlparse(url).netloc,
                                                              self.channel))

        self.assertLiveTitleContains(title, 'Duration:', 'Views:')

    def testLiveDailymotionHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('DAILYMOTION', 'https://www.dailymotion.com/video/x8a0e9g')

        title = self.live_call(lambda: plugin.handler_dailymotion(url, urlparse(url),
                                                                  self.channel))

        self.assertLiveTitleContains(title, 'Duration:', 'views')

    def testLiveVimeoHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('VIMEO', 'https://vimeo.com/76979871')

        title = self.live_call(lambda: plugin.handler_vimeo(url, urlparse(url).netloc,
                                                            self.channel))

        self.assertLiveTitleContains(title, 'Duration:', 'plays')

    def testLiveCoubHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('COUB', 'https://coub.com/view/g1s3x')

        title = self.live_call(lambda: plugin.handler_coub(url, urlparse(url).netloc,
                                                           self.channel))

        self.assertLiveTitleContains(title, 'views', 'likes', 'recoubs')

    def testLiveImdbHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('IMDB', 'https://www.imdb.com/title/tt0111161/')

        title = self.live_call(lambda: plugin.handler_imdb(url, urlparse(url), self.channel))

        self.assertLiveTitleContains(title, 'The Shawshank Redemption')

    def testLiveWikipediaHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('WIKIPEDIA',
                            'https://en.wikipedia.org/wiki/Python_(programming_language)')

        title = self.live_call(lambda: plugin.handler_wikipedia(url, urlparse(url).netloc,
                                                                self.channel))

        self.assertLiveTitleContains(title, 'programming language')

    def testLiveRedditHandler(self):
        plugin = self.irc.getCallback('SpiffyTitles')
        url = self.live_url('REDDIT', 'https://www.reddit.com/user/spez/')

        title = self.live_call(lambda: plugin.handler_reddit(url, urlparse(url).netloc,
                                                             self.channel))

        self.assertLiveTitleContains(title, 'Link karma:', 'Comment karma:')

    def testLiveImgurAlbumHandler(self):
        if not os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_ID'):
            raise unittest.SkipTest('set SPIFFYTITLES_IMGUR_CLIENT_ID')
        if not os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_SECRET'):
            raise unittest.SkipTest('set SPIFFYTITLES_IMGUR_CLIENT_SECRET')

        url = self.live_url('IMGUR_ALBUM')
        if not url:
            raise unittest.SkipTest('set SPIFFYTITLES_LIVE_IMGUR_ALBUM_URL')

        plugin = self.irc.getCallback('SpiffyTitles')
        title = self.live_call(lambda: plugin.handler_imgur_album(url, urlparse(url),
                                                                  self.channel))

        self.assertLiveTitleContains(title, 'images', 'views')

    def testLiveImgurImageHandler(self):
        if not os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_ID'):
            raise unittest.SkipTest('set SPIFFYTITLES_IMGUR_CLIENT_ID')
        if not os.environ.get('SPIFFYTITLES_IMGUR_CLIENT_SECRET'):
            raise unittest.SkipTest('set SPIFFYTITLES_IMGUR_CLIENT_SECRET')

        url = self.live_url('IMGUR_IMAGE')
        if not url:
            raise unittest.SkipTest('set SPIFFYTITLES_LIVE_IMGUR_IMAGE_URL')

        plugin = self.irc.getCallback('SpiffyTitles')
        title = self.live_call(lambda: plugin.handler_imgur_image(url, urlparse(url),
                                                                  self.channel))

        self.assertLiveTitleContains(title, 'views')

    def testLiveGazelleHandlers(self):
        redacted_url = self.live_url('REDACTED')
        orpheus_url = self.live_url('ORPHEUS')
        if not redacted_url and not orpheus_url:
            raise unittest.SkipTest('set SPIFFYTITLES_LIVE_REDACTED_URL or '
                                    'SPIFFYTITLES_LIVE_ORPHEUS_URL')

        plugin = self.irc.getCallback('SpiffyTitles')
        if not hasattr(plugin, 'api_red') and not hasattr(plugin, 'api_apl'):
            raise unittest.SkipTest('gazelle.conf is not configured')

        if redacted_url:
            title = self.live_call(lambda: plugin.handler_redacted(redacted_url,
                                                                   urlparse(redacted_url),
                                                                   self.channel))
            self.assertTrue(title)

        if orpheus_url:
            title = self.live_call(lambda: plugin.handler_apl(orpheus_url,
                                                              urlparse(orpheus_url),
                                                              self.channel))
            self.assertTrue(title)

    
# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
