import GIFEncoder from 'gif-encoder-2';
import { PNG } from 'pngjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function createDemoGif() {
  const screenshotsDir = path.resolve(__dirname, '../docs/screenshots');
  const outputGif = path.resolve(__dirname, '../docs/demo.gif');

  const files = [
    '01_dashboard_dark.png',
    '03_surgical_review_queue.png',
    '04_proposal_approved.png',
    '05_kb_search_filter.png',
    '06_screenshot_staleness.png',
    '07_could_not_assess_disclosures.png',
    '08_benchmark_confusion_matrix.png',
    '09_budget_guard.png',
    '02_dashboard_light.png'
  ];

  // Target size (e.g. 1080x675 for high fidelity and reasonable GIF file size)
  const width = 1080;
  const height = 675;

  const encoder = new GIFEncoder(width, height, 'neuquant', true);
  encoder.setRepeat(0); // loop indefinitely
  encoder.setDelay(1800); // 1.8s per slide
  encoder.setQuality(10); // 10 is balanced quality/speed

  encoder.start();

  for (const file of files) {
    const filePath = path.join(screenshotsDir, file);
    if (!fs.existsSync(filePath)) {
      console.warn(`File not found: ${filePath}`);
      continue;
    }

    console.log(`Processing slide: ${file}...`);
    const pngBuffer = fs.readFileSync(filePath);
    const png = PNG.sync.read(pngBuffer);

    // Resize / downsample into a new buffer matching width x height
    const resizedData = Buffer.alloc(width * height * 4);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        // Nearest neighbor mapping from source PNG to target dimensions
        const srcX = Math.floor((x / width) * png.width);
        const srcY = Math.floor((y / height) * png.height);
        const srcIdx = (srcY * png.width + srcX) * 4;
        const tgtIdx = (y * width + x) * 4;

        resizedData[tgtIdx] = png.data[srcIdx];         // R
        resizedData[tgtIdx + 1] = png.data[srcIdx + 1]; // G
        resizedData[tgtIdx + 2] = png.data[srcIdx + 2]; // B
        resizedData[tgtIdx + 3] = png.data[srcIdx + 3]; // A
      }
    }

    encoder.addFrame(resizedData);
  }

  encoder.finish();
  const buffer = encoder.out.getData();
  fs.writeFileSync(outputGif, buffer);
  console.log(`✅ Demo GIF created successfully at: ${outputGif} (${(buffer.length / 1024 / 1024).toFixed(2)} MB)`);
}

createDemoGif().catch(err => {
  console.error('Failed to generate demo GIF:', err);
  process.exit(1);
});
