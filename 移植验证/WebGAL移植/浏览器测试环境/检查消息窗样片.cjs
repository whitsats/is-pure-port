const { chromium } = require('playwright');
const fs = require('fs');

const URL = 'http://127.0.0.1:4182/';
const SCENE = '../数据/消息窗样片_MAC005_v74.txt';

function expectedLines() {
  return fs.readFileSync(SCENE, 'utf8')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.endsWith(';'))
    .map((line) => line.replace(/\s*-VOICE_\d+\.wav;$/, '').replace(/;$/, ''));
}

(async () => {
  const lines = expectedLines();
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
    const requests = [];
    const missing = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('response', (r) => {
      if (r.url().includes('/vocal/VOICE_0112')) requests.push([r.url(), r.status()]);
      if (r.status() >= 400) missing.push([r.url(), r.status()]);
    });
    // 正文按字数拆成 span，每个字内部叠了三层同形文字；按 span 取字并去掉三层重复。
    const squash = (text) => text.replace(/\s+/g, '');
    const shown = (text, timeout = 15000) => page.waitForFunction(
      (expected) => {
        const parts = [...document.querySelectorAll('#textBoxMain span[id]')].map((e) => e.textContent || '');
        const current = parts.map((t) => {
          const third = t.length / 3;
          return Number.isInteger(third) && third > 0 && t === t.slice(0, third).repeat(3) ? t.slice(0, third) : t;
        }).join('');
        return current.replace(/\s+/g, '') === expected.replace(/\s+/g, '');
      },
      text, { timeout, poll: 120 });
    const shownContains = (text, timeout = 15000) => page.waitForFunction(
      (expected) => {
        const parts = [...document.querySelectorAll('#textBoxMain span[id]')].map((e) => e.textContent || '');
        const current = parts.map((t) => {
          const third = t.length / 3;
          return Number.isInteger(third) && third > 0 && t === t.slice(0, third).repeat(3) ? t.slice(0, third) : t;
        }).join('');
        return current.includes(expected);
      },
      text, { timeout, poll: 120 });

    await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
    await page.getByText('简体中文', { exact: true }).first().click();
    await page.getByText('开始游戏', { exact: true }).first().click();
    await page.waitForTimeout(2500);

    // 第一句是手工标注的提示，之后每按一次只前进一行；节拍命令不应消耗按键。
    await shownContains('消息窗节奏演示');

    // 文字演出未结束时，点击只把当前句推到终态而不前进，因此每句允许几个短探针。
    // 若节拍命令多消耗了推进，台词会被跳过，本轮所有探针都不会命中。
    const advanceTo = async (line, label) => {
      for (let attempt = 0; attempt < 4; attempt++) {
        await page.mouse.click(800, 350);
        if (await shown(line, 1400).then(() => true).catch(() => false)) return;
      }
      throw new Error(`${label}未按序显示（可能被跳过）：${line}`);
    };

    for (const [index, line] of lines.entries()) {
      await advanceTo(line, `第 ${index + 1} 句`);
    }
    await advanceTo('片段到此为止，后续指令尚未转换。', '22 句之后的片尾');

    const plays = await page.evaluate(() => window.__isAudioPlays);
    console.log('LINES:', lines.length);
    console.log('VOICE_RESPONSES:', JSON.stringify(requests));
    console.log('MEDIA_PLAYS:', JSON.stringify(plays.map((url) => url.split('/').pop())));
    console.log('ERRORS:', JSON.stringify(errors));
    console.log('MISSING:', JSON.stringify(missing));
    await page.screenshot({ path: '../验证/消息窗样片.png' });

    if (errors.length) throw new Error('页面出现脚本错误');
    for (const name of ['VOICE_01124.wav', 'VOICE_01125.wav', 'VOICE_01126.wav', 'VOICE_01127.wav']) {
      if (!requests.some(([url, status]) => url.includes(name) && status === 200)) {
        throw new Error(`语音未成功加载: ${name}`);
      }
      if (!plays.some((url) => url.includes(name))) throw new Error(`语音未开始播放: ${name}`);
    }
    console.log('结果：22 句按序显示，4 条语音加载并播放，节拍命令未额外消耗按键。');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exitCode = 1; });
