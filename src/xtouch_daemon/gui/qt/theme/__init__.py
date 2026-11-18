"""
The look of the GUI, like openhasp-config-manager's: the palette of a qt-themes theme (dark or light, remembered) and
one application stylesheet built from design tokens (colors, spacing, radii, type scale). Widgets set the
`role`/`variant` properties instead of style sheets of their own, and painted widgets take their colors from here.
qt-themes brings its own palette, so the GUI looks the same without a desktop environment's theming.

- `tokens`: the design tokens and the colors of both themes and of the hardware.
- `style`: applying a theme (palette and stylesheet), and the properties widgets are styled by.
- `icons`: icons that follow the theme.
- `settings`: the zoom and the size of the preview, remembered.
"""
