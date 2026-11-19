# Development

How the daemon works inside and why. To set up the project and run the tests, see
[Contributing](https://github.com/markusressel/xtouch-daemon/blob/main/CONTRIBUTING.md); to make a release,
[Releasing](https://github.com/markusressel/xtouch-daemon/blob/main/RELEASING.md).

- **[Architecture](architecture/index.md)**: the modules, the data flow and the lifecycle, then [Audio](architecture/audio.md)
  (the meters), [Live view](architecture/live-view.md) (the GUI's socket and the live preview), [GUI](architecture/gui.md)
  and [Testing](architecture/testing.md).
- **Design documents**: why a feature works as it does, as it is now.
- **History**: designs that were replaced, kept for their reasons and research.

## Design documents

| Design | Status |
|---|---|
| [Channels, states and slots](design/slots/index.md) | Built (0.1.0) |
| [Where the people sit](design/slots/people.md) | Built (0.1.0) |
| [Previews, in the GUI or on the device](design/previews.md) | Built, not released |
| [A simulated device](design/device-simulator.md) | Built (0.1.0) |
| [Previews of the controls](design/control-previews.md) | Built (0.1.0) |
| [Output choices](design/choices.md) | Built (0.1.0) |
| [Launching applications](design/launch.md) | Built (0.1.0) |
| [Presets](design/presets.md) | Built (0.1.0) |
| [The voice chat](design/voice-chat.md) | Built (0.1.0) |
| [An interactive device test](design/interactive-test.md) | Designed, not built |

## History

| Document | Replaced by |
|---|---|
| [Channels, states and slots](history/slots.md): how it was built, the migration, the reviews | Its [design](design/slots/index.md) |
| [Layouts](history/layouts.md) | Channels, states and slots |
| [Strips that move](history/dynamic-strips.md) | Channels, states and slots; [output choices](design/choices.md) stay |
| [Refactoring, November 2026](history/refactoring-2026-11.md) | Done |
| [Try changes and situations on the device](history/try-and-simulate.md) | [Previews](design/previews.md) |
| [The virtual twin](history/virtual-twin.md) | [Previews](design/previews.md) |

A new design goes into `design/` with a status line at the top, into the table above and into `nav` of
`zensical.toml`; when it is replaced, it moves to `history/`, shortened to what still explains something.
