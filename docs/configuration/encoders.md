# Encoders

The fader of an audio strip always sets the volume. The encoder does what the strip's `encoder` option says, and its
LED ring shows it.

| `encoder` | Turn | Push | Ring |
|---|---|---|---|
| `volume` | Changes the volume by `behavior.encoder_step` per step; the fader follows. | Sets `behavior.reset_volume`. | The volume, lit from the left. |
| `balance` | Moves the balance between left and right, 5 % per step. Nothing for mono devices and streams. | Centers it. | From the center to the side. |
| `pick` | Picks the application among those without a strip of their own. | Pins it. | Which of them, as a dot; pinned, lit up to there. |

<!-- encoder modes media and homeassistant: added with their implementation -->

Which strip types have which modes, the default first:

| Strip type | Encoder modes |
|---|---|
| `output`, `input` | `balance`, `volume` |
| `apps` | `volume`, `balance` |
| `auto` | `pick`, `volume`, `balance` |

A mode that the strip type does not have is an error, e.g.
`strip[2]: encoder: pick is not for apps strips (volume, balance)`.

`homeassistant` strips have no `encoder` option: their encoder is a Home Assistant entity, see
[Home Assistant](../home-assistant.md#entities).

```toml
[[strip]]
type = "output"
label = "Speaker"
encoder = "volume"   # fine steps instead of the balance

[[strip]]
type = "auto"
encoder = "pick"     # the default for auto strips
```

## `volume`

Fine steps of the volume. One step is `behavior.encoder_step` percent (1 by default), and the fader follows. A push
sets `behavior.reset_volume` (100 % by default). Both stay within the [volume range](strips.md#volume-range) of the
strip.

## `balance`

The balance between the left and the right channel. One step moves it 5 %, so 20 steps go from the center to one side.
A push centers it. The ring lights from its center towards the side the balance leans to. On mono devices and streams
the encoder does nothing.

## `pick`

For `auto` strips. Turning the encoder picks the strip's application among those without a strip of their own,
paused ones too. One that another `auto` strip has swaps with it. It works on a strip without an application too.

A push pins the application: it stays on the strip after it stopped playing, until the next push. The ring shows which
of the candidates the strip has, as a dot; while pinned, it is lit up to there.
