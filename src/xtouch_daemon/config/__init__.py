"""
The configuration: a TOML file, by default `$XDG_CONFIG_HOME/xtouch-daemon/config.toml`. See `config.example.toml`
(also written by `xtouch-daemon init-config`) for every option.

- `files`: reading the file, its errors.
- `model`: `Config`, the whole file, and the checks across its sections.
- `sections`: the sections besides the strips and layouts (`[device]`, `[behavior]`, `[mqtt]`, ...).
- `layout`: a layout (`[[layout]]`).
- `strips`, `strip`, `audio_strips`, `layout_strips`: the strip types and the options they share.
- `inheritance`: resolving `inherit` strips of layouts.
- `values`, `names`, `presets`, `base`: the kinds of values of options, lists of names with presets, the base model.
"""
