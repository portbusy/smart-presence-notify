# Varco — Smart Presence Notify

An open perimeter and an incoming dot represent presence and a notification
reaching its destination. The approved design uses violet `#5552EB`, midnight
`#282B44`, green `#14805F` on light backgrounds, and lavender `#DBDAFF` with mint
`#75E4B2` on dark backgrounds.

## Distributed assets

Only the eight PNG assets are shipped in
`custom_components/smart_presence_notify/brand/`:

- `icon.png`, `dark_icon.png`: 256 × 256.
- `icon@2x.png`, `dark_icon@2x.png`: 512 × 512.
- `logo.png`, `dark_logo.png`: landscape, height 256.
- `logo@2x.png`, `dark_logo@2x.png`: double resolution, height 512.

All are transparent, trimmed and losslessly compressed progressive PNGs. The
filenames and dimensions follow the [Home Assistant brand specification](https://github.com/home-assistant/brands#image-specification).
[HACS](https://www.hacs.xyz/docs/publish/integration/#brand-assets) requires the
integration's `brand/` directory with at least `icon.png`.

Local branding is supported from [Home Assistant 2026.3](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).
The integration's existing HA 2026.1 minimum remains unchanged; older HA versions
can run the integration but do not display the bundled branding. Some HACS
frontend versions still use the old CDN and may show a placeholder; this is
tracked in [HACS #5223](https://github.com/hacs/integration/issues/5223).

## Editable sources

The four SVGs here are the production sources. Logo typography uses Avenir Next
(with Avenir and sans-serif fallbacks); regenerate with Avenir Next installed to
preserve the approved typography. With Node.js and `sharp` available, run:

```sh
node scripts/render_brand.cjs
```

The script trims SVG renders before exporting both resolutions. The
`exploration/` directory preserves the approved presentation and concept assets;
it is outside the integration so HACS does not install it.
