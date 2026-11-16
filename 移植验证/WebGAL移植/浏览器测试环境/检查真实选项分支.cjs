// 对照生成场景逐句检查三条分支；只验证 WebGAL 样片，不代表原版路线已实测。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const url = process.env.URL || 'http://127.0.0.1:4185/';
const cross = process.env.CROSS === '1';
const stateful = process.env.STATEFUL === '1';
const scenePath = stateful ? '../历史样片/选项跨剧本状态样片/public/game/scene/start.txt'
  : cross ? '../历史样片/选项跨剧本流程样片/public/game/scene/start.txt' : '../历史样片/选项分支真实剧情样片/public/game/scene/start.txt';
const scene = fs.readFileSync(path.join(__dirname, scenePath), 'utf8');
const cases = [
  { label: '道歉', index: 0 },
  { label: '少扯了！', index: 1 },
  { label: '…………', index: 2 },
];
const clean = (s) => s.replace(/\s+/g, '');

function expectedLines(index) {
  const start = scene.indexOf(`label:choice_${index};`) + `label:choice_${index};`.length;
  const end = scene.indexOf('jumpLabel:probe_end;', start);
  if (start < 1 || end < start) throw new Error('branch label missing');
  return scene.slice(start, end).split('\n').map(s => s.trim())
    .filter(s => s.endsWith(';') && !s.startsWith('wait:') && !s.startsWith('changeScene:') && !s.startsWith('setVar:'))
    .map(s => s.replace(/\s*-VOICE_\d+\.wav;$/, '').replace(/;$/, ''));
}

function expectedVoices(index) {
  const start = scene.indexOf(`label:choice_${index};`);
  const end = scene.indexOf('jumpLabel:probe_end;', start);
  return new Set([...scene.slice(start, end).matchAll(/-(VOICE_\d{5}\.wav);/g)].map(x => x[1]));
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'] });
  try {
    for (const item of cases.filter(c => process.env.CASE === undefined || String(c.index) === process.env.CASE)) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
      const page = await context.newPage();
      const errors = [], badResources = [], optionalMissing = [], voiceResponses = new Set(), sceneResponses = new Set();
      page.on('pageerror', e => errors.push(e.message));
      page.on('response', r => {
        if (r.url().includes('/vocal/VOICE_') && r.status() === 200) voiceResponses.add(r.url().split('/').pop());
        const scenePath = new URL(r.url()).pathname;
        if (/^\/game\/scene\/mac002_after_choice_\d\.txt$/.test(scenePath) && r.status() === 200 &&
            (r.headers()['content-type'] || '').includes('text/plain')) sceneResponses.add(scenePath.split('/').pop());
        if (r.status() >= 400) {
          const optional = /\/lib\/(live2d\.min|live2dcubismcore\.min)\.js$/.test(r.url());
          (optional && r.status() === 404 ? optionalMissing : badResources).push([r.status(), r.url()]);
        }
      });
      const current = () => page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')]
        .map(e => e.textContent || '').map(t => {
          const n = t.length / 3;
          return Number.isInteger(n) && n > 0 && t === t.slice(0, n).repeat(3) ? t.slice(0, n) : t;
        }).join(''));
      await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
      await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
      await page.getByText('简体中文', { exact: true }).first().click();
      await page.getByText('开始游戏', { exact: true }).first().click();
      await page.waitForTimeout(2500);
      for (let i = 0; i < 20 && !(await page.getByText(item.label, { exact: true }).count()); i++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(250);
      }
      await page.getByText(item.label, { exact: true }).first().click({ timeout: 10000 });
      await page.waitForTimeout(500);
      const expected = expectedLines(item.index);
      let index = 0;
      for (let step = 0; step < expected.length * 18 + 100 && index < expected.length; step++) {
        const text = clean(await current()), want = clean(expected[index]);
        if (text === want) {
          index++;
          await page.mouse.click(800, 350);
          await page.waitForTimeout(150);
        } else if (!text || want.startsWith(text) || (index && text === clean(expected[index - 1]))) {
          await page.mouse.click(800, 350);
          await page.waitForTimeout(120);
        } else {
          throw new Error(`分支 ${item.index} 第 ${index + 1} 句不符: expected=${want} actual=${text}`);
        }
      }
      if (index !== expected.length || errors.length || badResources.length) {
        throw new Error(`分支 ${item.index}: ${index}/${expected.length}, errors=${JSON.stringify(errors)}, bad=${JSON.stringify(badResources)}`);
      }
      const missingVoices = [...expectedVoices(item.index)].filter(name => !voiceResponses.has(name));
      if (missingVoices.length) throw new Error(`分支 ${item.index} 未加载语音: ${missingVoices.join(',')}`);
      if (cross) {
        for (let i = 0; i < 30 && !sceneResponses.has(`mac002_after_choice_${item.index}.txt`); i++) {
          await page.waitForTimeout(200);
        }
        if (!sceneResponses.has(`mac002_after_choice_${item.index}.txt`)) throw new Error(`分支 ${item.index} 未加载下一场景`);
        let displayed = '', sawState = !stateful;
        for (let i = 0; i < 50; i++) {
          displayed = clean(await current());
          if (displayed.includes('下一剧本MAC_002已载入')) break;
          if (stateful && displayed === `本次选择编号：${item.index}。`) {
            sawState = true;
            await page.mouse.click(800, 350);
          }
          // 点击可能先完成上一句打字；仅在仍显示分支末句时继续推进。
          if (displayed === clean(expected[expected.length - 1])) await page.mouse.click(800, 350);
          await page.waitForTimeout(200);
        }
        if (!sawState) throw new Error(`分支 ${item.index} 未能在下一场景恢复选项编号`);
        if (!displayed.includes('下一剧本MAC_002已载入')) throw new Error(`分支 ${item.index} 未显示目标场景内容: ${displayed}`);
        if (errors.length || badResources.length) throw new Error(`切换场景后异常: ${JSON.stringify({errors, badResources})}`);
      }
      console.log(`分支 ${item.index} ${item.label}: ${index}/${expected.length} 句逐句匹配; ${voiceResponses.size} 个语音资源成功加载; 下一剧本=${cross ? '已加载' : '未测试'}; 场景状态=${stateful ? '已验证' : '未测试'}; page errors=0; optional Live2D 404=${optionalMissing.length}`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
