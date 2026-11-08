#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Renders custom_components/trobar/brand/*.png from the Trobar brand kit's
# SVGs, to Home Assistant's brand-image specs: icons square, 256 and 512 px;
# logos landscape with the short side 128 and 256 px; transparent and trimmed.
#
#   dev/render_brand.sh PATH/TO/BRAND-KIT
#
# PATH/TO/BRAND-KIT is the kit's root (the directory holding svg/mark/ and
# svg/lockup/). Icons are the Troubadour mark; logos the Troubadour
# horizontal lockup; dark_* the Nuèch ones, whose cream "Trob" stays
# readable on HA's dark themes where Troubadour's near-black would not.
#
# Needs rsvg-convert and ImageMagick's convert. Without them, and with
# docker available, it runs itself in ubuntu:22.04 with both installed.
set -euo pipefail
cd "$(dirname "$0")/.."

kit="${1:?usage: dev/render_brand.sh PATH/TO/BRAND-KIT}"
kit="$(cd "$kit" && pwd)"
out="${TROBAR_RENDER_OUT:-custom_components/trobar/brand}"

if ! command -v rsvg-convert >/dev/null 2>&1 || ! command -v convert >/dev/null 2>&1; then
  if [ -n "${TROBAR_IN_RENDER_CONTAINER:-}" ] || ! command -v docker >/dev/null 2>&1; then
    echo "needs rsvg-convert and ImageMagick (or docker to run them in)" >&2
    exit 2
  fi
  tag="trobar-brand-render:local"
  printf 'FROM ubuntu:22.04\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends librsvg2-bin imagemagick && rm -rf /var/lib/apt/lists/*\n' \
    | docker build -q -t "$tag" - >/dev/null
  # The container renders into its own scratch directory and hands the
  # files back as a tar on stdout, so it never writes into the checkout.
  docker run --rm -e TROBAR_IN_RENDER_CONTAINER=1 -e TROBAR_RENDER_OUT=/tmp/out \
    -v "$PWD/dev:/repo/dev:ro" -v "$kit:/kit:ro" "$tag" \
    sh -c 'mkdir -p /tmp/out && /repo/dev/render_brand.sh /kit >&2 && tar -C /tmp/out -cf - .' \
    | tar -C "$out" -xf -
  echo "rendered $out from $kit (in docker)"
  exit 0
fi

# Rasterised large, trimmed to the artwork, then scaled down: the trim is
# exact at that size, and the final size is the one HA asks for. -strip
# keeps timestamps out, so an unchanged kit renders byte-identical files.
render() {  # svg, geometry, output
  rsvg-convert -h 2048 "$1" \
    | convert - -trim +repage -resize "$2" -strip "PNG32:$3"
}

mark="$kit/svg/mark"
lockup="$kit/svg/lockup"
render "$mark/trobar-mark-troubadour.svg" 256x256 "$out/icon.png"
render "$mark/trobar-mark-troubadour.svg" 512x512 "$out/icon@2x.png"
render "$lockup/trobar-lockup-horizontal-troubadour.svg" x128 "$out/logo.png"
render "$lockup/trobar-lockup-horizontal-troubadour.svg" x256 "$out/logo@2x.png"
render "$lockup/trobar-lockup-horizontal-nuech.svg" x128 "$out/dark_logo.png"
render "$lockup/trobar-lockup-horizontal-nuech.svg" x256 "$out/dark_logo@2x.png"
echo "rendered $out from $kit"
