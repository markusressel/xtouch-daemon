# Home Assistant

[Home Assistant](https://www.home-assistant.io/) is a home automation program. An *entity* is one thing in it, such
as the light `light.desk`. There are three ways to connect the control surface to it:

| You want | Use | Needs |
|---|---|---|
| A strip that does nothing by itself: your automations decide what it does (the fader dims a light, a button toggles a scene) | A [`homeassistant` channel](#homeassistant-channels): an entity for every part of the strip, which an automation reacts to. | The [`[mqtt]`](#mqtt) section |
| A strip whose parts are tied straight to an entity that Home Assistant has, with no automation | A [binding](../configuration/strip/bindings.md#an-entity-of-home-assistant) such as `fader = { entity = "light.desk" }`, on any channel, e.g. a `custom` channel (a strip you build part by part). | The [`[homeassistant]`](#homeassistant) section, with a token |
| An audio strip that keeps the volume on one control and hands the other to Home Assistant | `encoder = "homeassistant"` or `fader = "homeassistant"` on an audio channel, see [below](#audio-strips-with-home-assistant-controls). | The [`[mqtt]`](#mqtt) section |

The first and the third way use *entities of the daemon*: the daemon creates them in Home Assistant (e.g.
`number.xtouch_living_room_fader`) through the MQTT broker (the program that passes messages between them), by
*MQTT discovery*: Home Assistant finds them without any setup on its side. All ways need a
[slot](../configuration/slots.md) that shows the channel, as in the examples below.

Each control has one owner, PipeWire or Home Assistant. A `homeassistant` channel controls nothing by itself: it
reports what happens on its controls (as an *event*, a message such as "this button was pressed", see
[Entities](#entities)) and shows what Home Assistant sets.

!!! warning "Never both on one control"

    If a fader set a PipeWire volume and Home Assistant moved it too, the two would fight over the motor of the fader.

## `[mqtt]`

The MQTT broker of Home Assistant, e.g. the Mosquitto add-on. You need the section for `homeassistant` channels,
`"homeassistant"` as the value of a part or control, and `homeassistant = true` on a state. Without those it is
optional; with it, the daemon also shows the control surface, its modes, states and slots in Home Assistant.

| Option | Default | Meaning |
|---|---|---|
| `host` | required | The broker, e.g. `"homeassistant.local"`. |
| `port` | `1883` | Its port. |
| `username` | none | The user to log in as. |
| `password` | none | The password, in the file. |
| `password_file` | none | A file that holds the password instead, e.g. one only you can read. `~` is the home directory. |
| `password_env` | none | An environment variable that holds the password instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |
| `discovery_prefix` | `"homeassistant"` | Home Assistant's MQTT discovery prefix. |
| `namespace` | `"xtouch"` | Starts every entity ID (`number.xtouch_living_room_fader`) and is part of the MQTT topics. Lower case letters, digits, `_`. |
| `device_name` | `"X-Touch Extender"` | The name of the control surface in Home Assistant, where it is one Home Assistant device with all the entities. |

Set at most one of `password`, `password_file` and `password_env`. A password file that can't be read, or a
variable that is not set, stops the daemon at the start.

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_file = "~/.config/xtouch-daemon/mqtt-password"
```

A changed `[mqtt]` section needs a restart of the daemon (`systemctl --user restart xtouch-daemon`): a reload keeps
the whole configuration it runs, also the changes in other sections, until then.

Home Assistant greys the entities out while the daemon is not running or the control surface is not connected, also after a
crash (the broker tells Home Assistant, by an MQTT "last will"). The daemon connects to the broker again by itself.

The [GUI](gui.md#live-view) shows whether the daemon is connected, and why not (e.g. a wrong password); its "Test
connection" button tries settings before they are saved. To check it by hand, open Settings → Devices & services →
MQTT in Home Assistant: the Home Assistant device "X-Touch Extender" (`device_name`) is listed there with its entities.

## `[homeassistant]`

The API of Home Assistant, for parts bound to entities that Home Assistant has (`{ entity = "..." }` and
`{ service = "..." }`, see [Bindings](../configuration/strip/bindings.md#an-entity-of-home-assistant)). The daemon
connects only while the configuration has such parts. It needs no `[mqtt]` section.

| Option | Default | Meaning |
|---|---|---|
| `url` | required | The address of Home Assistant, as in the browser, e.g. `"http://homeassistant.local:8123"` (or `https://...`). |
| `token` | none | A long-lived access token, in the file. |
| `token_file` | none | A file that holds the token instead, e.g. one only you can read. `~` is the home directory. |
| `token_env` | none | An environment variable that holds the token instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |

Set exactly one of `token`, `token_file` and `token_env`. To make a token:

1. In Home Assistant, click your user name at the bottom left (your profile) and open the **Security** tab.
2. Under **Long-lived access tokens**, select **Create token**, name it `xtouch-daemon`, and copy it: Home
   Assistant shows it only once.
3. Put it into a file only you can read, and name the file in `token_file`:

```shell
install -m 600 /dev/null ~/.config/xtouch-daemon/homeassistant-token
$EDITOR ~/.config/xtouch-daemon/homeassistant-token
```

(`~/.config/xtouch-daemon/` is the directory of `config.toml`; create it with `mkdir -p` if it does not exist.) Then
add this to `config.toml`. The fader sets the brightness of the light `light.desk`, Select toggles it, and the
Select LED shows whether it is on:

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
Home Assistant (Settings → People → Users) limits that.

| When | The daemon |
|---|---|
| You save the file with a changed section | Reloads and connects again. No restart is needed (but a new token in the variable of `token_env` takes a restart of the service). |
| The connection breaks | Tries again by itself, with longer waits (at most 60 seconds). Meanwhile the parts show nothing. |
| Home Assistant refuses the token | Logs an error and stops trying, because Home Assistant can ban an address after failed logins. Make a new token, put it where the section reads it, and save the file. |
| It can't read `token_file`, or `token_env` is not set | Logs an error and runs without the connection. Save the file again once there is a token. |

The log (View → Log in the [GUI](gui.md)) says when the daemon connects and why it can't. The GUI page "Home
Assistant API" tests the settings before you save them, and its entity fields suggest the entities of Home Assistant
(see [the GUI](gui.md#suggestions-from-home-assistant)). With `token_env`, start the GUI with that variable set, or
it has no suggestions.

## `homeassistant` channels

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"homeassistant"`. |
| `label` | none | The top line of the LCD until Home Assistant sets one. It also starts the names of the entities in Home Assistant (`Living fader`); without it, the id of the channel does. The entity IDs always use the id. |
| `color` | `"white"` | The LCD color until Home Assistant sets one. |

```toml
[channel.living_room]
type = "homeassistant"   # the id is living_room: it makes number.xtouch_living_room_fader, ...
label = "Living"
color = "yellow"

[slots]
8 = "living_room"
```

The entities belong to the channel, not to a slot: they stay in Home Assistant whichever slot shows the channel, and
while none does. All entities of a strip are listed in [Entities](#entities).

## Audio strips with Home Assistant controls

An audio channel (of the type `output`, `input` or `apps`) can hand parts to Home Assistant by setting them
to `"homeassistant"` (see [Bindings](../configuration/strip/bindings.md#home-assistant)). Hand over only the fader,
and the encoder sets the volume; hand over only the encoder, and the fader keeps it. The Select, Rec and Solo buttons
keep their audio function unless you hand them over too (`select = { press = "homeassistant" }` or
`select = { led = "homeassistant" }`, also `rec` and `solo`); Mute always mutes. Each part you hand over gets its
entity of the [list below](#entities). A fader or an encoder of a `custom` channel that is bound to a program of
your own becomes a number in Home Assistant too; when Home Assistant changes it, the daemon runs `set`. See
[Encoders](../configuration/strip/encoders.md#homeassistant).

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-*"
label = "Desk"
encoder = "homeassistant"    # the fader sets the volume; the encoder is number.xtouch_desk_encoder
```

## Controls of a slot

The section [`[controls]`](../configuration/slots.md#controls-and-the-chord) hands a control over for one slot instead
of one channel: it belongs to Home Assistant whatever channel the slot shows. You can hand over the fader, the
encoder, the Select, Rec and Solo buttons, the meter, the color and the second line of the LCD. The entities are named
by the slot (`number.xtouch_slot_6_fader`), or by `id`:

```toml
[controls]
6 = { fader = "homeassistant", id = "desk" }      # number.xtouch_desk_fader
4 = { encoder = "homeassistant" }                 # number.xtouch_slot_4_encoder
```

## Entities

`<ns>` is `mqtt.namespace` (`xtouch` by default), `<id>` the id of the channel (`desk` for `[channel.desk]`), or for a
control of a slot its `id` or `slot_<n>`. The id of the channel names the entities, its `label` starts their names.

| Part (option) | Entity | What it is |
|---|---|---|
| `fader = "homeassistant"` | `number.<ns>_<id>_fader` | The fader, 0..100 in steps of 0.1. Setting it moves the motor fader; moving it by hand sets it. Starts at 0. |
| `encoder = "homeassistant"` | `number.<ns>_<id>_encoder` | The encoder, 0..100. The ring shows it; a turn changes it by `behavior.encoder_step`. Starts at 0. |
| `meter = "homeassistant"` | `number.<ns>_<id>_meter` | The LED meter, 0..100 %: 0 is dark, 100 lights it fully, and the level stays until you set another. Starts at 0. |
| `lcd = "homeassistant"` | `text.<ns>_<id>_top`, `text.<ns>_<id>_bottom` | The two lines of the LCD, 7 characters each. The second line is the part `lcd`. |
| `color = "homeassistant"` | `select.<ns>_<id>_color` | The LCD color: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. Starts with the `color` of the channel. |
| `led = "homeassistant"` of a button | `select.<ns>_<id>_rec_led`, `_solo_led`, `_mute_led`, `_select_led` | The LEDs of the buttons: `off`, `on` or `flash`. Start `off`. |
| `press = "homeassistant"` of a button, `encoder`, `fader` | `event.<ns>_<id>_buttons` | What happens on the strip: `rec_pressed`, `rec_released`, `solo_…`, `mute_…`, `select_…`, `encoder_pressed`, `encoder_released`, `fader_touched`, `fader_released`. |

A button does not switch its own [LED](../configuration/strip/leds.md) on a Home Assistant strip: an automation reacts to the event and sets the LED to
show the result. The broker keeps the last value that Home Assistant set (an MQTT *retained message*), so after a
restart of the daemon the strips show it again. While the broker can't be reached, a strip shows its label,
`offline` and its color, and the control surface does nothing on it.

Entities of a channel that was removed from the configuration are removed from Home Assistant on the next reload.

## Choices

With `[mqtt]`, an `output` or `input` channel with [`choices`](../configuration/channels/devices.md#choices) has
`select.<ns>_<id>_output` (`select.<ns>_<id>_input`): the choice the strip shows, one option per choice, named by its
`label` (or its `device`; a second choice of the same name gets a number, e.g. `Out 2`). Choosing one switches to it
like Select on the control surface; one that isn't there is refused and the select goes back. The select follows the strip,
also when the default changes elsewhere.

## States, modes and slots

With `[mqtt]`, Home Assistant sees and sets the [states and modes](../configuration/slots.md#states-and-modes):

| Entity | What it is |
|---|---|
| `select.<ns>_mode` | The mode picked by hand, or `auto` for the rules. Choosing one picks it, like `xtouch-daemon mode`. |
| `binary_sensor.<ns>_state_<id>` | Each state and mode, with the attributes `since`, `source` and `override`. |
| `select.<ns>_state_<id>` | The override of each state that is no mode: `auto`, `on`, `off`. |
| `switch.<ns>_state_<id>_input` | For states with `homeassistant = true`: what Home Assistant feeds into them. |
| `binary_sensor.<ns>_<id>_shown` | Whether a channel is on a slot. |
| `sensor.<ns>_slot_<n>` | What slot n shows (a channel id, `app:<name>`, `person:<name>` or `none`), with `label`, `kind`, `via` and `reason`. |

For example, an automation sets the mode `gaming` (defined in `[state.gaming]`) while the PC runs a game:

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_mode
data:
  option: gaming
```

## Automations

These automations are for the channel `living_room` of the [example above](#homeassistant-channels). They go into
`configuration.yaml` (in `automations.yaml` or the automation editor, leave out the line `automation:`) and use the `triggers:` and `actions:` syntax of Home
Assistant 2024.10 or later. The fader dims a light and shows its brightness on the LCD, and Mute toggles it:

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
```

To react to the entities from code, see [As a haad controller](../development/haad-controller.md).

Next: [Slots](../configuration/slots.md#controls-and-the-chord) (controls of a slot), [Troubleshooting](troubleshooting.md#home-assistant).
