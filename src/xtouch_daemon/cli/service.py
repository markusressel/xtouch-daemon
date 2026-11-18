"""
The systemd user service (`install-service`).
"""

import click

from xtouch_daemon.system import systemd


@click.command("install-service")
@click.option("--now", is_flag=True, help="Also enable and start it.")
@click.option(
    "--remove-override",
    is_flag=True,
    help="Only remove the unit in ~/.config/systemd/user that overrides the one of the package (enabled and running "
    "stay so).",
)
def install_service(now: bool, remove_override: bool) -> None:
    """
    Set the daemon up as a systemd user service. The release package has its unit already; any other installation
    writes one to ~/.config/systemd/user.
    """
    service = systemd.Service()
    try:
        if remove_override:
            if not systemd.overrides_packaged_unit():
                raise click.ClickException(f"{systemd.unit_path()} does not override {systemd.PACKAGED_UNIT}")
            path = service.remove_override()
            click.echo(f"Removed {path}: the service uses {systemd.PACKAGED_UNIT} now")
            return
        path = service.install(systemd.executable(), start=now)
    except systemd.ServiceError as e:
        raise click.ClickException(str(e)) from e
    if path is None:
        click.echo(f"The package installed {systemd.PACKAGED_UNIT}")
        if systemd.overrides_packaged_unit():
            click.echo(
                f"{systemd.unit_path()} overrides it: xtouch-daemon install-service --remove-override removes that"
            )
    else:
        click.echo(f"Wrote {path}")
    if not now:
        click.echo(f"Start it with: systemctl --user enable --now {systemd.UNIT_NAME}")
    click.echo("Logs: journalctl --user -u xtouch-daemon -f")
