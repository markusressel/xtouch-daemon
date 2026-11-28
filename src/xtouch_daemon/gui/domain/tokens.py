"""
The design tokens (spacing, radii, type scale) and the colors of both themes and of the hardware.

Every text color is chosen for a contrast of at least 4.5:1 (WCAG 2.2 AA) on the surfaces it is used on, and the
outlines of controls for at least 3:1, in both themes; the comments say which pairs were measured.
"""

from dataclasses import dataclass
from enum import StrEnum


class Entity(StrEnum):
    """
    The things of the configuration that have a color of their own (`ThemeColors`): states (modes are states too),
    channels (and what else a slot can show: pools, people), slots, and presence: a condition that asks whether a
    channel or a member of a pool is there (`browser plays`), in a hue apart from the channel it asks about.
    """

    STATE = "state"
    CHANNEL = "channel"
    PRESENCE = "presence"
    SLOT = "slot"


class ThemeMode(StrEnum):
    DARK = "dark"
    LIGHT = "light"


# -- spacing, sizes and type: the same in both themes -------------------------------------------------------------


class Space:
    """The spacing scale, on a 4 px grid: margins and gaps use these, so the window lines up."""

    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 24
    XXL = 32


class Radius:
    SMALL = 4
    """Menu items, tool buttons, scroll bars."""
    MEDIUM = 6
    """Buttons and fields."""
    LARGE = 8
    """Cards."""
    PILL = 12
    """Chips: half their height, so they are round at the ends."""


class Motion:
    """How long things take to change: short enough not to wait for, long enough to follow (as on Android)."""

    RESIZE = 200
    """A card that grows or shrinks, or a row that comes or goes, in ms."""
    FADE = 150
    """A change of the look that fades (a color, a text, a page), in ms."""
    enabled = True
    """False: every change happens at once (in tests and screenshots, see `gui/quick/theme.py`)."""


CONTROL_HEIGHT = 32
"""The height of buttons, fields and choices (incl. the border), so a row of them lines up."""


class TypeScale:
    """Font sizes relative to the font of the desktop, so the user's choice of size is kept."""

    CAPTION = 0.9
    TITLE = 1.6
    SECTION = 1.3


# -- colors ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeColors:
    """The color tokens of a theme. `surface` is the window, `raised` a card on it, `sunken` a field."""

    qt_theme: str
    surface: str
    raised: str
    sunken: str
    chrome: str
    """The header and the footer."""
    border: str
    """Decorative lines: cards, dividers (no contrast needed)."""
    control_border: str
    """The outline of fields, buttons and switches: 3:1 on surface, raised and sunken."""
    text: str
    text_muted: str
    """Hints and help: 4.5:1 on every surface."""
    placeholder: str
    """Placeholders show the defaults here, so they are text too: 4.5:1 on sunken."""
    accent: str
    accent_hover: str
    on_accent: str
    """Text and icons on an accent background: 4.5:1 on accent and accent_hover."""
    accent_tint: str
    """The background of a selected item (navigation, menu): text keeps 4.5:1 on it."""
    error: str
    warning: str
    success: str
    tone_good: str
    tone_warn: str
    tone_bad: str
    tone_neutral: str
    """The texts of the pills, 4.5:1 on their tinted backgrounds."""
    state: str
    channel: str
    slot: str
    presence: str
    """
    The colors of the things the configuration is made of (see `Entity`), everywhere in the window: in the help, as
    chips, on the rail. Hues of their own, apart from the tones (good, warning, bad) and the accent (what can be
    clicked): 4.5:1 on every surface as text; chips have text in `text` on a tint of them.
    """


THEMES = {
    # One Dark. text on raised 10.2:1; text_muted 6.5 (raised) / 5.9 (sunken); control_border 3.3 (raised) / 4.0
    # (sunken) / 3.6 (surface); on_accent 8.0 on accent, 9.4 on accent_hover; error 5.2..6.3; placeholder 5.2 on
    # sunken; the pill texts 4.9..6.4 on their tints; state, channel, slot 5.1..5.4 on raised, text 6.5 on their chips;
    # presence 6.5 on raised
    ThemeMode.DARK: ThemeColors(
        qt_theme="one_dark_two",
        surface="#282c34",
        raised="#2e333d",
        sunken="#21252b",
        chrome="#21252b",
        border="#3b414d",
        control_border="#7a8294",
        text="#e6e6e6",
        text_muted="#a9b1bd",
        placeholder="#8f96a3",
        accent="#61afef",
        accent_hover="#7cbdf2",
        on_accent="#0d1117",
        accent_tint="#303e4e",
        error="#ef8891",
        warning="#e5c07b",
        success="#98c379",
        tone_good="#98c379",
        tone_warn="#e5c07b",
        tone_bad="#ef8891",
        tone_neutral="#b1b8c4",
        state="#d48fe7",
        channel="#56b6c2",
        slot="#d19a66",
        presence="#b5c25a",
    ),
    # GitHub light. text_muted 5.7 (surface) / 6.1 (white); control_border 3.2 / 3.5; on_accent 5.2 on accent, 5.9
    # on accent_hover; error 5.0, success 4.8, warning 4.6 on surface; the pill texts 4.9..6.5 on their tints; state,
    # channel, slot 4.7 on surface, 5.0 on white, text 11 on their chips; presence 5.3 on surface, 5.6 on white
    ThemeMode.LIGHT: ThemeColors(
        qt_theme="github_light",
        surface="#f6f8fa",
        raised="#ffffff",
        sunken="#ffffff",
        chrome="#ffffff",
        border="#d0d7de",
        control_border="#818b98",
        text="#1f2328",
        text_muted="#59636e",
        placeholder="#59636e",
        accent="#0969da",
        accent_hover="#0860ca",
        on_accent="#ffffff",
        accent_tint="#dce8f6",
        error="#cf222e",
        warning="#9a6700",
        success="#1a7f37",
        tone_good="#116329",
        tone_warn="#7d4e00",
        tone_bad="#a40e26",
        tone_neutral="#59636e",
        state="#8250df",
        channel="#0f7b84",
        slot="#bc4c00",
        presence="#5c6f00",
    ),
}

TINT_ALPHA = 30
"""How strongly a color tints a background (pills, chips, the problems button), of 255."""

LCD_COLORS = {
    "off": "#1a1c1f",
    "red": "#ff4d4d",
    "green": "#3ee06a",
    "yellow": "#ffd23f",
    "blue": "#5a86ff",
    "magenta": "#e64dff",
    "cyan": "#3fe0e6",
    "white": "#eef1f4",
}
"""The backlights of the LCDs, as bright as they look on the device; LCD_TEXT keeps 5.6:1 or more on each."""

LCD_TEXT = "#101215"
"""Dark marks on a backlight, e.g. the tick on a light color of the color picker."""
LCD_TEXT_OFF = "#9aa0a6"
"""Light marks on the dark "off": 6.5:1."""


@dataclass(frozen=True)
class Hardware:
    """
    The colors of the device, the same in both themes: the preview shows the hardware, which is black. The labels
    printed on it keep 4.5:1 or more on the strip; the LEDs have their real colors.
    """

    panel_top: str = "#1b1e23"
    panel_bottom: str = "#0e1013"
    panel_edge: str = "#30343c"
    strip_top: str = "#22252b"
    strip_bottom: str = "#1a1d22"
    strip_edge: str = "#2f333b"
    print: str = "#c3c8d0"
    """Printed labels (the type of a strip, the buttons): 9.1:1 on the strip."""
    print_dim: str = "#9298a2"
    """Fine print (the scale of the fader): 5.3:1 on the strip."""
    rec: str = "#ff3b3b"
    solo: str = "#ffc928"
    mute: str = "#ff3b3b"
    select: str = "#34d65c"
    ring: str = "#ff9a2e"
    meter_low: str = "#34d65c"
    meter_mid: str = "#ff9f1c"
    meter_high: str = "#ff3b3b"
    led_off: str = "#30343c"
    key: str = "#5c6168"
    """An unlit button: gray rubber, its LED color shows only as a tint."""
    lcd_bezel: str = "#060708"
    knob_top: str = "#4b515b"
    knob_bottom: str = "#1d2025"
    collar_inner: str = "#2b2e33"
    collar_outer: str = "#4a4e55"
    """The gray collar around the knob that holds the LEDs of the ring."""
    slot: str = "#050607"
    cap_top: str = "#d5d9df"
    cap_bottom: str = "#80868f"
    cap_line: str = "#1b1d21"
    tag: str = "#c3c8d0"
    tag_text: str = "#1a1d22"
    """The number of the strip on the light tag at the bottom: 9.5:1."""
    badge: str = "#c9283a"
    badge_text: str = "#ffffff"
    """On the problems badge: 5.5:1."""


HARDWARE = Hardware()
