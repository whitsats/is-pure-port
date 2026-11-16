// 开头样片核查：逐句严格比对当前显示的整句，而不是只等文本出现。
// 这样能发现跳句、错句与重复；同时核对语音加载/播放、页面脚本错误。
const { chromium } = require('playwright');
const fs = require('fs');

const URL = process.env.URL || 'http://127.0.0.1:4183/';
const SCENE = process.env.SCENE || '../历史样片/开头样片/public/game/scene/start.txt';
const SHOT = process.env.SHOT || '../验证/开头样片.png';

const sceneSource = fs.readFileSync(SCENE, 'utf8');
const expected = sceneSource
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => line.endsWith(';') && !/^(changeBg|wait):/.test(line))
  .map((line) => line.replace(/\s*-VOICE_\d+\.wav;$/, '').replace(/;$/, ''));
const voices = [...new Set([...sceneSource.matchAll(/-(VOICE_\d{5}\.wav);/g)].map((m) => m[1]))];

const squash = (text) => text.replace(/\s+/g, '');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
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
    const errors = [];
    const badResponses = [];
    const voiceResponses = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('response', (r) => {
      if (r.url().includes('/vocal/VOICE_')) voiceResponses.push([r.url(), r.status()]);
      if (r.status() >= 400) badResponses.push([r.url(), r.status()]);
    });

    // 正文按字拆成 span，每个字叠了三层同形文字；按 span 取字并去掉三层重复。
    const current = () => page.evaluate(() => {
      const parts = [...document.querySelectorAll('#textBoxMain span[id]')].map((e) => e.textContent || '');
      return parts.map((t) => {
        const third = t.length / 3;
        return Number.isInteger(third) && third > 0 && t === t.slice(0, third).repeat(3) ? t.slice(0, third) : t;
      }).join('');
    });

    await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
    await page.getByText('简体中文', { exact: true }).first().click();
    await page.getByText('开始游戏', { exact: true }).first().click();
    await page.waitForTimeout(2500);

    const shown = [];
    let index = 0;
    for (let step = 0; step < expected.length * 12 + 80 && index < expected.length; step++) {
      const text = squash(await current());
      const want = squash(expected[index]);
      if (text === want) {
        shown.push(want);
        index += 1;
        await page.mouse.click(800, 350);
        await page.waitForTimeout(180);
        continue;
      }
      // 刚点过一下、上一句还没退场：再点一次（会先把演出结算完），但不算推进。
      if (index > 0 && text === squash(expected[index - 1])) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(150);
        continue;
      }
      // 打字过程中当前文本是目标句的前缀：再点一次把它推完，不算推进。
      if (want.startsWith(text) || text.length === 0) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(120);
        continue;
      }
      throw new Error(`第 ${index + 1} 句不匹配。期望「${want.slice(0, 24)}」，实际「${text.slice(0, 24)}」`);
    }
    if (index !== expected.length) {
      throw new Error(`只推进到第 ${index} 句（共 ${expected.length} 句），最后显示「${(await current()).slice(0, 24)}」`);
    }

    const plays = await page.evaluate(() => window.__isAudioPlays);
    const duplicates = shown.filter((line, i) => i > 0 && shown[i - 1] === line);
    console.log('LINES:', expected.length);
    console.log('ADVANCED:', shown.length);
    console.log('DUPLICATES:', JSON.stringify(duplicates));
    console.log('FIRST:', shown[0]);
    console.log('LAST:', shown[shown.length - 1]);
    console.log('MEDIA_PLAYS:', JSON.stringify(plays.filter((url) => url.includes('VOICE_')).map((url) => url.split('/').pop())));
    console.log('ERRORS:', JSON.stringify(errors));
    console.log('BAD_RESPONSES:', JSON.stringify(badResponses));
    await page.screenshot({ path: SHOT });

    if (errors.length) throw new Error('页面出现脚本错误');
    if (duplicates.length) throw new Error('出现重复台词');
    if (shown.length !== expected.length) throw new Error('推进句数与期望不符');
    for (const name of voices) {
      if (!voiceResponses.some(([url, status]) => url.includes(name) && status === 200)) {
        throw new Error(`语音未成功加载: ${name}`);
      }
      if (!plays.some((url) => url.includes(name))) throw new Error(`语音未开始播放: ${name}`);
    }
    console.log(`结果：${shown.length} 句逐句严格匹配、无重复、无脚本错误；${voices.length} 条语音加载并播放。`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exitCode = 1; });
