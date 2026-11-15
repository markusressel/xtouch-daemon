#!/usr/bin/env bash
#
# Builds the release tarballs of xtouch-daemon (see RELEASING.md). The release workflow runs it, and it runs locally the
# same way.
#
# Usage: packaging/build-release.sh [<output directory>]   (default: dist/)
#
#   xtouch-daemon-<version>-x86_64.tar.gz      the daemon: its own Python 3.14 (python-build-standalone, installed by
#                                              uv) with every locked dependency except the GUI's, in
#                                              usr/lib/xtouch-daemon, the command usr/bin/xtouch-daemon, the systemd user
#                                              unit and the example configuration
#   xtouch-daemon-gui-<version>-any.tar.gz     the GUI: an environment for the system's Python 3.14 and its PyQt6, with
#                                              the GUI's other dependencies; it uses the daemon's packages
#   sha256sums.txt                             the checksums of both
#
# Each tarball holds one directory, <name>-<version>-<arch>/, with LICENSE and the usr/ tree to install.
#
# haad-mqtt-autodiscovery is built from the commit in packaging/haad-mqtt-autodiscovery.rev, taken from the repository
# next to this one (../haad-mqtt-autodiscovery, or $HAAD_MQTT_AUTODISCOVERY_DIR). Uncommitted changes there don't
# matter; the commit has to be in that repository.

set -euo pipefail

die() {
	echo "error: $*" >&2
	exit 1
}

info() {
	echo "==> $*"
}

[ $# -le 1 ] || die "usage: $0 [<output directory>]"

for tool in git tar gzip uv; do
	command -v "$tool" > /dev/null || die "'$tool' not found"
done

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
haad_dir="${HAAD_MQTT_AUTODISCOVERY_DIR:-$repo_dir/../haad-mqtt-autodiscovery}"
out_dir="$(mkdir -p "${1:-$repo_dir/dist}" && cd "${1:-$repo_dir/dist}" && pwd)"
haad_rev="$(tr -d '[:space:]' < "$repo_dir/packaging/haad-mqtt-autodiscovery.rev")"

[[ "$haad_rev" =~ ^[0-9a-f]{40}$ ]] || die "packaging/haad-mqtt-autodiscovery.rev holds no commit hash"
git -C "$haad_dir" cat-file -e "$haad_rev^{commit}" 2> /dev/null ||
	die "commit $haad_rev of haad-mqtt-autodiscovery not found in $haad_dir (git fetch there)"

work_dir="$(mktemp -d)"
info "Building in $work_dir"

# the daemon's tree, and the GUI's
daemon_root="$work_dir/daemon"
gui_root="$work_dir/gui"
daemon_lib="$daemon_root/usr/lib/xtouch-daemon"
gui_lib="$gui_root/usr/lib/xtouch-daemon-gui"

info "haad-mqtt-autodiscovery at $haad_rev"
mkdir -p "$work_dir/haad-mqtt-autodiscovery"
git -C "$haad_dir" archive "$haad_rev" | tar -x -C "$work_dir/haad-mqtt-autodiscovery"

info "Python 3.14 (python-build-standalone)"
export UV_PYTHON_INSTALL_DIR="$work_dir/pythons"
uv python install --no-bin --quiet 3.14
python_home="$(dirname "$(dirname "$(readlink -f "$(uv python find --managed-python --no-project 3.14)")")")"
mkdir -p "$daemon_lib/python"
# without what a daemon never runs: pip, IDLE, Tk, the test suite of the standard library. Not stripped: strip
# breaks its binaries
tar -C "$python_home" -c \
	--exclude='./bin/idle*' \
	--exclude='./bin/pip*' \
	--exclude='./lib/itcl*' \
	--exclude='./lib/libtcl*' \
	--exclude='./lib/tcl*' \
	--exclude='./lib/thread*' \
	--exclude='./lib/tk*' \
	--exclude='./lib/python3.14/ensurepip' \
	--exclude='./lib/python3.14/idlelib' \
	--exclude='./lib/python3.14/lib-dynload/_tkinter*' \
	--exclude='./lib/python3.14/site-packages/pip' \
	--exclude='./lib/python3.14/site-packages/pip-*' \
	--exclude='./lib/python3.14/test' \
	--exclude='./lib/python3.14/tkinter' \
	--exclude='./lib/python3.14/turtledemo' \
	. | tar -C "$daemon_lib/python" -x
python="$daemon_lib/python/bin/python3.14"

version="$("$python" -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' \
	"$repo_dir/pyproject.toml")"
info "xtouch-daemon $version"

# the locked versions (uv.lock), without the dev tools; the project and haad-mqtt-autodiscovery are installed from
# their sources
export_requirements() {
	(cd "$repo_dir" && uv export --frozen --no-dev --no-editable --no-hashes --no-annotate --no-header \
		--no-emit-project --no-emit-package haad-mqtt-autodiscovery --format requirements-txt "$@")
}
export_requirements > "$work_dir/daemon.txt"
# Qt comes from the system (python-pyqt6), which the GUI's Python uses
export_requirements --extra gui --no-emit-package pyqt6 --no-emit-package pyqt6-qt6 --no-emit-package pyqt6-sip |
	grep -vxF -f "$work_dir/daemon.txt" > "$work_dir/gui.txt"

info "Building xtouch-daemon and haad-mqtt-autodiscovery"
# wheels built now: uv would reuse a cached build of a source directory whose pyproject.toml did not change
uv build --quiet --wheel --python "$python" --out-dir "$work_dir/wheels" "$work_dir/haad-mqtt-autodiscovery"
uv build --quiet --wheel --python "$python" --out-dir "$work_dir/wheels" "$repo_dir"

info "Installing the daemon and its dependencies"
uv pip install --quiet --python "$python" --break-system-packages --no-deps --link-mode copy \
	-r "$work_dir/daemon.txt" "$work_dir"/wheels/*.whl

# a command that finds its Python relative to itself, so an unpacked tarball runs from anywhere; -I keeps the
# user's site-packages and PYTHON* variables out
mkdir -p "$daemon_root/usr/bin"
cat > "$daemon_root/usr/bin/xtouch-daemon" << 'EOF'
#!/bin/sh
# xtouch-daemon from the release package: its own Python 3.14 in /usr/lib/xtouch-daemon.
exec "$(dirname "$(readlink -f "$0")")/../lib/xtouch-daemon/python/bin/python3.14" -I -m xtouch_daemon "$@"
EOF
chmod 755 "$daemon_root/usr/bin/xtouch-daemon"

mkdir -p "$daemon_root/usr/lib/systemd/user" "$daemon_root/usr/share/xtouch-daemon"
"$python" -I -c 'from xtouch_daemon.systemd import unit_file; print(unit_file("/usr/bin/xtouch-daemon"), end="")' \
	> "$daemon_root/usr/lib/systemd/user/xtouch-daemon.service"
cp "$repo_dir/src/xtouch_daemon/config.example.toml" "$daemon_root/usr/share/xtouch-daemon/"
cp "$repo_dir/LICENSE" "$daemon_root/"

info "Installing the GUI's dependencies: $(tr '\n' ' ' < "$work_dir/gui.txt")"
gui_site_packages="$gui_lib/lib/python3.14/site-packages"
uv pip install --quiet --python "$python" --target "$gui_site_packages" --no-deps --link-mode copy \
	-r "$work_dir/gui.txt"
# a virtual environment of the system's Python, which has PyQt6 in its site-packages
mkdir -p "$gui_lib/bin"
ln -s /usr/bin/python3.14 "$gui_lib/bin/python3.14"
ln -s python3.14 "$gui_lib/bin/python3"
ln -s python3.14 "$gui_lib/bin/python"
cat > "$gui_lib/pyvenv.cfg" << 'EOF'
home = /usr/bin
include-system-site-packages = true
version = 3.14
EOF
# the daemon's packages (xtouch-daemon itself, pydantic, ...) after the GUI's and before the system's; relative to this
# site-packages, as for the command. pydantic-core and dbus-fast are compiled for CPython 3.14 on x86_64 with glibc,
# like the system's Python, and the version of xtouch-daemon-bin is pinned to the GUI's
echo "../../../../xtouch-daemon/python/lib/python3.14/site-packages" > "$gui_site_packages/xtouch-daemon.pth"

mkdir -p "$gui_root/usr/bin" "$gui_root/usr/share/applications"
cat > "$gui_root/usr/bin/xtouch-daemon-gui" << 'EOF'
#!/bin/sh
# The GUI of xtouch-daemon from the release package: the system's Python 3.14 and PyQt6, see /usr/lib/xtouch-daemon-gui.
exec "$(dirname "$(readlink -f "$0")")/../lib/xtouch-daemon-gui/bin/python3.14" -I -m xtouch_daemon gui "$@"
EOF
chmod 755 "$gui_root/usr/bin/xtouch-daemon-gui"
cp "$repo_dir/packaging/xtouch-daemon-gui.desktop" "$gui_root/usr/share/applications/"
cp "$repo_dir/LICENSE" "$gui_root/"

# compile <tree> <directory>: the bytecode of everything in it, with the paths of the installed files. Nobody can write
# it next to the files in /usr/lib later. Checked by the hash of the source rather than its time, which makepkg sets
# to SOURCE_DATE_EPOCH. The bundled Python compiles the GUI's too: the system's Python 3.14 reads the bytecode of
# every 3.14 release
compile() {
	"$python" -I -m compileall -q -f -j 0 --invalidation-mode checked-hash -s "$1" -p / "$2" > /dev/null
}
info "Compiling the bytecode"
compile "$daemon_root" "$daemon_lib"
compile "$gui_root" "$gui_lib"

# pack <tree> <name>: <out_dir>/<name>.tar.gz with the tree as <name>/
pack() {
	local tree="$1" name="$2"
	mv "$tree" "$work_dir/$name"
	tar -C "$work_dir" --sort=name --owner=0 --group=0 --numeric-owner -c "$name" | gzip -n -9 > "$out_dir/$name.tar.gz"
	info "$out_dir/$name.tar.gz ($(du -h "$out_dir/$name.tar.gz" | cut -f1))"
}

daemon_name="xtouch-daemon-$version-x86_64"
gui_name="xtouch-daemon-gui-$version-any"
pack "$daemon_root" "$daemon_name"
pack "$gui_root" "$gui_name"
(cd "$out_dir" && sha256sum "$daemon_name.tar.gz" "$gui_name.tar.gz" > sha256sums.txt)
info "Done"
