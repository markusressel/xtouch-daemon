"""
systemctl for the tests: it answers with the properties it is given and records the commands.
"""


class FakeSystemctl:
    """Answers `systemctl --user show` with `properties` and records every command."""

    def __init__(self, properties: str = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"):
        self.properties = properties
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        return self.properties if command[2] == "show" else ""
