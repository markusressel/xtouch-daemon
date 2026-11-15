# Configuration

xtouch-daemon reads a TOML file, by default `~/.config/xtouch-daemon/config.toml` (`$XDG_CONFIG_HOME` is respected).
`-c FILE` selects another one. Without a file at the default path it uses the
[example configuration](../src/xtouch_daemon/config.example.toml): six `auto` strips, the default input and the
default output.

```shell
xtouch-daemon init-config      # writes the example to the default path (-f overwrites)
xtouch-daemon check-config     # validates the file and lists what each strip does
```

Unknown options are errors, so a typo does not go unnoticed. `check-config` names the place of every error, e.g.
`strip[3].label: String should have at most 7 characters`.

`xtouch-daemon gui` (with the `gui` extra, see the [README](../README.md#gui)) edits the same options in a window. It
shows the same errors next to the options, keeps the comments of the file when it saves, and applies the file as
described below: it reloads the running daemon (the service, or one started from a terminal or an IDE), or offers a
restart for a changed `[device]` or `[mqtt]` section. It then tells whether the daemon took the file: a reload keeps
the old configuration when the new one can't be used.

## Applying changes

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

A reload (SIGHUP) builds the strips from the new file without a restart. A file with errors is reported in the log
and the current configuration stays. A changed `[device]` section needs a restart
(`systemctl --user restart xtouch-daemon`). So does a changed `[mqtt]` section: until then, a reload keeps the
current configuration.

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the extender's sound card, as `/proc/asound/cards` lists it. |

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `100` | The volume of a fader at the top, 100..150 percent. Above 100 % the audio is amplified in software. |
| `encoder_step` | `1` | Percent per encoder step, 1..10. |
| `reset_volume` | `100` | The volume a push on an encoder sets, 0..150, at most `max_volume`. |
| `meters` | `true` | Whether the LED meters show audio levels at all. |
| `auto_hold` | `5` | Seconds an `auto` strip keeps an application after it stopped playing. |
| `ignore` | `["speech-dispatcher"]` | Applications `auto` strips never take: parts of the name or binary, ignoring case. |

## `[aliases]`

The name to show on an `auto` strip for an application, at most 7 characters:

```toml
[aliases]
"WEBRTC VoiceEngine" = "Discord"
"Firefox" = "Firefox"
```

The key is the application name the sound server reports. `xtouch-daemon list-apps` shows it.

## `[mqtt]`

The MQTT broker of Home Assistant, needed by [`homeassistant` strips](#type--homeassistant). Without
`homeassistant` strips the section is optional; with it, the daemon connects anyway and shows the device in Home
Assistant.

| Option | Default | Meaning |
|---|---|---|
| `host` | required | The broker, e.g. `"homeassistant.local"`. |
| `port` | `1883` | Its port. |
| `username` | none | The user to log in as. |
| `password` | none | The password, in the file. |
| `password_file` | none | A file that holds the password instead, e.g. one only you can read. Surrounding whitespace is ignored. |
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

The entities are available in Home Assistant while the daemon runs and the device is connected; otherwise they are
greyed out (a last will covers a crash).

## `[[strip]]`

Up to eight, from the left. Strips that are not configured are `auto` strips.

Options of every strip type except `empty`:

| Option | Default | Meaning |
|---|---|---|
| `color` | `"white"` | The LCD backlight: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. |
| `meter` | `true` | Whether this strip's LED meter shows the level (if `behavior.meters` is on). |
| `rec` | `"recording"` | What the LED of the Rec button shows, see below. |
| `solo` | `"off"` | What the LED of the Solo button shows, see below. |

Labels are at most 7 characters of ASCII: that is what fits on the LCD.

The Rec and Solo LEDs are indicators; their buttons do nothing. Each shows one of:

| Indicator | Lit while |
|---|---|
| `recording` | An application records: from the input, from the monitor of the output (e.g. a screen recorder), or for `apps`/`auto` strips, the application records anything (e.g. Discord using a microphone). Level meters don't count: the daemon's own, pavucontrol's. |
| `playing` | Audio flows: the device runs, or a stream of the applications plays. |
| `default` | The device is the default output/input. Never for applications. |
| `muted` | The strip is muted (like the Mute LED). |
| `off` | Never. |

```toml
[[strip]]
type = "input"
label = "Mic"
rec = "recording"   # the default: lit while an application uses the microphone
solo = "default"
```

### `type = "output"` / `type = "input"`

A device: an output (a sink) or an input (a source).

| Option | Default | Meaning |
|---|---|---|
| `device` | the default device | The node name (`xtouch-daemon list-devices`) or the description of the device, or a list of them; `*` is a wildcard. Without it, the strip follows whatever device is the default. |
| `label` | `"Output"` / `"Input"`, or the start of the device's description | The top line of the LCD. |
| `select` | `true` | Whether Select makes the device the default. Needs `device`. |
| `profiles` | none | Profiles of the device's sound card that Rec switches between, see below. |

```toml
[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[[strip]]
type = "input"          # the default input
label = "Mic"
color = "red"

[[strip]]
type = "output"
device = ["bluez_output.*"]   # whichever Bluetooth headphones are connected
color = "green"
```

With several devices, the strip shows one of those that are there: the default one, or else the one it showed last.
Select makes it the default; pressed on the default one, it switches to the next one that is there and makes that the
default. Without `label`, the LCD shows which one it is.

#### Profiles: analog or digital output

A sound card has profiles that decide which devices it has, e.g. analog or digital (S/PDIF, IEC958) output. Each
profile has a device of its own, so name `device` with a wildcard that matches all of them. With `profiles`, Rec
switches the card to the next one:

```toml
[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.*"   # the analog and the digital output of the card
label = "Speaker"
profiles = [
  { label = "Analog", profile = "output:analog-stereo+input:analog-stereo" },
  { label = "Digital", profile = "output:iec958-stereo+input:analog-stereo" },
]
```

- `label`: what the LCD shows for 2 s after a switch (7 characters).
- `profile`: the name or the description of the profile. `xtouch-daemon list-devices` lists the profiles of each card.
- The Rec LED is on for every profile but the first, so it can't show an indicator (`rec`) here.
- If the old device was the default, the new one becomes the default.
- Each device has its own volume: the fader moves to the volume of the new one.
- A card in a profile that isn't in the list switches to the first one.

| Element | Function |
|---|---|
| Fader | Sets the volume, 0 at the bottom to `max_volume` at the top. Follows changes made elsewhere. |
| Encoder | Changes the volume by `encoder_step` per step; the fader follows. |
| Encoder push | Sets `reset_volume`. |
| Mute | Toggles mute. The LED is on while the device is muted. |
| Rec | With `profiles`: switches the sound card to the next profile. The LED is on for every profile but the first. |
| Select | With `device` and `select`: makes the device the default output/input, or switches to the next of several. The LED is on while it is the default. |
| LCD | Top: the label. Bottom: the volume, or `muted`. |
| Ring | The volume. |
| Meter | The level: what plays on an output, what an input records. |

A device that is not there (e.g. Bluetooth headphones that are switched off) shows `off` on a dark LCD. Its fader goes
down, and the fader and buttons do nothing until it is back.

Use the node name for a device that is both an output and an input under one description, e.g. Bluetooth headphones
with a microphone. A description matches only devices of the strip's direction, but a node name is unambiguous and
stays the same across restarts.

### `type = "apps"`

All playback streams of a group of applications.

| Option | Default | Meaning |
|---|---|---|
| `match` | required | Parts of application names or binaries, ignoring case. |
| `label` | required | The top line of the LCD. |

```toml
[[strip]]
type = "apps"
match = ["discord", "webrtc", "teamspeak", "mumble"]
label = "VoIP"
color = "white"
```

A stream belongs to the strip when its application name (`application.name`) or binary
(`application.process.binary`) contains one of the `match` entries. `"wine"` matches `wine64-preloader`, `".exe"`
matches Windows games under Proton. `xtouch-daemon list-apps` shows the names and binaries of the applications that
play, and which strip takes each one. A stream can belong to several `apps` strips.

| Element | Function |
|---|---|
| Fader | Sets every stream of the group to the same volume. A stream that starts later gets that volume too. Shows the loudest stream. |
| Encoder | Changes the volume by `encoder_step` per step. |
| Encoder push | Sets `reset_volume` for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The LED is on while all are muted. |
| Select | Nothing. |
| LCD | Top: the label. Bottom: the volume, `muted`, or `idle` while no stream of the group is there. |
| Ring | The volume. |
| Meter | The level of all streams of the group together. |

While no stream of the group is there (e.g. the application was closed), the LCD is dark and shows `idle`, and the
fader glides slowly to the bottom and does nothing. The strip keeps its volume: when a stream comes back, the fader
goes up to it and the stream gets it.

The strip changes the volume of the streams themselves, like the per-application sliders in pavucontrol, so it needs
no setup in PipeWire.

### `type = "auto"`

The next application that plays and has no strip of its own.

```toml
[[strip]]
type = "auto"
color = "cyan"
```

How `auto` strips get their applications:

- An application qualifies while at least one of its streams plays (is not paused).
- Applications that an `apps` strip matches, and applications in `behavior.ignore`, never go to `auto` strips.
- Free `auto` strips take new applications from the left, in the order the applications started.
- An application keeps its strip while it plays, and for `behavior.auto_hold` seconds after it stopped. Then the strip
  is free again. This way a music player does not jump to another strip between two tracks.
- The label is the application's alias from `[aliases]`, or its name.
- A newly assigned application keeps its own volume.

An `auto` strip works like an `apps` strip for its application. Without an application it is dark, blank, and does
nothing.

### `type = "homeassistant"`

A strip that belongs to Home Assistant instead of PipeWire: every part of it is an entity there, and automations
decide what it does, e.g. the fader dims a light, the encoder sets the volume of a speaker in another room, a button
toggles a scene. Needs the [`[mqtt]`](#mqtt) section.

**PipeWire or Home Assistant?** Each strip has one owner, chosen by its `type`. The PipeWire types (`output`,
`input`, `apps`, `auto`) control audio on this computer and need nothing else. A `homeassistant` strip controls
nothing by itself; it only reports what happens on it and shows what Home Assistant sets. Nothing in between: a
fader that both set a PipeWire volume and were moved by Home Assistant would fight over the motor. So give audio on
this computer PipeWire strips, and everything else (lights, other speakers, scenes) `homeassistant` strips.

| Option | Default | Meaning |
|---|---|---|
| `id` | `"strip_<position>"` | Part of the entity IDs. Set it to keep the entities (and the automations that use them) when moving the strip. Lower case letters, digits, `_`. |
| `label` | none | The top line of the LCD until Home Assistant sets one, and the start of the entity names (`Strip <position>` without it). |
| `color` | `"white"` | The LCD color until Home Assistant sets one. |

The entities (`<ns>` is `mqtt.namespace`, `<id>` the strip's `id`):

| Entity | What it is |
|---|---|
| `number.<ns>_<id>_fader` | The fader, 0..100 in steps of 0.1. Setting it moves the motor fader; moving the fader by hand sets it (at most every 100 ms while it moves, and where it was let go). |
| `number.<ns>_<id>_encoder` | The encoder, 0..100. The ring shows it; turning the encoder changes it by `behavior.encoder_step` per step. |
| `text.<ns>_<id>_top`, `text.<ns>_<id>_bottom` | The two lines of the LCD, 7 characters each. |
| `select.<ns>_<id>_color` | The LCD color: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. |
| `select.<ns>_<id>_rec_led`, `_solo_led`, `_mute_led`, `_select_led` | The LEDs of the buttons: `off`, `on` or `flash`. |
| `event.<ns>_<id>_buttons` | What happens on the strip: `rec_pressed`, `rec_released`, `solo_…`, `mute_…`, `select_…`, `encoder_pressed`, `encoder_released`, `fader_touched`, `fader_released`. |

A button does not switch its LED: if a button should toggle something, an automation reacts to the event and sets
the LED to show the result. Home Assistant keeps what it set last (retained on the broker), so after a restart of the
daemon the strips show it again. New entities start with the configured label and color, the fader and encoder at 0
and the LEDs off. While the broker can't be reached, a strip shows its label, `offline` and its color, and the
device does nothing on it.

```toml
[[strip]]
type = "homeassistant"
id = "living_room"
label = "Living"
color = "yellow"
```

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
```

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

### `type = "empty"`

A dark strip that does nothing. Its fader stays at the bottom. It has no options besides `type`.

## Complete example

```toml
[behavior]
max_volume = 100
encoder_step = 2
auto_hold = 10
ignore = ["speech-dispatcher", "notification"]

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[[strip]]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
label = "Buds"
color = "green"

[[strip]]
type = "input"
label = "Mic"
color = "red"

[[strip]]
type = "apps"
match = ["brave", "firefox"]
label = "Browser"
color = "yellow"

[[strip]]
type = "apps"
match = ["steam", "wine", "proton", ".exe"]
label = "Games"
color = "magenta"

[[strip]]
type = "empty"

# strips 7 and 8 are not configured: they are "auto" strips
```
