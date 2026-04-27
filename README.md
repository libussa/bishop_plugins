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
