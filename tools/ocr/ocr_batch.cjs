// OCR دسته‌ایِ تصاویر با یک worker؛ برای صدها سلول جدول.
// ورودی: مسیر یک JSON با { images: [{path, tag}], psm }.
// خروجی: JSON با { engine, lang, results: [{tag, text, confidence}] }.
const fs = require('fs');
const path = require('path');
const { createWorker } = require('tesseract.js');

(async () => {
  const jobPath = path.resolve(process.argv[2]);
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  const langPath = path.join(__dirname, 'node_modules', '@tesseract.js-data', 'fas', '4.0.0_best_int');
  const worker = await createWorker('fas', 1, {
    langPath,
    cachePath: path.join(__dirname, 'cache'),
  });
  await worker.setParameters({ tessedit_pageseg_mode: String(job.psm || 7) });
  const results = [];
  for (const item of job.images) {
    const { data } = await worker.recognize(path.resolve(item.path), {}, { text: true });
    results.push({ tag: item.tag, text: data.text || '', confidence: data.confidence });
  }
  process.stdout.write(JSON.stringify({
    engine: 'tesseract.js',
    version: require('tesseract.js/package.json').version,
    lang: 'fas',
    results,
  }));
  await worker.terminate();
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
