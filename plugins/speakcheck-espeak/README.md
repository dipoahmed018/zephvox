# speakcheck-espeak

A [speakcheck](../../README.md) plugin that adds the `espeak` pronunciation driver, based on
[espeak-ng](https://github.com/espeak-ng/espeak-ng) through [phonemizer](https://github.com/bootphon/phonemizer).
espeak-ng's rules cover any word, in US or UK English.

speakcheck's default drivers (CMUdict, then DeepPhonemizer for unknown words) already cover every
word. Use this plugin if you prefer espeak's rules, for example for British English.

```sh
uv sync --extra models --extra cpu --extra espeak    # in the speakcheck folder, next to your other extras
```

```toml
# config.toml
[provider.chain]
order = ["cmudict", "espeak"]       # or ["espeak"] with language = "en-gb" below

[provider.espeak]
language = "en-us"                  # or "en-gb"
```

## License

GPL-3.0-or-later ([LICENSE](LICENSE)), because phonemizer and espeak-ng are GPL. This plugin is a
separate package: speakcheck never imports it unless you install it and choose it in your config.
It is not covered by speakcheck's commercial license.
