# Home Assistant

[Home Assistant](https://www.home-assistant.io/) is a home automation program. An *entity* is one thing in it, such
as the light `light.desk`. This page shows three ways to connect the device to it, and a related case for programs. Choose by what you want:

| You want | Use | Needs |
|---|---|---|
| A strip that does nothing by itself, and your Home Assistant automations decide what it does (the fader dims a light, a button toggles a scene) | A [`homeassistant` channel](#homeassistant-channels). The daemon creates entities in Home Assistant for every part of the strip, and an automation of yours reacts to them. | The [`[mqtt]`](#mqtt) section |
| A strip whose parts are tied straight to an entity that is already in Home Assistant (the meter shows a temperature, the fader dims a light, the Select button toggles it), with no automation | A [binding](../configuration/strip/bindings.md) of the part, e.g. `fader = { entity = "light.desk" }`, in a `custom` channel (a strip you build part by part). | The [`[homeassistant]`](#homeassistant) section, with a token |
| An audio strip that keeps the volume on one control and hands the other control to Home Assistant | `encoder = "homeassistant"` or `fader = "homeassistant"` on an audio channel, see [below](#audio-strips-with-home-assistant-controls). | The [`[mqtt]`](#mqtt) section |

An *entity of the daemon* is one that the daemon creates in Home Assistant (e.g. `number.xtouch_living_room_fader`).
The first and the third way use them. The second way uses entities that Home Assistant has anyway. All routes need
a strip: a [slot](../configuration/slots.md) must show the channel, as in the examples below.

The daemon announces its entities to Home Assistant through the MQTT broker (the program that passes messages between
them), by *MQTT discovery*: Home Assistant finds them without any setup on its side.

## PipeWire or Home Assistant?

Each control has one owner, PipeWire or Home Assistant:

| Owner | Controls |
|---|---|
| PipeWire | The audio channels and the pools of strips control audio on this computer and need nothing else. |
| Home Assistant | A `homeassistant` channel controls nothing by itself. It reports to Home Assistant what happens on its controls (as an event: a message in Home Assistant that tells "this button was pressed", see [Entities](#entities)), and shows what Home Assistant sets (the entities of its parts). What follows is up to your automations. |
| Both, a control each | An audio channel can hand its fader or its encoder to Home Assistant and keep the other one for the volume, see [below](#audio-strips-with-home-assistant-controls). [`[controls]`](#controls-of-a-slot) hands a control of a slot to Home Assistant whatever the slot shows. |

!!! warning "Never both on one control"

    If a fader set a PipeWire volume and Home Assistant moved it too, the two would fight over the motor of the fader.

## `[mqtt]`

The MQTT broker of Home Assistant, e.g. the Mosquitto add-on. You must add the section for everything that makes the
daemon create entities in Home Assistant: `homeassistant` channels, `"homeassistant"` as the value of a part or
control, and `homeassistant = true` on a state. Without those, the section is optional. With it, the daemon also
shows the device, its modes, states and slots in Home Assistant.

| Option | Default | Meaning |
|---|---|---|
| `host` | required | The broker, e.g. `"homeassistant.local"`. |
| `port` | `1883` | Its port. |
| `username` | none | The user to log in as. |
| `password` | none | The password, in the file. |
| `password_file` | none | A file that holds the password instead, e.g. one only you can read. `~` is the home directory. Surrounding whitespace is ignored. |
| `password_env` | none | An environment variable that holds the password instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |
| `discovery_prefix` | `"homeassistant"` | Home Assistant's MQTT discovery prefix. |
| `namespace` | `"xtouch"` | Starts every entity ID (`number.xtouch_living_room_fader`) and is part of the MQTT topics. Lower case letters, digits, `_`. |
| `device_name` | `"X-Touch Extender"` | The name of the device in Home Assistant. |

Set at most one of `password`, `password_file` and `password_env`. A password file that can't be read, or a
variable that is not set, stops the daemon at the start with a message.

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_file = "~/.config/xtouch-daemon/mqtt-password"
```

A changed `[mqtt]` section needs a restart of the daemon (`systemctl --user restart xtouch-daemon`). The daemon
reloads a saved file by itself, but it ignores a file whose `[mqtt]` section changed: it keeps the whole
configuration it runs, also the changes in other sections, until you restart.

The entities are available in Home Assistant while the daemon runs and the device is connected; otherwise Home
Assistant greys them out. This also holds after a crash: the broker tells Home Assistant that the daemon is gone
(an MQTT "last will", a message that the daemon leaves with the broker for this case). The daemon connects to the
broker again by itself when the broker was gone.

The [GUI](gui.md#live-view) shows whether the daemon is connected, and why not (e.g. a wrong password),
and its "Test connection" button tries settings before they are saved. To check that it works, open Settings →
Devices & services → MQTT in Home Assistant: the device "X-Touch Extender" (`device_name`) is listed there with its
entities.

## `[homeassistant]`

The API of Home Assistant, for the parts bound to entities that Home Assistant has (`{ entity = "..." }` and
`{ service = "..." }`, see
[An entity of Home Assistant](../configuration/strip/bindings.md#an-entity-of-home-assistant)). The daemon connects
only while the configuration has such parts (in a channel or in `[controls]`). This needs no `[mqtt]` section.

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

(`~/.config/xtouch-daemon/` is the directory of the configuration file `config.toml`. Create it with
`mkdir -p ~/.config/xtouch-daemon` if it does not exist.) Then add this to `config.toml`. The example has a
`custom` channel with an entity binding. The fader sets the brightness of the light `light.desk` (0 to 100 % of the
fader is the brightness range of the light). Select toggles the light, and its LED shows whether the light is on. The
slot puts the channel on the first strip:

```toml
[homeassistant]
url = "http://homeassistant.local:8123"
token_file = "~/.config/xtouch-daemon/homeassistant-token"

[channel.lamp]
type = "custom"
label = "Lamp"
fader = { entity = "light.desk" }
select = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }

[slots]
1 = "lamp"
```

The token acts as your user: the daemon sees every entity and can call every service you can. A user of its own in
Home Assistant (Settings → People → Users) limits that to what that user may do.

| When | The daemon |
|---|---|
| You change the section and save the file | The daemon reloads and connects again with the new section. No restart is needed. |
| The connection breaks | Tries again after 1, 2, 5, 10 and 30 seconds, then every 60 seconds. The waits get longer with each failed try; they start at 1 second again only after a connection that received the states of the entities. Meanwhile the parts show nothing. |
| Home Assistant refuses the token | Logs an error and stops trying. The daemon never sends a refused token to that address again, even if you move the same token to another option (e.g. from `token` to `token_file`), because Home Assistant can ban an address after failed logins. Make a new token, put it where the section reads it, and save the file. |
| It can't read `token_file`, or `token_env` is not set | Logs an error and runs without the connection. Save the file again once there is a token. |

- A new token in the variable of `token_env` takes a restart of the service: a reload keeps its environment.
- A fader or an encoder bound to an entity of Home Assistant gets no entity of the daemon's own over `[mqtt]`: the
  entity is already in Home Assistant.
- The log says when the daemon connects to Home Assistant, and why it can't (View → Log in the [GUI](gui.md)).
- In the GUI, the page "Home Assistant API" tests the settings before you save them, and shows how the daemon's
  connection is doing. The fields of entities suggest the entities of Home Assistant (see
  [the GUI](gui.md#suggestions-from-home-assistant)). The window reads them with the token in the editor: with
  `token_env`, start the GUI with that variable set, or it has no suggestions.

## `homeassistant` channels

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"homeassistant"`. |
| `label` | none | The top line of the LCD until Home Assistant sets one. It also starts the names of the entities in Home Assistant (`Living fader`); without it, the id of the channel does. The entity IDs always use the id. |
| `color` | `"white"` | The LCD color until Home Assistant sets one. |

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_env = "XTOUCH_MQTT_PASSWORD"

[channel.living_room]
type = "homeassistant"   # the id is living_room: it makes number.xtouch_living_room_fader, ...
label = "Living"
color = "yellow"

[slots]
8 = "living_room"
```

The entities belong to the channel, not to a slot: they stay in Home Assistant whichever slot shows the channel, and
while none does. The list of all entities of a strip is [below](#entities).


## Audio strips with Home Assistant controls

An audio channel (a channel of the type `output`, `input`, `apps` or `auto`) can give its parts to Home Assistant (see
[Bindings](../configuration/strip/bindings.md)). If you hand over only the fader, the encoder sets the volume; if you
hand over only the encoder, the fader keeps it. Each part you hand over gets its entity of the [list below](#entities).
The Select, Rec and Solo buttons keep their audio function unless you hand them over too. Mute always keeps
muting the audio on these channels. The options are:

| Option | Entities |
|---|---|
| `encoder = "homeassistant"` | `number.<ns>_<id>_encoder`, and `event.<ns>_<id>_buttons` with `encoder_pressed`, `encoder_released`. |
| `fader = "homeassistant"` | `number.<ns>_<id>_fader`, and `event.<ns>_<id>_buttons` with `fader_touched`, `fader_released`. |
| `lcd = "homeassistant"` | `text.<ns>_<id>_bottom`: the second line of the LCD. |
| `color = "homeassistant"` | `select.<ns>_<id>_color`. |
| `meter = "homeassistant"` | `number.<ns>_<id>_meter`. |
| `select = { press = "homeassistant" }` (also `rec`, `solo`) | `event.<ns>_<id>_buttons` with `select_pressed`, `select_released`. |
| `select = { led = "homeassistant" }` (also `rec`, `solo`) | `select.<ns>_<id>_select_led`. |

A related case is a fader or an encoder of a `custom` channel that is bound to a program on this computer instead of
a light, e.g. `fader = { set = "sysctrl display redshift brightness -b {value}", min = 0.1, max = 1.0 }` (see
[Bindings](../configuration/strip/bindings.md)). With `[mqtt]`, such a part also becomes a number in Home Assistant,
from the `min` of the binding to its `max`. When Home Assistant changes the number, the daemon runs `set`, a shell
command, with the new value. On an audio channel, the parts that you do not hand over stay with PipeWire (see
[Buttons](../configuration/strip/leds.md#buttons)). A [`custom` channel](../configuration/channels/custom.md) takes
the same parts, and Mute is a button like the others there. The id of the channel names the entities, its `label`
starts their names. See [Encoders](../configuration/strip/encoders.md#homeassistant) for the details.

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"
label = "Desk"
encoder = "homeassistant"    # the fader sets the volume; the encoder is number.xtouch_desk_encoder, which an automation of yours can turn into the brightness of the desk lamp
```

## Controls of a slot

The options of a channel above hand a part over for one channel. The section
[`[controls]`](../configuration/slots.md#controls-and-the-chord) hands a control over for one slot instead: it belongs
to Home Assistant whatever channel the slot shows. You can hand over: the fader, the encoder (turn and push), the
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

A button does not switch its own LED on a Home Assistant strip: if a button should toggle something, an automation reacts to the event and sets
the LED to show the result. The broker keeps the last value that Home Assistant set (MQTT calls this a retained
message), so after a restart of the daemon the strips show it again. New entities start with the configured label and color, the fader and encoder at 0
and the LEDs off. While the broker can't be reached, a strip shows its label, `offline` and its color, and the
device does nothing on it.

Entities of a channel that was removed from the configuration are removed from Home Assistant on the next reload.

## Choices

With `[mqtt]`, an `output` or `input` channel with [`choices`](../configuration/channels/devices.md#choices) has
`select.<ns>_<id>_output` (`select.<ns>_<id>_input`): the choice the strip shows, one option per choice, named by its
`label` (or its `device`; a second choice of the same name gets a number, e.g. `Out 2`). Choosing one switches to it
like Select on the device (the sound card goes to the profile of the choice first, see [`choices`](../configuration/channels/devices.md#choices)); one that isn't there is refused and the select goes back. The select
follows the strip, also when the default changes elsewhere.

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_out_output
data:
  option: Speaker       # a choice of the channel `out`, see Choices
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

For example, an automation of Home Assistant sets the mode `gaming` while the PC runs a game (the mode is a
[mode](../configuration/slots.md#states-and-modes) you defined in `[state.gaming]`):

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_mode
data:
  option: gaming
```

## Automations

An automation that dims a light with the fader, shows its brightness on the LCD, and toggles it with Mute. It is for
the channel `living_room` of the [example above](#homeassistant-channels), and goes into your Home Assistant
configuration (`automations.yaml`, or the automation editor in YAML mode; it uses the `triggers:` and `actions:`
syntax of Home Assistant 2024.10 or later):

```yaml
automation:
  - alias: "X-Touch: fader dims the living room"
    mode: queued          # handle every change in turn, none is dropped while a run is busy
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
