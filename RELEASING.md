# Releasing xtouch-daemon

xtouch-daemon follows [semantic versioning](https://semver.org/). Tags are the bare version, e.g. `0.2.0` (no `v`).

A release consists of two tarballs, built by the [Release workflow](.github/workflows/release.yml) and attached to the
GitHub release of the tag, and two AUR packages built from them:

| Tarball | AUR package | Contents |
|---|---|---|
| `xtouch-daemon-<version>-x86_64.tar.gz` | `xtouch-daemon-bin` | A standalone CPython 3.14 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone), installed by uv) with xtouch-daemon and every locked dependency except the GUI's, in `usr/lib/xtouch-daemon`; the command `usr/bin/xtouch-daemon`; the systemd user unit `usr/lib/systemd/user/xtouch-daemon.service` (`ExecStart=/usr/bin/xtouch-daemon run`, otherwise what `install-service` writes); `usr/share/xtouch-daemon/config.example.toml`; the Mumble plugin `usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin` (built from `integrations/mumble` with CMake); `LICENSE`. |
| `xtouch-daemon-gui-<version>-any.tar.gz` | `xtouch-daemon-gui-bin` | A virtual environment of the system's `/usr/bin/python3.14` with its site-packages (for Arch's `python-pyqt6`) in `usr/lib/xtouch-daemon-gui`, holding the GUI's other dependencies (qtawesome, qtpy, qt-themes, tomlkit, packaging); the command `usr/bin/xtouch-daemon-gui`; `usr/share/applications/xtouch-daemon-gui.desktop`; `LICENSE`. |

Each tarball holds one directory, `<name>-<version>-<arch>/`, with `LICENSE` and the `usr/` tree.

The GUI's environment finds xtouch-daemon and its dependencies (pydantic, ...) through a `.pth` file that points at
the site-packages of `xtouch-daemon-bin`, relative to its own. That works because both are CPython 3.14 on x86_64 with
glibc: the compiled dependencies (`pydantic-core`, `dbus-fast`) are built for exactly that, and the bytecode is the
same for every 3.14 release. `xtouch-daemon-gui-bin` depends on `xtouch-daemon-bin` of its own version, and on
`python>=3.14`, `python<3.15`, so an update of Arch's Python to 3.15 can't break it silently.

The bundled Python is relocatable, and both commands find their environment relative to themselves, so an unpacked
tarball runs from any directory, e.g. `<dir>/usr/bin/xtouch-daemon --help`.

## haad-mqtt-autodiscovery

[haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) is a path dependency
(`[tool.uv.sources]`): development uses the checkout next to this one. CI and releases build the commit in
[`packaging/haad-mqtt-autodiscovery.rev`](packaging/haad-mqtt-autodiscovery.rev).

- `just pin-haad-mqtt-autodiscovery` writes the commit checked out in `../haad-mqtt-autodiscovery` to that file. It
  warns about uncommitted changes there (the pin does not include them) and about a commit that is not pushed yet
  (CI can't check it out). Commit the file together with the `uv.lock` that goes with it.
- `packaging/build-release.sh` takes the pinned commit from the repository next to this one (`git archive`), so
  uncommitted changes there don't end up in a release.

The [CI](.github/workflows/ci.yml) and [Release](.github/workflows/release.yml) workflows check out the pinned
commit next to the project.

## Cutting a release

1. **Set the version** in `pyproject.toml` (`version = "0.2.0"`), run `uv lock`, and give the topmost section of
   [`CHANGELOG.md`](CHANGELOG.md) the version and the date (`## [0.2.0] - 2026-12-01`). The release notes are that
   section. Commit.

2. **Try the build** (optional, it is what CI runs):

   ```shell
   just release-build        # packaging/build-release.sh dist
   ```

   It needs git, uv, cmake, a C compiler and network access (Python and the wheels are downloaded). Check an unpacked tarball, e.g.:

   ```shell
   root="$(mktemp -d)"
   tar -xzf dist/xtouch-daemon-0.2.0-x86_64.tar.gz -C "$root"
   "$root"/xtouch-daemon-0.2.0-x86_64/usr/bin/xtouch-daemon --help
   ```

3. **Tag and push:**

   ```shell
   git tag 0.2.0
   git push origin main 0.2.0
   ```

   The Release workflow checks that the tag is the version in `pyproject.toml`, builds the tarballs, test-builds both
   AUR packages from them in an Arch Linux container, installs them there and runs them, and then creates the GitHub
   release of the tag with the tarballs, `sha256sums.txt` and the section of the changelog. A release that exists
   already (e.g. created by hand) gets the tarballs added.

4. **Publish the AUR packages** once the workflow has passed. On an Arch Linux machine with your AUR SSH key:

   ```shell
   packaging/aur/publish.sh 0.2.0
   ```

   The script updates your AUR clones (`$AUR_DIR/xtouch-daemon-bin` and `$AUR_DIR/xtouch-daemon-gui-bin`, default
   `AUR_DIR=~/programming/AUR`; missing clones are created), sets `pkgver` and `pkgrel` in temporary copies of the
   PKGBUILDs, downloads the release tarballs for the checksums (`updpkgsums`), test-builds both packages, generates
   `.SRCINFO`, shows the diff and pushes after you confirm. Nothing in the clones changes before that. See
   `packaging/aur/publish.sh --help` for options (e.g. `--pkgrel 2` for a packaging-only fix of the same version).

5. **Bump the PKGBUILDs in this repository** to the released version (`pkgver=0.2.0`, `pkgrel=1`), regenerate their
   `.SRCINFO` (`makepkg --printsrcinfo > .SRCINFO` in each directory) and commit, so they show what the AUR has.
   Their `sha256sums` stay `SKIP`: `publish.sh` fills in the real ones.

## AUR packages

The PKGBUILDs live in [`packaging/aur`](packaging/aur) and are the source of truth; don't edit them on the AUR
directly, the next release overwrites them.

- `xtouch-daemon-bin`: the daemon tarball, unpacked to `/`. `options=('!strip')`: strip breaks the binaries of the
  bundled Python. Its `check()` runs `xtouch-daemon --version` and `check-config` on the example configuration.
- `xtouch-daemon-gui-bin`: the GUI tarball, `arch=('any')` (it contains no compiled code).
- There is no `-git` package yet.

Publishing is deliberately manual (`packaging/aur/publish.sh`): an AUR SSH key grants push access to every package of
the account, and a PKGBUILD runs code on users' machines, so the key is not stored in GitHub.

To create the AUR packages the first time, nothing has to be done on the AUR website: the first push of `publish.sh`
creates them.

## Testing the packages locally

```shell
just release-build
build="$(mktemp -d)"
cp -r packaging/aur/xtouch-daemon-bin packaging/aur/xtouch-daemon-gui-bin "$build"/
cp dist/xtouch-daemon-*-x86_64.tar.gz "$build"/xtouch-daemon-bin/
cp dist/xtouch-daemon-gui-*-any.tar.gz "$build"/xtouch-daemon-gui-bin/
(cd "$build"/xtouch-daemon-bin && updpkgsums && makepkg --force)
(cd "$build"/xtouch-daemon-gui-bin && updpkgsums && makepkg --force --nodeps)
```

makepkg takes a source file it finds next to the PKGBUILD instead of downloading it. Set `pkgver` in the copies if
the version in `pyproject.toml` differs from the one in the PKGBUILDs.
