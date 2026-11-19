#!/usr/bin/env bash
#
# Cuts a release of xtouch-daemon in two steps, with a look at the changelog in between. See RELEASING.md.
#
# Usage: packaging/release.sh prepare <version>
#        packaging/release.sh publish <version>
#
#   prepare    on a clean main that is origin/main: sets the version in pyproject.toml and uv.lock, makes the section
#              [Unreleased] of CHANGELOG.md the section of the version with today's date (and its link), shows the
#              diff, and commits and pushes it to main once you confirm
#   publish    tags the commit of prepare and pushes the tag, waits for the Release workflow of the tag (it stops if
#              that fails), publishes the AUR packages (packaging/aur/publish.sh, which asks before it pushes), and
#              commits and pushes the PKGBUILDs of the version to main; run it again after it stopped (e.g. N at the
#              AUR): it goes on from the tag
#
# Environment:
#   AUR_DIR    passed on to packaging/aur/publish.sh (default there: ~/programming/AUR)

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

confirm() {
	local answer
	read -r -p "$1 [y/N] " answer
	[[ "$answer" =~ ^[yY]$ ]]
}

[ $# -eq 1 ] && [[ "$1" =~ ^(-h|--help)$ ]] && usage 0
[ $# -eq 2 ] || usage
step="$1"
version="$2"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$version' is not a release version (expected X.Y.Z)"

for tool in git gh uv python3; do
	command -v "$tool" > /dev/null || die "'$tool' not found"
done

repo_dir="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
cd "$repo_dir"
repo_url="https://github.com/markusressel/xtouch-daemon"

# on main, nothing uncommitted, and the same commit as origin/main
check_main() {
	[ "$(git branch --show-current)" = main ] || die "not on main"
	[ -z "$(git status --porcelain)" ] || die "the working tree has changes; commit them first"
	info "Fetching origin"
	git fetch --quiet --tags origin
	[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main is not origin/main; pull or push first"
}

tagged() {
	git rev-parse -q --verify "refs/tags/$version" > /dev/null
}

project_version() {
	sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1
}

prepare() {
	check_main
	! tagged || die "the tag $version exists already"
	grep -q '^## \[Unreleased\]$' CHANGELOG.md || die "CHANGELOG.md has no section ## [Unreleased]"
	! grep -q "^## \[$version\]" CHANGELOG.md || die "CHANGELOG.md has a section for $version already"

	info "Setting the version $version"
	sed -i "0,/^version = \".*\"$/s//version = \"$version\"/" pyproject.toml
	uv lock --quiet

	info "Making [Unreleased] the section of $version"
	VERSION="$version" DATE="$(date +%F)" URL="$repo_url" python3 - << 'EOF'
import os
import re
from pathlib import Path

version, date, url = os.environ["VERSION"], os.environ["DATE"], os.environ["URL"]
path = Path("CHANGELOG.md")
text = path.read_text()
start = text.index("## [Unreleased]\n") + len("## [Unreleased]\n")
end = text.find("\n## [", start)
if not text[start : end if end >= 0 else None].strip():
    raise SystemExit("error: the section [Unreleased] of CHANGELOG.md is empty")
text = text[:start] + f"\n## [{version}] - {date}\n" + text[start:]
# the links at the end: [Unreleased] compares with the new version, which comes before the older ones
text = re.sub(r"^\[Unreleased\]: .*\n", "", text, flags=re.MULTILINE)
links = f"[Unreleased]: {url}/compare/{version}...HEAD\n[{version}]: {url}/releases/tag/{version}\n"
first = re.search(r"^\[\d+\.\d+\.\d+\]: ", text, flags=re.MULTILINE)
if first is None:
    text = text.rstrip("\n") + "\n\n" + links
else:
    text = text[: first.start()] + links + text[first.start() :]
path.write_text(text)
EOF

	git --no-pager diff
	if ! confirm "Commit \"Release $version\" and push it to main?"; then
		echo "Nothing committed; the changes stay in the working tree."
		exit 1
	fi
	git add pyproject.toml uv.lock CHANGELOG.md
	git commit --quiet -m "Release $version"
	git push --quiet origin main
	info "Pushed. Next: packaging/release.sh publish $version (just release-publish $version)"
}

publish() {
	check_main
	[ "$(project_version)" = "$version" ] || die "pyproject.toml has the version $(project_version); run prepare first"
	grep -q "^## \[$version\] - " CHANGELOG.md || die "CHANGELOG.md has no section for $version"
	command -v makepkg > /dev/null || die "'makepkg' not found: the AUR packages need Arch Linux"

	if tagged; then
		# a run that stopped after the tag (e.g. N at the AUR): go on from there
		[ "$(git rev-list -n 1 "$version")" = "$(git rev-parse HEAD)" ] || die "the tag $version is not on main's commit"
		info "The tag $version exists already"
	else
		info "Tagging $(git log --oneline -1) as $version"
		git tag "$version"
	fi
	git push --quiet origin "$version"

	info "Waiting for the Release workflow of $version"
	local run=""
	for _ in $(seq 60); do
		run="$(gh run list --workflow release.yml --branch "$version" --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
		[ -n "$run" ] && break
		sleep 5
	done
	[ -n "$run" ] || die "no run of the Release workflow for $version showed up"
	gh run watch "$run" --interval 30 --exit-status > /dev/null ||
		die "the Release workflow failed: $repo_url/actions/runs/$run"
	info "Released: $repo_url/releases/tag/$version"

	packaging/aur/publish.sh "$version"

	info "Setting the PKGBUILDs of this repository to $version"
	local dir
	for dir in packaging/aur/xtouch-daemon-bin packaging/aur/xtouch-daemon-gui-bin; do
		sed -i "s/^pkgver=.*/pkgver=$version/; s/^pkgrel=.*/pkgrel=1/" "$dir/PKGBUILD"
		(cd "$dir" && makepkg --printsrcinfo > .SRCINFO)
	done
	git add packaging/aur
	if ! git diff --cached --quiet; then
		git commit --quiet -m "AUR: the PKGBUILDs of $version"
		git push --quiet origin main
	fi
	info "Done: $version is on GitHub and the AUR"
}

case "$step" in
prepare) prepare ;;
publish) publish ;;
*) usage ;;
esac
