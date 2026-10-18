#!/usr/bin/bash
# CI only: runs as root in a disposable archlinux:base-devel container with the
# repository at /work and no credentials. Each phase runs in its own container:
#   plan   unit tests, then render the package from build/aur/release.json and
#          compare it with AUR (build/aur/plan/)
#   build  build the planned recipe as an unprivileged user, install it with
#          its repository dependencies, then run namcap and the app's headless
#          checks against the installed files
# The workflow copies the plan out of /work between the phases, so code run
# during the build (the AppImage runtime, the app) cannot alter what is pushed.
set -euo pipefail
phase=${1:?usage: ci-validate.sh plan|build}
cd /work
test "$(id -u)" = 0 && test -f /.dockerenv || { echo 'Run this only in the CI container' >&2; exit 1; }
: "${BUILDER_UID:?}"
work=/work/build/aur

case "$phase" in
  plan) packages=(python-pytest) ;;
  # Pillow, pypdf and ReportLab create and independently read the smoke fixtures;
  # pypdf needs cryptography to read back the AES-256 output of protect_pdf.
  build) packages=(namcap shellcheck desktop-file-utils xorg-server-xvfb xorg-xauth
                   python-pillow python-pypdf python-reportlab python-cryptography) ;;
  *) echo "Unknown phase $phase" >&2; exit 2 ;;
esac
pacman -Syu --noconfirm --needed git python "${packages[@]}"
useradd --uid "$BUILDER_UID" --create-home builder
as_builder() { runuser -u builder -- env HOME=/home/builder "$@"; }

if [[ "$phase" == plan ]]; then
  : "${MAINTAINER:?}"
  # Includes the vercmp and makepkg checks that skip outside Arch.
  as_builder python -m pytest scripts/tests/test_aur_package.py -v -p no:cacheprovider
  as_builder python scripts/aur_package.py plan --release "$work/release.json" \
    --maintainer "$MAINTAINER" --out "$work/plan"
  exit 0
fi

build=/home/builder/package
as_builder mkdir -p "$build" "$work/logs"
as_builder cp -a "$work/plan/package/." "$build/"
cd "$build"
bash -n PKGBUILD
shellcheck leafsmith.sh
desktop-file-validate leafsmith.desktop
diff -u .SRCINFO <(as_builder makepkg --printsrcinfo)
# Downloads the release AppImage and checks every pinned SHA-256.
as_builder makepkg --verifysource --noconfirm
as_builder makepkg --nodeps --noconfirm 2>&1 | tee "$work/logs/makepkg.log"
mapfile -t built < <(as_builder makepkg --packagelist)
[[ ${#built[@]} == 1 && -f "${built[0]}" ]] || { echo "Expected one built package: ${built[*]}" >&2; exit 1; }
pacman -U --noconfirm "${built[0]}"
pacman -Qkk leafsmith-bin > "$work/logs/pacman-Qkk.log"
as_builder python /work/scripts/aur_package.py namcap "$build/PKGBUILD" "${built[0]}" | tee "$work/logs/namcap.log"
as_builder python /work/scripts/aur_package.py smoke --logs "$work/logs/smoke"
