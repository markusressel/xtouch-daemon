"""
The configuration: a TOML file, by default `$XDG_CONFIG_HOME/xtouch-daemon/config.toml`. See `slots.example.toml`
(written by `xtouch-daemon init-config`) and docs/configuration/.

- `files`: reading the file, its errors.
- `model`: `Config`, the whole file.
- `sections`: the sections of the daemon and the device (`[device]`, `[behavior]`, `[mqtt]`, ...).
- `slots`: the channels, states and slots (`[channel.*]`, `[state.*]`, `[slots]`, ...), with the strip of each.
- `strips`, `strip`, `audio_strips`, `layout_strips`: the types of the channels' strips and the options they share.
- `migrate`: writing a file with strips and layouts as channels, states and slots.
- `legacy`: the format with strips and layouts, for `migrate` and the GUI.
- `values`, `names`, `presets`, `base`: the kinds of values of options, lists of names with presets, the base model.
"""
