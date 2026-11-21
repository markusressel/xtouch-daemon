# Encoders

![The encoder: a knob in a ring of 13 LEDs, lit from the left](../../images/controls/encoder.png){ .xt-part width="110" }

The encoder is the knob above the display of a strip. It turns and it pushes. What it does is set by the `encoder`
option of the strip's channel, and the ring of 13 [LEDs](leds.md) around it shows the result. After a turn or a push, the
second line of the LCD shows the exact value for 2 seconds instead of the volume; moving the fader ends that.

The fader of an audio strip sets the volume. You can give the fader another job: Home Assistant controls it
([`fader = "homeassistant"`](#fader-homeassistant)), or it sets a value of your own
([bound](bindings.md)), such as the brightness of a screen. Then the encoder takes over the volume, and the volume is its only mode.

The `encoder` option takes a mode, which is a word, or a table for a value of your own:

| `encoder` | Turn | Push | Ring | LCD |
|---|---|---|---|---|
| `volume` | Changes the volume by [`behavior.encoder_step`](../behavior.md) per step; the fader follows. | Sets `behavior.reset_volume`. | The volume, lit from the left. | The volume. |
| `balance` | Moves the balance between left and right, 5 % per step. Does nothing on a mono output or stream. | Centers it. | From the center to the side. | `L 15%`, `center`, `R 5%`. |
| `pick` | Picks the application of the slot among the ones without a channel of their own, paused or not. | Pins it. | Which of them, as a dot; pinned, lit up to there. | Which of how many (`2/5`); `pinned` or `auto`. |
| `media` | Seeks in the track of the applications' media player, 5 s per step. | Plays or pauses. | How far the track is, lit from the left; blinking while paused, dark while stopped. | Where the track is (`1:05`); `playing` or `paused`. |
| `homeassistant` | Changes a number entity in Home Assistant that the daemon creates. | Sends an event to Home Assistant. | The number. | The number (`42%`). |
| `{ set, watch, ... }` | Changes a [value of your own](#a-value-of-your-own) by its `step`. | Sets its `push`. | The value, lit from the left. | The value, in its `format`. |

Which modes a strip takes depends on what it shows. In each row of this table, the first mode is the default:

| What the strip shows | Encoder modes |
|---|---|
| A channel of type `output` or `input` | `balance`, `volume`, `homeassistant` |
| A channel of type `apps` | `media`, `volume`, `balance`, `homeassistant` |
| An application that a slot takes from the pool `apps` or `auto`, without a channel of its own | `pick`, `media`, `volume`, `balance` |
| An output or input that a slot takes from the pool `devices` | `balance`, `volume` |

The strips of people have no encoder at all: the encoder has nothing to do there.

The modes above belong to the strip's channel or place. On top of that, the `[controls]` section can take over the
encoder of a slot while a condition holds, whatever the slot shows, and give it to Home Assistant or to a
value (see [Controls](../slots.md#controls-and-the-chord)). Slot 5 gives its encoder to Home Assistant, slot 6 uses it for the
brightness of a [custom channel](../channels/custom.md) named `screen`:

```toml
[controls]
5 = { encoder = "homeassistant" }
6 = { encoder = { channel = "screen" } }
```

A mode that the strip does not have is an error, e.g.
`channel.web: encoder: pick is not for apps strips (media, volume, balance, homeassistant)`.
`xtouch-daemon check-config` shows the encoder of every channel.

A channel of type `homeassistant` has no `encoder` option, because its encoder is always an entity in Home
Assistant (see [Home Assistant](../../guides/home-assistant.md#entities)). That is a different thing from the mode
`homeassistant` above, which gives the encoder of an audio strip to Home Assistant.

```toml
[channel.out]
type = "output"
label = "Speaker"
encoder = "volume"   # fine steps instead of the balance

[slots]
5 = [{ show = "auto", encoder = "media" }]   # slot 5 shows auto; its encoder is in mode media, not pick
```

## `volume`

Fine steps of the volume. One step is `behavior.encoder_step` percent (1 by default), and the fader follows. A push
sets `behavior.reset_volume` (100 % by default). Both stay within the [volume range](../channels/index.md#volume-range) of the
channel.

## `balance`

The balance between the left and the right channel. One step moves it 5 %, so 20 steps go from the center to one side.
A push centers it. The ring lights from its center towards the side the balance leans to. The LCD shows the exact balance,
e.g. `L 15%` (15 % of the way from the center to the full left) or `center`. On a mono output or stream the encoder
does nothing.

## `pick`

For slots that show `auto`, or the pool `apps`. Turning the encoder picks the slot's application among the **candidates**: the applications without a
channel of their own, paused ones too. People are not candidates. If another `auto` slot shows the application you pick, the two slots swap applications. On a slot that shows
no application yet, a turn puts one there.

A push pins the application: it stays on the slot after it stopped playing. The next push unpins it, and the
slot is picked by itself again. The ring shows which
of the candidates the slot has, as a dot; while pinned, it is lit up to there. The LCD shows which one of how many
(`2/5`) after a turn. After a push it shows `pinned`, or `auto` after a push that unpins (the slot picks by itself again).

## `media`

The default for `apps` channels. The encoder controls the media player of the strip's applications: Spotify, a browser,
mpv with mpv-mpris, anything that speaks [MPRIS](https://specifications.freedesktop.org/mpris-spec/latest/) on the
session bus.

| | `media` |
|---|---|
| Turn | Seeks 5 seconds per step. |
| Push | Plays or pauses. |
| Ring | Fills up from the left with how far the track is. It blinks while the track is paused and is dark while it is stopped, or for a live stream (it has no length). |
| LCD | Where the track is after a seek (`1:05`), and what a push made of it (`playing`, `paused`). |

The daemon finds the player of the application by its process (for a browser: the process that plays the sound)
or, if that fails, by its name (`spotify` for Spotify). An application without a player leaves the encoder without a
function.

A browser ends its audio stream a few seconds after you pause a video. So a paused player keeps the strip lit: the
fader stays at the volume and the ring blinks. The strip goes dark when the player is stopped or closed. On a slot of
`apps` or `auto`, the slot keeps the stopped application for the seconds of `hold` in
[`[pool.apps]`](../slots.md#pools-of-applications-and-of-people), then it frees the slot.

!!! note "Needs the session bus"

    `xtouch-daemon` needs the D-Bus session bus for this, which a systemd user service has. Without it the daemon logs
    `No media players: the session bus is not reachable (...)` once and keeps trying.

## `homeassistant`

The encoder belongs to Home Assistant, the fader still sets the volume. For example, the encoder dims the light next
to the speakers. Turning changes `number.<ns>_<id>_encoder` (0..100) by `behavior.encoder_step` per step, the ring
shows it, the LCD shows the value (`42%`), and a push sends `encoder_pressed`/`encoder_released` on `event.<ns>_<id>_buttons`. It works while the strip
is idle too. In the entity IDs, `<ns>` is the `namespace` of `[mqtt]` (`xtouch` by default) and `<id>` the id of the channel. An automation in Home Assistant decides what the number does, see
[Home Assistant](../../guides/home-assistant.md#audio-strips-with-home-assistant-controls).

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"  # number.xtouch_desk_encoder
encoder = "homeassistant"
```

## A value of your own

The encoder sets a value that commands of your own change (`set`) and read (`watch`), e.g. the brightness of a screen with
[system-control](https://github.com/markusressel/system-control) (`sysctrl`). The fader still sets the volume. The
options are those of a value in [Bindings](bindings.md) (`set`, `watch`, `min`, `max`, `step`, `push`, `format`), and
they are explained in [Custom channels](../channels/custom.md#a-value).

The encoder can also set an entity of Home Assistant, e.g. `encoder = { entity = "media_player.kitchen" }` for the
volume of a speaker. See [An entity of Home Assistant](bindings.md#an-entity-of-home-assistant).

```toml
[channel.out]
type = "output"
label = "Speaker"
encoder = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, push = 1.0, format = "{value:.0%}" }
```

## `fader = "homeassistant"`

The other way round: the fader belongs to Home Assistant (`number.<ns>_<id>_fader`, with `fader_touched` and
`fader_released` events), and the encoder sets the volume in fine steps. The LCD still shows the volume. A fader
bound to a [value of your own](bindings.md) does the same: the encoder sets the volume. Only
`fader = "homeassistant"` needs the [`[mqtt]`](../../guides/home-assistant.md#mqtt) section.

```toml
[channel.music]
type = "apps"
match = ["spotify"]
label = "Music"
fader = "homeassistant"      # number.xtouch_music_fader; encoder: volume
```
