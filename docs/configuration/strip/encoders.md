# Encoders

![The encoder: a knob in a ring of 13 LEDs, lit from the left](../../images/controls/encoder.png){ .xt-part width="110" }

The encoder is the knob above the display of a strip. It turns and it pushes. The `encoder` option of the strip's
channel sets what it does, and the ring of 13 [LEDs](leds.md) around it shows the result. After a turn or a push, the
second line of the LCD shows the exact value for 2 seconds; moving the fader ends that.

The fader of an audio strip sets the volume. If the fader gets another job (Home Assistant controls it, see
[`fader = "homeassistant"`](#fader-homeassistant), or it sets a [value of your own](bindings.md)), the encoder takes
over the volume, and the volume is its only mode.

The `encoder` option takes a mode, which is a word, or a table for a value of your own:

| `encoder` | Turn | Push | Ring | LCD |
|---|---|---|---|---|
| [`volume`](#volume) | Changes the volume; the fader follows. | Resets it. | The volume. | The volume. |
| [`balance`](#balance) | Moves the balance between left and right. | Centers it. | From the center to the side. | `L 15%`, `center`, `R 5%`. |
| [`pick`](#pick) | Picks the application of the slot among the candidates. | Pins it. | Which of them. | Which of how many (`2/5`); `pinned` or `auto`. |
| [`media`](#media) | Seeks in the track of the applications' media player. | Plays or pauses. | How far the track is. | Where the track is (`1:05`); `playing` or `paused`. |
| [`homeassistant`](#homeassistant) | Changes a number entity in Home Assistant that the daemon creates. | Sends an event to Home Assistant. | The number. | The number (`42%`). |
| `{ set, watch, ... }` | Changes a [value of your own](#a-value-of-your-own) by its `step`. | Sets its `push`. | The value. | The value, in its `format`. |

Which modes a strip takes depends on what it shows. In each row of this table, the first mode is the default:

| What the strip shows | Encoder modes |
|---|---|
| A channel of type `output` or `input` | `balance`, `volume`, `homeassistant` |
| A channel of type `apps` | `media`, `volume`, `balance`, `homeassistant` |
| An application that a slot takes from the pool `apps` or `auto`, without a channel of its own | `pick`, `media`, `volume`, `balance` |
| An output or input that a slot takes from the pool `devices` | `balance`, `volume` |

The strips of people have no encoder at all: the encoder has nothing to do there.

The `[controls]` section can also take over the encoder of a slot, whatever the slot shows (see
[Controls](../slots.md#controls-and-the-chord)). Slot 5 gives its encoder to Home Assistant, slot 6 uses it for the
brightness of a [custom channel](../channels/custom.md) named `screen`:

```toml
[controls]
5 = { encoder = "homeassistant" }
6 = { encoder = { channel = "screen" } }
```

A mode that the strip does not have is an error, e.g.
`channel.web: encoder: pick is not for apps strips (media, volume, balance, homeassistant)`.
`xtouch-daemon check-config` shows the encoder of every channel. A channel of type `homeassistant` has no `encoder`
option: its encoder is always an entity (see [Home Assistant](../../guides/home-assistant.md#entities)).

```toml
[channel.out]
type = "output"
encoder = "volume"   # fine steps instead of the balance

[slots]
5 = [{ show = "auto", encoder = "media" }]   # slot 5 shows auto; its encoder is in mode media, not pick
```

## `volume`

Fine steps of the volume. One step is [`behavior.encoder_step`](../behavior.md) percent (1 by default), and the
fader follows. The ring is lit from the left. A push sets `behavior.reset_volume` (100 % by default). Both stay within
the [volume range](../channels/index.md#volume-range) of the channel.

## `balance`

The balance between the left and the right channel. One step moves it 5 %, so 20 steps go from the center to one side.
A push centers it. The ring lights from its center towards the side the balance leans to. The LCD shows the exact
balance, e.g. `L 15%` (15 % of the way to the full left) or `center`. On a mono output or stream the encoder does
nothing.

## `pick`

For slots that show `auto`, or the pool `apps`. A turn picks the slot's application among the **candidates**: the
applications without a channel of their own, paused ones too (people are not). If another `auto` slot shows the
application you pick, the two slots swap. On a slot without an application, a turn puts one there.

A push pins the application: it stays on the slot after it stopped playing. The next push unpins it, and the slot
picks by itself again. The ring shows which candidate the slot has, as a dot; while pinned, it is lit up to there. The
LCD shows which one of how many (`2/5`) after a turn, and `pinned` or `auto` after a push.

## `media`

The default for `apps` channels. The encoder controls the media player of the strip's applications: Spotify, a browser,
mpv with mpv-mpris, anything that speaks [MPRIS](https://specifications.freedesktop.org/mpris-spec/latest/) on the
session bus.

A turn seeks 5 seconds per step, a push plays or pauses. The ring fills up from the left with how far the track is.
It blinks while the track is paused and is dark while it is stopped, or for a live stream (it has no length). The LCD
shows where the track is after a seek (`1:05`), and `playing` or `paused` after a push.

The daemon finds the player by the process of the application or, if that fails, by its name (`spotify` for
Spotify). An application without a player leaves the encoder without a function.

A browser ends its audio stream a few seconds after you pause a video, so a paused player keeps the strip lit. The
strip goes dark when the player is stopped or closed. On a slot of `apps` or `auto`, the slot keeps the stopped
application for the seconds of `hold` in [`[pool.apps]`](../slots.md#pools-of-applications-and-of-people), then frees it.

!!! note "Needs the session bus"

    Without the D-Bus session bus (a systemd user service has it), the daemon logs
    `No media players: the session bus is not reachable (...)` once and keeps trying.

## `homeassistant`

The encoder belongs to Home Assistant, the fader still sets the volume. Turning changes
`number.<ns>_<id>_encoder` (0..100) by `behavior.encoder_step` per step, the ring and the LCD show it, and a push
sends `encoder_pressed`/`encoder_released` on `event.<ns>_<id>_buttons`. It works while the strip is idle too. An
automation in Home Assistant decides what the number does, see
[Home Assistant](../../guides/home-assistant.md#audio-strips-with-home-assistant-controls) (it explains `<ns>` and `<id>`).

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"  # number.xtouch_desk_encoder
encoder = "homeassistant"
```

## A value of your own

The encoder sets a value that commands of your own change (`set`) and read (`watch`), e.g. the brightness of a screen.
The fader still sets the volume. The options are those of [a value](../channels/custom.md#a-value); the full
example, with the screen, is in [Bindings](bindings.md#example-the-brightness-of-a-screen). The encoder can also set
an entity of Home Assistant, e.g. `encoder = { entity = "media_player.kitchen" }` for the volume of a speaker (see
[An entity of Home Assistant](bindings.md#an-entity-of-home-assistant)).

## `fader = "homeassistant"`

The other way round: the fader belongs to Home Assistant (`number.<ns>_<id>_fader`, with `fader_touched` and
`fader_released` events), and the encoder sets the volume in fine steps. The LCD still shows the volume. It needs the
[`[mqtt]`](../../guides/home-assistant.md#mqtt) section.

```toml
[channel.music]
type = "apps"
match = ["spotify"]
label = "Music"
fader = "homeassistant"      # number.xtouch_music_fader; encoder: volume
```
