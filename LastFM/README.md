LastFM for Supybot/Limnoria
==============

A Supybot/Limnoria plugin for LastFM, forked from [krf/supybot-lastfm](https://github.com/krf/supybot-lastfm).

### Changes made in this fork

- Native Python 3 support.
- Code cleanup, formatting enhancements, and various bugfixes.
- Migration to the newer (v2) LastFM API, using JSON instead of XML.
- Simpler DB implementation tracking bot accounts and hostmasks instead of nicks (unfortunately, this resets your DB if you're upgrading from krf's older versions).
- The active commands are `np`, `wp`, `set`, `topartists`, and `toptags`.
- Optional YouTube search links can be added to `np` output. Set
  `plugins.LastFM.youtubeApiKey` and enable `plugins.LastFM.fetchYouTubeLink`
  for this to work.

### Setup and Usage

Before using any parts of this plugin, you must register on the LastFM website and obtain an API key for your bot: https://www.last.fm/api/account/create

After doing so, you must then configure your bot to use your key: `/msg <botname> config plugins.LastFM.apiKey <your-api-key>`.

Showing now playing information:
```
<@GLolol> %np RJ
<@Atlas> The Shadows — Apache — instrumental, surf rock — 42x
```
When used in a channel, `%np <nick>` first checks whether `<nick>` is a
registered channel user with a saved LastFM username. If not, `<nick>` is used
as a LastFM username directly.

Setting your LastFM user:
```
<@GLolol> %lastfm set RJ
<@Atlas> you are now https://www.last.fm/user/RJ
```

Showing current channel listeners:
```
<@GLolol> %wp
<@Atlas> R⁣J  The Shadows  Apache
```
