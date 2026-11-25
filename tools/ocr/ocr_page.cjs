// OCR یک تصویر با tesseract.js و دادهٔ آموزش‌دیدهٔ فارسیِ همراهِ مخزن.
// خروجی JSON است تا موتور، اطمینان، ابعاد و متن در شاهدِ ردیف ثبت شوند.
const path = require('path');
const { createWorker } = require('tesseract.js');

(async () => {
  const image = path.resolve(process.argv[2]);
  const langPath = path.join(__dirname, 'node_modules', '@tesseract.js-data', 'fas', '4.0.0_best_int');
  const worker = await createWorker('fas', 1, {
    langPath,
    cachePath: path.join(__dirname, 'cache'),
  });
  // جدول‌های تقویم به‌هم‌ریخته‌اند؛ PSM قابلِ تنظیم برای آزمونِ کیفیت لازم است.
  if (process.env.TESS_PSM) {
    await worker.setParameters({ tessedit_pageseg_mode: process.env.TESS_PSM });
  }
  const { data } = await worker.recognize(image, {}, { blocks: true, text: true });
  process.stdout.write(JSON.stringify({
    engine: 'tesseract.js',
    version: require('tesseract.js/package.json').version,
    lang: 'fas',
    text: data.text || '',
    confidence: data.confidence,
    lines: (data.lines || []).length,
    words: (data.words || []).map((w) => ({
      text: w.text,
      confidence: w.confidence,
      bbox: w.bbox,
    })),
  }));
  await worker.terminate();
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
