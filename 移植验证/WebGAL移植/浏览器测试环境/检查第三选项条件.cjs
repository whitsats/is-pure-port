// 在独立浏览器存储中定点运行生成场景末尾的真实 WebGAL 选择语句。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const clean = s => (s || '').replace(/\s+/gu, '');
async function current(page) {
  return page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')].map(e => e.textContent || '').map(t => {
    const n = t.length / 3;
    return Number.isInteger(n) && n > 0 && t === t.slice(0, n).repeat(3) ? t.slice(0, n) : t;
  }).join(''));
}
async function run(browser, first, second, visible, picked, expected) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage(), errors = [], scenes = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {
    const p = new URL(r.url()).pathname;
    if (p.startsWith('/game/scene/')) scenes.push({path: p, status: r.status()});
  });
  const source = fs.readFileSync(path.resolve(__dirname,
    `../历史样片/新游戏三选项样片/public/game/scene/choice_${first}_${second}_003.txt`), 'utf8');
  const start = source.lastIndexOf('setVar:mac_6010=');
  if (start < 0) throw new Error('未找到真实场景末尾的条件选择');
  await page.route('**/game/scene/start.txt', route => route.fulfill({status: 200, contentType: 'text/plain', body: source.slice(start)}));
  try {
    await page.goto('http://127.0.0.1:4192/', {waitUntil: 'networkidle', timeout: 60000});
    await page.getByText('PRESS THE SCREEN TO START', {exact: true}).click();
    await page.getByText('简体中文', {exact: true}).first().click();
    await page.getByText('开始游戏', {exact: true}).first().click();
    await page.getByText('没必要说明', {exact: true}).first().waitFor({state: 'visible', timeout: 15000});
    const actual = await page.getByText('青梅竹马而已', {exact: true}).first().isVisible();
    if (actual !== visible) throw new Error(`组合 ${first}-${second} 的条件选项显示为 ${actual}，预期 ${visible}`);
    await page.getByText(picked, {exact: true}).first().click();
    for (let n = 0; n < 100 && clean(await current(page)) !== clean(expected); n++) {
      await page.waitForTimeout(100);
      if (!(await current(page))) await page.mouse.click(800, 350);
    }
    if (clean(await current(page)) !== clean(expected)) throw new Error('分支首句不符: ' + await current(page));
    const index = picked === '青梅竹马而已' ? 0 : 1;
    const wanted = `/game/scene/choice_${first}_${second}_${index}_003.txt`;
    if (!scenes.some(s => s.path === wanted && s.status === 200)) throw new Error('跳转场景不符: ' + JSON.stringify(scenes));
    await page.waitForTimeout(1200);
    await page.getByText('快速存档', {exact: true}).first().click();
    await page.waitForTimeout(800);
    for (let n = 0; n < 30 && clean(await current(page)) === clean(expected); n++) {
      await page.mouse.click(800, 350); await page.waitForTimeout(100);
    }
    await page.getByText('快速读档', {exact: true}).first().click();
    for (let n = 0; n < 60 && clean(await current(page)) !== clean(expected); n++) await page.waitForTimeout(100);
    if (clean(await current(page)) !== clean(expected)) throw new Error('第三选项分支读档未恢复');
    if (errors.length) throw new Error('页面错误: ' + JSON.stringify(errors));
    console.log(`组合 ${first}-${second}: 条件选项${visible ? '显示' : '隐藏'}，选择 ${index} 后存读档通过`);
  } finally { await context.close(); }
}
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio']});
  try {
    await run(browser, 1, 0, false, '没必要说明', '我面向伊织――');
    await run(browser, 1, 1, true, '青梅竹马而已', '在这里说清楚吧。');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
