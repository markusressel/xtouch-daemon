# Encoders

The fader of an audio strip sets the volume, unless it is in [Home Assistant](#fader-homeassistant). The encoder
does what the strip's `encoder` option says, and its LED ring shows it. After a turn or a push, the second line of
the LCD shows the exact value for 2 seconds instead of the volume; moving the fader ends that.

| `encoder` | Turn | Push | Ring | LCD |
|---|---|---|---|---|
| `volume` | Changes the volume by `behavior.encoder_step` per step; the fader follows. | Sets `behavior.reset_volume`. | The volume, lit from the left. | The volume. |
| `balance` | Moves the balance between left and right, 5 % per step. Nothing for mono devices and streams. | Centers it. | From the center to the side. | `L 15%`, `center`, `R 5%`. |
| `pick` | Picks the application among those without a strip of their own. | Pins it. | Which of them, as a dot; pinned, lit up to there. | Which of how many (`2/5`); `pinned` or `auto`. |
| `media` | Seeks in the track of the applications' media player, 5 s per step. | Plays or pauses. | How far the track is, lit from the left; blinking while paused, dark while stopped. | Where the track is (`1:05`); `playing` or `paused`. |
| `homeassistant` | Changes a number entity in Home Assistant. | An event in Home Assistant. | The number. | The number (`42%`). |

Which channel types have which modes, the default first:

| Channel type | Encoder modes |
|---|---|
| `output`, `input` | `balance`, `volume`, `homeassistant` |
| `apps` | `media`, `volume`, `balance`, `homeassistant` |
| `auto` (a place in a slot) | `pick`, `media`, `volume`, `balance`, `homeassistant` |

A mode that the type does not have is an error, e.g.
`channel.web: encoder: pick is not for apps strips (media, volume, balance, homeassistant)`. With
[`fader = "homeassistant"`](#fader-homeassistant) the default is `volume`, and it is the only mode.
`xtouch-daemon check-config` shows the encoder of every channel.

`homeassistant` channels have no `encoder` option: their encoder is a Home Assistant entity, see
[Home Assistant](../../guides/home-assistant.md#entities).

```toml
[channel.out]
type = "output"
label = "Speaker"
encoder = "volume"   # fine steps instead of the balance

[slots]
5 = [{ show = "auto", encoder = "media" }]   # pick is the default for auto
```

## `volume`

Fine steps of the volume. One step is `behavior.encoder_step` percent (1 by default), and the fader follows. A push
sets `behavior.reset_volume` (100 % by default). Both stay within the [volume range](../channels/index.md#volume-range) of the
channel.

## `balance`

The balance between the left and the right channel. One step moves it 5 %, so 20 steps go from the center to one side.
A push centers it. The ring lights from its center towards the side the balance leans to; only a balance exactly in
the center lights the center LED alone, so one a hair off lights the next LED too. The LCD shows the exact balance,
e.g. `L 15%` (the left side 15 % towards the full left), `R <1%` or `center`. On mono devices and streams the encoder
does nothing.

## `pick`

For `auto`. Turning the encoder picks the slot's application among those without a channel of their own, paused
ones too. One that another `auto` slot has swaps with it. It works on a slot without an application too.

A push pins the application: it stays on the slot after it stopped playing, until the next push. The ring shows which
of the candidates the slot has, as a dot; while pinned, it is lit up to there. The LCD shows which one of how many
(`2/5`) after a turn, and `pinned` or `auto` (picked by itself again) after a push.

## `media`

The default for `apps` channels. The encoder controls the media player of the strip's applications: Spotify, a browser,
mpv with mpv-mpris, anything that speaks [MPRIS](https://specifications.freedesktop.org/mpris-spec/latest/) on the
session bus. Turning seeks 5 seconds per step, a push plays or pauses. The ring fills up from the left with how far the track
is, also while the strip is idle (e.g. paused). It blinks (0.5 s on, 0.5 s off) while the track is paused and is
dark while it is stopped, or for live streams without a length. The LCD shows where the track is
after a seek (`1:05`), and what a push made of it (`playing`, `paused`).

The player is the one of the process that plays a stream of the strip or of one of its parents, since browsers play
from a child process. Without such a player, one named like the application (`spotify` for Spotify). Playing streams
come first. Applications without a player leave the encoder without a function.

A paused player keeps the strip active, also after its streams are gone: browsers end the stream of a paused video
a few seconds after the pause, and the strip would go dark with it. It stays lit with its fader at the volume, and
the ring blinks; a move of the fader sets the volume the stream gets when it plays again. The strip goes dark when
the player is stopped or closed. On a slot of `apps` or `auto` this lasts as long as the slot keeps the application
(`hold` of `[pool.apps]`).

`xtouch-daemon` needs the D-Bus session bus for this, which a systemd user service has. Without it the daemon logs
`No media players: the session bus is not reachable (...)` once and keeps trying.

## `homeassistant`

The encoder belongs to Home Assistant, the fader still sets the volume. For example, the encoder dims the light next
to the speakers. Turning changes `number.<ns>_<id>_encoder` (0..100) by `behavior.encoder_step` per step, the ring
shows it, the LCD shows the value (`42%`), and a push sends `encoder_pressed`/`encoder_released` on `event.<ns>_<id>_buttons`. It works while the strip
is idle too. An automation in Home Assistant decides what the number does, see
[Home Assistant](../../guides/home-assistant.md#audio-strips-with-home-assistant-controls).

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"  # number.xtouch_desk_encoder
encoder = "homeassistant"
```

## `fader = "homeassistant"`

The other way round: the fader belongs to Home Assistant (`number.<ns>_<id>_fader`, with `fader_touched` and
`fader_released` events), and the encoder sets the volume in fine steps. The LCD still shows the volume. Both need the
[`[mqtt]`](../../guides/home-assistant.md#mqtt) section.

```toml
[channel.music]
type = "apps"
match = ["spotify"]
label = "Music"
fader = "homeassistant"      # number.xtouch_music_fader; encoder: volume
```
