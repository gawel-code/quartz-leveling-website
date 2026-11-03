// Rend docs/animation-installation.html en MP4 (1920×1080, 30 i/s) : images par Playwright, assemblage par ffmpeg.
// Usage : node tools/rendre_animation.js [sortie.mp4]   (ou APERCU="3,8,12" pour quelques PNG seulement)
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");
(async () => {
  const html = path.resolve(__dirname, "../docs/animation-installation.html");
  const sortie = path.resolve(process.argv[2] || path.resolve(__dirname, "../docs/animation-installation.mp4"));
  const dossier = fs.mkdtempSync(path.join(os.tmpdir(), "anim-"));
  const nav = await chromium.launch();
  const page = await nav.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 });
  await page.goto("file://" + html + "?rec");
  await page.evaluate(() => document.fonts.ready);
  const duree = await page.evaluate(() => window.DUREE);
  const temps = process.env.APERCU ? process.env.APERCU.split(",").map(Number)
    : Array.from({ length: Math.round(duree * 30) + 1 }, (_, i) => i / 30);
  for (let i = 0; i < temps.length; i++) {
    await page.evaluate((t) => window.seek(t), temps[i]);
    await page.screenshot({ path: path.join(dossier, `i${String(i).padStart(4, "0")}.png`) });
  }
  await nav.close();
  if (process.env.APERCU) { console.log(dossier); return; }
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "30", "-i", path.join(dossier, "i%04d.png"),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "slow", "-movflags", "+faststart", sortie]);
  fs.rmSync(dossier, { recursive: true });
  console.log(sortie);
})();
