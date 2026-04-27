# bishop_plugins

Plugins for bishop, a Limnoria IRC bot.

This repository is laid out as a multi-plugin repository for Limnoria's
PluginDownloader: every top-level plugin directory can be installed with:

```text
@plugindownloader install libussa <PluginName>
```

The bot image is responsible for Python dependencies from each plugin's
`requirements.txt`; PluginDownloader only downloads the plugin source and the
bot still loads plugins with `@load <PluginName>`.

## Tests

The repository has a uv-managed test environment with Limnoria and the runtime
dependencies used by the plugins:

```text
uv sync
```

Run a focused plugin test suite with:

```text
uv run scripts/test-plugin SpiffyTitles
```

Multiple plugin names are accepted:

```text
uv run scripts/test-plugin IMDB SpiffyTitles
```

The wrapper creates a temporary plugin directory before calling `supybot-test`.
This avoids Limnoria discovering unrelated plugin tests when you only want to
run one plugin.

`LastFM` tests are not self-contained; they require external API credentials.
