# Home Assistant

A `homeassistant` strip belongs to Home Assistant instead of PipeWire: every part of it is an entity there, and
automations decide what it does. For example, the fader dims a light, the encoder sets the volume of a speaker in
another room, a button toggles a scene. The daemon reaches Home Assistant over MQTT discovery, so it needs the
[`[mqtt]`](#mqtt) section.

## PipeWire or Home Assistant?

Each control has one owner. The PipeWire types (`output`, `input`, `apps`, `auto`) control audio on this computer
and need nothing else. A `homeassistant` strip controls nothing by itself; it only reports what happens on it and
shows what Home Assistant sets. In between, an audio strip can hand its fader or its encoder to Home Assistant and keep
the other one for the volume, see [below](#audio-strips-with-home-assistant-controls). Never both on one control: a
fader that both set a PipeWire volume and were moved by Home Assistant would fight over the motor.

## `[mqtt]`

The MQTT broker of Home Assistant, e.g. the Mosquitto add-on. Without `homeassistant` strips the section is optional;
with it, the daemon connects anyway and shows the device in Home Assistant.

| Option | Default | Meaning |
|---|---|---|
| `host` | required | The broker, e.g. `"homeassistant.local"`. |
| `port` | `1883` | Its port. |
| `username` | none | The user to log in as. |
| `password` | none | The password, in the file. |
| `password_file` | none | A file that holds the password instead, e.g. one only you can read. `~` is the home directory. Surrounding whitespace is ignored. |
| `password_env` | none | An environment variable that holds the password instead, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). |
| `discovery_prefix` | `"homeassistant"` | Home Assistant's MQTT discovery prefix. |
| `namespace` | `"xtouch"` | Starts every entity ID (`number.xtouch_strip_5_fader`) and is part of the topics. Lower case letters, digits, `_`. |
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

The [GUI](gui.md#live-view-and-preview) shows whether the daemon is connected, and why not (e.g. a wrong password),
and its "Test connection" button tries settings before they are saved.

## `homeassistant` strips

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"homeassistant"`. |
| `id` | `"strip_<position>"` | Part of the entity IDs. Set it to keep the entities (and the automations that use them) when moving the strip. Lower case letters, digits, `_`, at most 64 characters. Unique among the strips. |
| `label` | none | The top line of the LCD until Home Assistant sets one, and the start of the entity names (`Strip <position>` without it). |
| `color` | `"white"` | The LCD color until Home Assistant sets one. |

```toml
[mqtt]
host = "homeassistant.local"
username = "xtouch"
password_env = "XTOUCH_MQTT_PASSWORD"

[[strip]]
type = "homeassistant"
id = "living_room"
label = "Living"
color = "yellow"
```

## Audio strips with Home Assistant controls

An `output`, `input`, `apps` or `auto` strip with `encoder = "homeassistant"` or `fader = "homeassistant"` keeps the
volume on the other control and gets these entities of the [list below](#entities):

| Option | Entities |
|---|---|
| `encoder = "homeassistant"` | `number.<ns>_<id>_encoder`, and `event.<ns>_<id>_buttons` with `encoder_pressed`, `encoder_released`. |
| `fader = "homeassistant"` | `number.<ns>_<id>_fader`, and `event.<ns>_<id>_buttons` with `fader_touched`, `fader_released`. |

The LCD, the LEDs and the buttons stay with PipeWire. `id` names the entities as for `homeassistant` strips
(`strip_<position>` by default: the position in the list of the file, not on the device, which differs with
[collapsing strips](configuration/collapsing.md#home-assistant)), and the strip's `label` starts their names. See
[Encoders](configuration/encoders.md#homeassistant) for the details.

```toml
[[strip]]
type = "output"
device = "alsa_output.usb-*"
label = "Desk"
id = "desk"
encoder = "homeassistant"    # the fader sets the volume, the encoder dims the desk lamp
```

## Entities

`<ns>` is `mqtt.namespace`, `<id>` the strip's `id`:

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

Entities of a strip that was removed from the configuration are removed from Home Assistant on the next reload.
The entities of the strips of every [layout](configuration/layouts.md) stay while another layout is shown.

## Choices

With `[mqtt]`, an `output` or `input` strip with [`choices`](configuration/devices.md#choices) has
`select.<ns>_<id>_output` (`select.<ns>_<id>_input`): the choice the strip shows, one option per choice, named by its
`label` (or its `device`; a second choice of the same name gets a number, e.g. `Out 2`). Choosing one switches to it
like Select on the device, profile first; one that isn't there is refused and the select goes back. The select
follows the strip, also when the default changes elsewhere.

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_strip_1_output
data:
  option: Speaker
```

## Layouts

With `[mqtt]` and more than one [layout](configuration/layouts.md), the daemon has `select.<ns>_layout`: the layout
the device shows, one option per layout. Choosing one switches to it, like `xtouch-daemon layout`; the select follows
every switch, also by a rule or the Solo chord, and after a restart of the daemon it shows the layout the daemon
started with (see [Switching](configuration/layouts.md#switching)), not the one Home Assistant had last. For example, the gaming layout while the PC runs a game in another
room's automation:

```yaml
action: select.select_option
target:
  entity_id: select.xtouch_layout
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

## haad

The same as a [haad](https://github.com/markusressel/haad) controller (a sketch: the entity wrappers are haad's, the
names depend on your setup):

```python
@haad_controller(registry_name="xtouch_living_room")
class XTouchLivingRoom(HaadController):
    @haad_ha_entity
    def fader(self) -> HANumber:
        return HANumber("number.xtouch_living_room_fader")

    @haad_ha_entity
    def encoder(self) -> HANumber:
        return HANumber("number.xtouch_living_room_encoder")

    @haad_ha_entity
    def buttons(self) -> HAEventEntity:
        return HAEventEntity("event.xtouch_living_room_buttons")

    @haad_ha_entity
    def light(self) -> HALight:
        return HALight("light.living_room")

    @haad_ha_entity
    def speaker(self) -> HAMediaPlayer:
        return HAMediaPlayer("media_player.living_room")

    async def initialize(self) -> None:
        async def dim() -> None:
            # turn_on() of HALight does nothing for a light that is on: set the brightness directly
            brightness = await self.fader.get_state()
            await self.ha.perform_action("light/turn_on", entity_id=self.light.entity_id, brightness_pct=brightness)

        async def volume() -> None:
            await self.speaker.volume_set(await self.encoder.get_state() / 100)

        async def button() -> None:
            if await self.buttons.get_event_type() == "mute_pressed":
                await self.light.toggle()

        await self.react_to(trigger=self.fader, action=dim)
        await self.react_to(trigger=self.encoder, action=volume)
        await self.react_to(trigger=self.buttons, action=button)
```
