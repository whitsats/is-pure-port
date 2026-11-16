const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.addInitScript(() => {
      window.__isAudioPlays = [];
      const original = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function (...args) {
        const src = this.currentSrc || this.src;
        const result = original.apply(this, args);
        if (result && result.then) result.then(() => window.__isAudioPlays.push(src)).catch(() => {});
        return result;
      };
    });
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', r => { if (r.url().includes('/vocal/VOICE_')) requests.push([r.url(), r.status()]); });
    await page.goto('http://127.0.0.1:4179/', { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
    await page.getByText('简体中文', { exact: true }).first().click();
    await page.getByText('开始游戏', { exact: true }).first().click();
    await page.waitForTimeout(3000);
    for (let i = 0; i < 6; i++) {
      await page.mouse.click(800, 350);
      await page.waitForTimeout(2500);
    }
    console.log('VOICE_RESPONSES:', JSON.stringify(requests));
    const plays = await page.evaluate(() => window.__isAudioPlays);
    console.log('MEDIA_PLAYS:', JSON.stringify(plays));
    console.log('ERRORS:', JSON.stringify(errors));
    await page.screenshot({ path: '../验证/自动片段.png' });
    if (errors.length) throw new Error('页面出现脚本错误');
    for (const name of ['VOICE_00000.wav', 'VOICE_00001.wav']) {
      if (!requests.some(([url, status]) => url.includes(name) && status === 200)) throw new Error(`语音未成功加载: ${name}`);
      if (!plays.some(url => url.includes(name))) throw new Error(`语音未开始播放: ${name}`);
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
