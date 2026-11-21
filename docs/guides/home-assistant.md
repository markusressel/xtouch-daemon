# Home Assistant

A `homeassistant` channel is a strip that belongs to Home Assistant instead of PipeWire: every part of it is an entity there, and
automations decide what it does. For example, the fader dims a light, the encoder sets the volume of a speaker in
another room, a button toggles a scene. The daemon reaches Home Assistant over MQTT discovery, so it needs the
[`[mqtt]`](#mqtt) section.

Any part of a channel can also show an entity of Home Assistant itself, and a fader or an encoder can set one, e.g.
the meter shows a temperature, the fader dims a light, Select toggles it. That needs no automation and no `[mqtt]`,
but the API of Home Assistant: the [`[homeassistant]`](#homeassistant) section, with a token.

## PipeWire or Home Assistant?

Each control has one owner. The audio channels (`output`, `input`, `apps`) and the pools (`auto`, `apps`, ...)
control audio on this computer and need nothing else. A `homeassistant` channel controls nothing by itself; it only
reports what happens on it and shows what Home Assistant sets. In between, an audio channel can hand its fader or its
encoder to Home Assistant and keep the other one for the volume, see
[below](#audio-strips-with-home-assistant-controls), and [`[controls]`](#controls-of-a-slot) hands a control of a slot
to Home Assistant whatever the slot shows. Never both on one control: a
fader that both set a PipeWire volume and were moved by Home Assistant would fight over the motor.

## `[mqtt]`

The MQTT broker of Home Assistant, e.g. the Mosquitto add-on. Anything that is an entity in Home Assistant needs it
(`homeassistant` channels and controls, `homeassistant = true` on a state); without such, the section is optional,
and with it the daemon still shows the device, its modes, states and slots in Home Assistant.

| Option | Default | Meaning |
|---|---|---|
| `host` | required | The broker, e.g. `"homeassistant.local"`. |
| `port` | `1883` | Its port. |
| `username` | none | The user to log in as. |
| `password` | none | The password, in the file. |
| `password_file` | none | A file that holds the password instead, e.g. one only you can read. `~` is the home directory. Surrounding whitespace is ignored. |
| `password_env` | none | An environment variable that holds the password instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |
| `discovery_prefix` | `"homeassistant"` | Home Assistant's MQTT discovery prefix. |
| `namespace` | `"xtouch"` | Starts every entity ID (`number.xtouch_lamp_fader`) and is part of the topics. Lower case letters, digits, `_`. |
| `device_name` | `"X-Touch Extender"` | The name of the device in Home Assistant. |

Set at most one of `password`, `password_file` and `password_env`. A password file that can't be read, or a
variable that is not set, stops the daemon at the start with a message.

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_file = "~/.config/xtouch-daemon/mqtt-password"
```

A changed `[mqtt]` section needs a restart of the daemon (`systemctl --user restart xtouch-daemon`). Until then, a
reload keeps the whole current configuration.

The entities are available in Home Assistant while the daemon runs and the device is connected; otherwise they are
greyed out. A last will covers a crash. The daemon connects to the broker again by itself when it was gone.

The [GUI](gui.md#live-view) shows whether the daemon is connected, and why not (e.g. a wrong password),
and its "Test connection" button tries settings before they are saved.

## `[homeassistant]`

The API of Home Assistant, for the parts bound to its entities (`{ entity = "..." }` and `{ service = "..." }`, see
[An entity of Home Assistant](../configuration/strip/bindings.md#an-entity-of-home-assistant)). The daemon connects
only while the configuration has such parts.

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The address of Home Assistant, as in the browser, e.g. `"http://homeassistant.local:8123"` (or `https://...`). The daemon uses its WebSocket API (`/api/websocket`). |
| `token` | none | A long-lived access token, in the file. |
| `token_file` | none | A file that holds the token instead, e.g. one only you can read. `~` is the home directory. Surrounding whitespace is ignored. |
| `token_env` | none | An environment variable that holds the token instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |

Set exactly one of `token`, `token_file` and `token_env`. To make a token:

1. Open Home Assistant in the browser and click your user name at the bottom left: your profile.
2. Open the **Security** tab. Under **Long-lived access tokens**, select **Create token**.
3. Give it a name, e.g. `xtouch-daemon`, and copy the token: Home Assistant shows it only once.
4. Put it into a file only you can read, and name the file in `token_file`:

```shell
install -m 600 /dev/null ~/.config/xtouch-daemon/homeassistant-token
$EDITOR ~/.config/xtouch-daemon/homeassistant-token
```

```toml
[homeassistant]
url = "http://homeassistant.local:8123"
token_file = "~/.config/xtouch-daemon/homeassistant-token"

[channel.lamp]
type = "custom"
label = "Lamp"
fader = { entity = "light.desk" }
select = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }
```

The token acts as your user: the daemon sees every entity and can call every service you can. A user of its own in
Home Assistant (Settings → People → Users) limits that to what that user may do.

| When | The daemon |
|---|---|
| You change the section and reload | Connects again with it. No restart is needed. |
| The connection breaks | Tries again after 1, 2, 5, 10 and 30 seconds, then every 60 seconds. The waits start at 1 second again only after a connection got the states. Meanwhile the parts show nothing. |
| Home Assistant refuses the token | Logs an error and stops trying. A token Home Assistant refused is never sent to it again, not even from another section: Home Assistant can ban an address after failed logins. Make a new token, put it where the section reads it, and reload. |
| It can't read `token_file`, or `token_env` is not set | Logs an error and runs without the connection. A reload tries again once there is a token. |

- A new token in the variable of `token_env` takes a restart of the service: a reload keeps its environment.
- A fader or an encoder bound to an entity gets no entity of the daemon's own over `[mqtt]`: the entity is already in
  Home Assistant.
- The log says when the daemon connects to Home Assistant, and why it can't (View → Log in the [GUI](gui.md)).
- In the GUI, the page "Home Assistant API" tests the settings before you save them, and shows how the daemon's
  connection is doing. The fields of entities suggest the entities of Home Assistant (see
  [the GUI](gui.md#suggestions-from-home-assistant)). The window reads them with the token in the editor: with
  `token_env`, start the GUI with that variable set, or it has no suggestions.

## `homeassistant` channels

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"homeassistant"`. |
| `label` | none | The top line of the LCD until Home Assistant sets one, and the start of the entity names (the id without it). |
| `color` | `"white"` | The LCD color until Home Assistant sets one. |

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_env = "XTOUCH_MQTT_PASSWORD"

[channel.living_room]
type = "homeassistant"   # number.xtouch_living_room_fader, ...
label = "Living"
color = "yellow"

[slots]
8 = "living_room"
```

The entities belong to the channel, not to a slot: they stay in Home Assistant whichever slot shows the channel, and
while none does.

## Audio strips with Home Assistant controls

An `output`, `input`, `apps` or `auto` channel can give any of its parts to Home Assistant (see
[Bindings](../configuration/strip/bindings.md)). With `encoder = "homeassistant"` or `fader = "homeassistant"` it
keeps the volume on the other control. Each part gets its entity of the [list below](#entities):

| Option | Entities |
|---|---|
| `encoder = "homeassistant"` | `number.<ns>_<id>_encoder`, and `event.<ns>_<id>_buttons` with `encoder_pressed`, `encoder_released`. |
| `fader = "homeassistant"` | `number.<ns>_<id>_fader`, and `event.<ns>_<id>_buttons` with `fader_touched`, `fader_released`. |
| `lcd = "homeassistant"` | `text.<ns>_<id>_bottom`: the second line of the LCD. |
| `color = "homeassistant"` | `select.<ns>_<id>_color`. |
| `meter = "homeassistant"` | `number.<ns>_<id>_meter`. |
| `select = { press = "homeassistant" }` (also `rec`, `solo`) | `event.<ns>_<id>_buttons` with `select_pressed`, `select_released`. |
| `select = { led = "homeassistant" }` (also `rec`, `solo`) | `select.<ns>_<id>_select_led`. |

With `[mqtt]`, a fader or an encoder bound to a program of your own is a number too: from the binding's `min` to
its `max`, and a change there runs `set`. The parts that are not bound stay with PipeWire (see
[Buttons](../configuration/strip/leds.md#buttons)). A [`custom` channel](../configuration/channels/custom.md) takes
the same parts, and Mute is a button like the others there. The channel's id names the entities, its `label` starts their
names. See [Encoders](../configuration/strip/encoders.md#homeassistant) for the details.

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"
label = "Desk"
encoder = "homeassistant"    # the fader sets the volume, the encoder dims the desk lamp
```

## Controls of a slot

A control of a slot can belong to Home Assistant whatever the slot shows, with
[`[controls]`](../configuration/slots.md#controls-and-the-chord): the fader, the encoder (turn and push), the
Select, Rec and Solo buttons (an event per press, and a select for the LED), the meter, the color and the second line
of the LCD. The entities are named by the slot
(`number.xtouch_slot_6_fader`), or by `id`:

```toml
[controls]
6 = { fader = "homeassistant", id = "desk" }      # number.xtouch_desk_fader
4 = { encoder = "homeassistant" }                 # number.xtouch_slot_4_encoder
```

With the fader taken, the encoder sets the volume of what the slot shows; with only the encoder taken, the fader
keeps it.

## Entities

`<ns>` is `mqtt.namespace`, `<id>` the id of the channel (`desk` for `[channel.desk]`), or for a control of a slot its
`id` or `slot_<n>`:

| Entity | What it is |
|---|---|
| `number.<ns>_<id>_fader` | The fader, 0..100 in steps of 0.1. Setting it moves the motor fader; moving the fader by hand sets it (at most every 100 ms while it moves, and where it was let go). |
| `number.<ns>_<id>_encoder` | The encoder, 0..100. The ring shows it; turning the encoder changes it by `behavior.encoder_step` per step. |
| `number.<ns>_<id>_meter` | The LED meter, 0..100 %: 0 is dark, 100 lights it fully; the daemon holds the level (the device would let it fall). Its 14 levels are about 7 % each, 100 % lights the red LED at the top too, so e.g. a CPU load or a power ratio goes in as it is. |
| `text.<ns>_<id>_top`, `text.<ns>_<id>_bottom` | The two lines of the LCD, 7 characters each. |
| `select.<ns>_<id>_color` | The LCD color: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. |
| `select.<ns>_<id>_rec_led`, `_solo_led`, `_mute_led`, `_select_led` | The LEDs of the buttons: `off`, `on` or `flash`. |
| `event.<ns>_<id>_buttons` | What happens on the strip: `rec_pressed`, `rec_released`, `solo_…`, `mute_…`, `select_…`, `encoder_pressed`, `encoder_released`, `fader_touched`, `fader_released`. |

A button does not switch its LED: if a button should toggle something, an automation reacts to the event and sets
the LED to show the result. Home Assistant keeps what it set last (retained on the broker), so after a restart of the
daemon the strips show it again. New entities start with the configured label and color, the fader and encoder at 0
and the LEDs off. While the broker can't be reached, a strip shows its label, `offline` and its color, and the
device does nothing on it.

Entities of a channel that was removed from the configuration are removed from Home Assistant on the next reload.

## Choices

With `[mqtt]`, an `output` or `input` channel with [`choices`](../configuration/channels/devices.md#choices) has
`select.<ns>_<id>_output` (`select.<ns>_<id>_input`): the choice the strip shows, one option per choice, named by its
`label` (or its `device`; a second choice of the same name gets a number, e.g. `Out 2`). Choosing one switches to it
like Select on the device, profile first; one that isn't there is refused and the select goes back. The select
follows the strip, also when the default changes elsewhere.

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_out_output
data:
  option: Speaker
```

## Modes, states and slots

With `[mqtt]`, Home Assistant sees and sets the [states and modes](../configuration/slots.md#states-and-modes):

| Entity | What it is |
|---|---|
| `select.<ns>_mode` | The mode picked by hand, or `auto` for the rules. Choosing one picks it, like `xtouch-daemon mode`. |
| `binary_sensor.<ns>_state_<id>` | Each state and mode, with the attributes `since`, `source` and `override`. |
| `select.<ns>_state_<id>` | The override of each state that is no mode: `auto`, `on`, `off`. |
| `switch.<ns>_state_<id>_input` | For states with `homeassistant = true`: what Home Assistant feeds into them. |
| `binary_sensor.<ns>_<id>_shown` | Whether a channel is on a slot. |
| `sensor.<ns>_slot_<n>` | What slot n shows (a channel id, `app:<name>`, `person:<name>` or `none`), with `label`, `kind`, `via` and `reason`. |

For example, the mode gaming while the PC runs a game, from another room's automation:

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_mode
data:
  option: gaming
```

## Automations

An automation that dims a light with the fader, shows its brightness on the LCD, and toggles it with Mute:

```yaml
automation:
  - alias: "X-Touch: fader dims the living room"
    mode: queued
    triggers:
      - trigger: state
        entity_id: number.xtouch_living_room_fader
    actions:
      - action: light.turn_on
        target: { entity_id: light.living_room }
        data:
          brightness_pct: "{{ trigger.to_state.state | float | round(0) }}"
      - action: text.set_value
        target: { entity_id: text.xtouch_living_room_bottom }
        data:
          value: "{{ trigger.to_state.state | float | round(0) }}%"

  - alias: "X-Touch: Mute toggles the living room"
    triggers:
      - trigger: state
        entity_id: event.xtouch_living_room_buttons
        attribute: event_type
        to: mute_pressed
    actions:
      - action: light.toggle
        target: { entity_id: light.living_room }

  - alias: "X-Touch: the Mute LED shows the living room light"
    triggers:
      - trigger: state
        entity_id: light.living_room
    actions:
      - action: select.select_option
        target: { entity_id: select.xtouch_living_room_mute_led }
        data:
          option: "{{ 'on' if is_state('light.living_room', 'on') else 'off' }}"

  - alias: "X-Touch: the meter shows the power of the washing machine"
    triggers:
      - trigger: state
        entity_id: sensor.washing_machine_power
    actions:
      - action: number.set_value
        target: { entity_id: number.xtouch_living_room_meter }
        data:
          # 2000 W lights it fully
          value: "{{ [trigger.to_state.state | float(0) / 2000 * 100, 100] | min | round(0) }}"
```

To react to the entities from code, see [As a haad controller](../development/haad-controller.md).

Next: [Slots](../configuration/slots.md#controls-and-the-chord) (controls of a slot), [Troubleshooting](troubleshooting.md#home-assistant).
