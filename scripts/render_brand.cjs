// Run with Node.js and sharp installed: node scripts/render_brand.cjs
const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require('sharp');

async function main() {
  const source = path.resolve(__dirname, '../docs/brand');
  const brand = path.resolve(__dirname, '../custom_components/smart_presence_notify/brand');
  await fs.mkdir(brand, { recursive: true });
  const png = { compressionLevel: 9, progressive: true };
  for (const name of ['icon', 'dark_icon', 'logo', 'dark_logo']) {
    // Trim at high resolution before scaling; never upscale a raster export.
    const trimmed = await sharp(path.join(source, `${name}.svg`), { density: 288 })
      .trim({ background: '#00000000', threshold: 1 }).toBuffer();
    const dimensions = await sharp(trimmed).metadata();
    const width = name.endsWith('icon') ? 256 : Math.round(256 * dimensions.width / dimensions.height);
    for (const scale of [1, 2]) {
      const size = 256 * scale;
      const output = name + (scale === 2 ? '@2x' : '') + '.png';
      await sharp(trimmed)
        .resize({ width: width * scale, height: size, fit: 'fill' })
        .png(png).toFile(path.join(brand, output));
    }
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
