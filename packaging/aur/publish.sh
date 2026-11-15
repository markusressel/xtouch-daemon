#!/usr/bin/env bash
#
# Publishes the xtouch-daemon-bin and xtouch-daemon-gui-bin AUR packages for an existing GitHub release.
#
# Runs locally on Arch Linux with the maintainer's AUR SSH key, which deliberately never leaves the maintainer's
# machine (no CI secret). See RELEASING.md.
#
# Usage: packaging/aur/publish.sh [--yes] [--pkgrel N] [--skip-build] <version>
#
#   <version>       release to publish, e.g. 0.2.0 (its tag and tarballs must be on GitHub already)
#   --pkgrel N      pkgrel of both packages (default: 1); use for packaging-only fixes of the same version
#   --skip-build    only generate .SRCINFO, don't test-build the packages
#   --yes           push without asking for confirmation
#
# Environment:
#   AUR_DIR         directory containing the AUR clones xtouch-daemon-bin/ and xtouch-daemon-gui-bin/
#                   (default: ~/programming/AUR); missing clones are created

set -euo pipefail

usage() {
	sed -n '/^# Usage:/,/^$/s/^# \{0,1\}//p' "$0"
	exit "${1:-1}"
}

die() {
	echo "error: $*" >&2
	exit 1
}

info() {
	echo "==> $*"
}

assume_yes=false
pkgrel=1
skip_build=false
version=""

while [ $# -gt 0 ]; do
	case "$1" in
	--yes) assume_yes=true ;;
	--pkgrel)
		[ $# -ge 2 ] || die "--pkgrel needs a value"
		pkgrel="$2"
		shift
		;;
	--skip-build) skip_build=true ;;
	-h | --help) usage 0 ;;
	-*) die "unknown option: $1" ;;
	*)
		[ -z "$version" ] || die "only one version allowed"
		version="$1"
		;;
	esac
	shift
done

[ -n "$version" ] || usage
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$version' is not a release version (expected X.Y.Z)"
[[ "$pkgrel" =~ ^[1-9][0-9]*$ ]] || die "invalid pkgrel '$pkgrel'"

for tool in git makepkg updpkgsums; do
	command -v "$tool" > /dev/null || die "'$tool' not found (needs Arch Linux with base-devel and pacman-contrib)"
done

packages=(xtouch-daemon-bin xtouch-daemon-gui-bin)
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "$script_dir" rev-parse --show-toplevel)"
aur_dir="${AUR_DIR:-$HOME/programming/AUR}"

info "Checking that tag $version exists on GitHub"
git -C "$repo_dir" ls-remote --exit-code --tags origin "refs/tags/$version" > /dev/null ||
	die "tag $version not found on origin; push it first"

if ! git -C "$repo_dir" diff --quiet HEAD -- packaging/aur; then
	die "packaging/aur has uncommitted changes; commit them first so the published files match the repository"
fi

# a fresh directory for every run, left in /tmp
work_dir="$(mktemp -d)"

# prepare_clone <pkgname>: makes sure $aur_dir/<pkgname> is an up-to-date, clean AUR clone
prepare_clone() {
	local pkg="$1" clone="$aur_dir/$1"
	if [ ! -d "$clone/.git" ]; then
		info "Cloning AUR repository $pkg into $clone"
		git -c init.defaultBranch=master clone "ssh://aur@aur.archlinux.org/$pkg.git" "$clone"
	fi
	if [ "$(git -C "$clone" config --get remote.origin.url)" != "ssh://aur@aur.archlinux.org/$pkg.git" ]; then
		die "$clone is not a clone of the AUR package $pkg"
	fi
	if [ -n "$(git -C "$clone" status --porcelain)" ]; then
		die "$clone has uncommitted changes"
	fi
	# a freshly created AUR package has no commits yet, so there is nothing to pull
	if git -C "$clone" rev-parse --verify -q HEAD > /dev/null; then
		info "Updating $clone"
		git -C "$clone" pull --ff-only --quiet
	fi
}

# build <pkgname>: sets the version and checksums, test-builds the package and generates .SRCINFO in a temporary copy
build() {
	local pkg="$1" dir="$work_dir/$1"
	mkdir -p "$dir"
	cp "$script_dir/$pkg/PKGBUILD" "$dir/"
	(
		cd "$dir"
		sed -i "s/^pkgver=.*/pkgver=$version/; s/^pkgrel=.*/pkgrel=$pkgrel/" PKGBUILD
		info "$pkg: downloading the release tarball for the checksums"
		updpkgsums
		if [ "$skip_build" != true ]; then
			info "$pkg: test build"
			# --nodeps: nothing is compiled, and the GUI's xtouch-daemon-bin of the new version is not installed yet
			makepkg --force --cleanbuild --noconfirm --nodeps
		fi
		makepkg --printsrcinfo > .SRCINFO
	)
}

changed=()
for pkg in "${packages[@]}"; do
	prepare_clone "$pkg"
	build "$pkg"
	if cmp -s "$work_dir/$pkg/PKGBUILD" "$aur_dir/$pkg/PKGBUILD" && cmp -s "$work_dir/$pkg/.SRCINFO" "$aur_dir/$pkg/.SRCINFO"; then
		info "$pkg: no changes"
	else
		changed+=("$pkg")
		echo
		info "$pkg: changes to publish"
		for file in PKGBUILD .SRCINFO; do
			diff -u --label "a/$file" --label "b/$file" "$aur_dir/$pkg/$file" "$work_dir/$pkg/$file" 2> /dev/null ||
				[ -e "$aur_dir/$pkg/$file" ] || cat "$work_dir/$pkg/$file"
		done
	fi
done

if [ ${#changed[@]} -eq 0 ]; then
	info "Nothing to publish"
	exit 0
fi

if [ "$assume_yes" != true ]; then
	echo
	read -r -p "Publish ${changed[*]} for $version to the AUR? [y/N] " answer
	case "$answer" in
	y | Y | yes) ;;
	*)
		echo "Aborted, nothing was published. The AUR clones under $aur_dir are unchanged."
		exit 1
		;;
	esac
fi

for pkg in "${changed[@]}"; do
	info "$pkg: publishing"
	cp "$work_dir/$pkg/PKGBUILD" "$work_dir/$pkg/.SRCINFO" "$aur_dir/$pkg/"
	git -C "$aur_dir/$pkg" add PKGBUILD .SRCINFO
	git -C "$aur_dir/$pkg" commit --quiet -m "Release $version-$pkgrel"
	git -C "$aur_dir/$pkg" push origin HEAD:master
done

info "Done"
