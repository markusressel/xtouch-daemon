# History: layouts

Status: replaced by [channels, states and slots](../design/slots/index.md) before 0.1.0. What stays of it: the research
below, and the [voice chat](../design/voice-chat.md), which was designed with it.

The idea: several **layouts**, each a set of up to 8 strips (`[[layout]]` with `[[layout.strip]]`; the top-level
`[[strip]]` list was the layout `default`). One was active; rules (`apps`, `processes`, `priority`) picked it,
edge-triggered with a `hold`, and Home Assistant (`select.<ns>_layout`), the command line (`xtouch-daemon layout`),
the GUI (a tab per layout) and the Solo chord switched by hand. A switch was a reload with another set of strips on
the same surface, with a banner across the LCDs. `inherit` strips took the strip of another layout at their place;
`voip` strips without `person` formed a group that paged through the participants with Select.

What carried over: edge-triggered rules and a manual choice that lasts until they change (now the overrides of
modes), the banner, the chord, the remembered choice, `voice_chat` and the people.

What didn't work: a strip that matters in two situations needed two layouts that can't both be active; `inherit`
referred to positions, so moving a strip changed what it meant. See [why](../design/slots/index.md#why).

## What others do

| Product | Unit | How it switches | Notes |
|---|---|---|---|
| Elgato Stream Deck | profile, with pages and folders | "Smart Profiles": the application in focus picks its profile, matched by executable; leaving it restores the previous profile. A key action switches by hand. ([Elgato][elgato]) | Automatic switching is paused while the editor is open. A manual switch by a plugin can disable the automatic one ([bug report][sd-bug]), a known pain point. |
| Loupedeck / Logitech | profile per application, with workspaces and pages | "Dynamic mode" (on by default) follows the active application; off, the chosen profile stays. A button switches workspaces. ([Loupedeck CT][loupedeck], [user guide][loupedeck-guide]) | Open-source Linux ports match by process name and window title, falling back to a default profile ([loupedeckapp][loupedeckapp]). |
| GoXLR Utility (Linux) | device and microphone profiles | UI, and `goxlr-client profiles device load <name>` for scripts and hotkeys ([wiki][goxlr]) | The profile is a whole mixer state; a "load colours only" variant exists. |
| Mackie Control DAWs (Logic, Cubase) | banks of 8 channels | Bank Left/Right moves by 8 (by the size of the surface group), Channel Left/Right by 1; the last bank is filled up to 8 rather than left half empty ([Logic][logic-banks]) | The model for "more participants than strips". |
| deej | one configuration | none; the file is reloaded on change | (From the project's README, not re-checked.) |
| Voicemeeter | settings files, macro buttons | macro buttons and the Remote API load a settings file | (From memory, not re-checked.) |
| TouchOSC | pages (tabs) of one layout | a tab bar on the surface, or OSC/MIDI messages | (From memory, not re-checked.) |

Lessons taken:

1. **One active layout, switched as a whole.** Every product swaps the complete set of controls; nobody blends two.
2. **Automatic and manual switching coexist, and the rules for that must be simple.** Stream Deck and Loupedeck make
   the automatic one win whenever the focus changes; a manual choice lasts until the next change. That was the
   model here too: rules are *edge-triggered*.
3. **Focus is a desktop concept.** On Wayland there is no portable way to ask which window has the focus (KWin
   scripts, GNOME extensions, the Sway/Hyprland IPC all differ). The daemon knows something better for a mixer: which
   applications **play** (PipeWire streams), and which processes **run** (`/proc`). Focus can come later as a
   provider of the same rule engine.
4. **A command line to switch** (GoXLR) makes every other integration (hotkeys, scripts, desktop launchers) free.
5. **Banks for variable lists** (Mackie): a group of strips shows a page of a longer list, and buttons page through it.

[elgato]: https://www.elgato.com/us/en/explorer/products/stream-deck/smart-profiles-stream-deck/
[sd-bug]: https://github.com/Miracle4142/streamdeck-bug-report-switch-to-profile-event
[loupedeck]: https://loupedeck.com/products/loupedeck-ct/
[loupedeck-guide]: https://f.hubspotusercontent40.net/hubfs/5145542/Knowledge%20Base/Profile%20Downloads/LOUPEDECK_LIVE_USER_GUIDE_v4.2.5.pdf
[loupedeckapp]: https://github.com/ascendedent/loupedeckapp
[goxlr]: https://github.com/GoXLR-on-Linux/goxlr-utility/wiki/The-CLI-and-AutoHotkey
[logic-banks]: https://support.apple.com/guide/logicpro-css/bank-buttons-ctls72224042/mac
