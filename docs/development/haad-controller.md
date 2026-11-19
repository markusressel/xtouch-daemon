# As a haad controller

The entities of the [Home Assistant guide](../guides/home-assistant.md) in code.

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
