"""
The GUI (`xtouch-daemon gui`, needs the `gui` extra), like openhasp-config-manager's: `domain` holds the logic
(editing, validating and saving the configuration, the devices and applications of the sound server, applying it to
the service) and knows nothing of Qt; `qt` holds the widgets.
"""
