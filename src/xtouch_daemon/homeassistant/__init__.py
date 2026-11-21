"""
Home Assistant through its WebSocket API (`[homeassistant]`): the entities bindings show and set directly
(`{ entity = "..." }`, see docs/development/design/bindings.md). `domains` has what the daemon knows of the domains
(their values and the services that set them), `states` the states of the entities and their changes as the API sends
them, `parts` how a state becomes what a part shows, `client` the connection. The MQTT side (entities of the daemon's
own) is `xtouch_daemon.mqtt`.
"""
