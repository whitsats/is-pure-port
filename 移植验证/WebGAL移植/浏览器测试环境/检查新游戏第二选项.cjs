// 用路由替换开头以定点测试第二选项；首选项完整开头另有独立测试。
const { chromium } = require('playwright');
const labels = ['２年教室', '走廊', '美術室', '站前商店街'];
const firstLines = ['诶……伊织不在。', '？？？「濑户！」', '一贵「道具，我先放在这里了」', '一贵「（哼歌）」'];
const clean = s => (s || '').replace(/\s+/gu, '');
async function current(page) {
  return page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')].map(e => e.textContent || '').map(t => {
    const n = t.length / 3;
    return Number.isInteger(n) && n > 0 && t === t.slice(0, n).repeat(3) ? t.slice(0, n) : t;
  }).join(''));
}
async function run(browser, a, b) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage(), errors = [], scenes = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {
    const path = new URL(r.url()).pathname;
    if (path.startsWith('/game/scene/')) scenes.push({path, status: r.status()});
  });
  await page.route('**/game/scene/start.txt', route => route.fulfill({status: 200, contentType: 'text/plain',
    body: `setVar:first_choice=${a};\nchangeScene:branch_${a}_002.txt;\n`}));
  try {
    await page.goto('http://127.0.0.1:4191/', {waitUntil: 'networkidle', timeout: 60000});
    await page.getByText('PRESS THE SCREEN TO START', {exact: true}).click();
    await page.getByText('简体中文', {exact: true}).first().click();
    await page.getByText('开始游戏', {exact: true}).first().click();
    const choice = page.getByText(labels[b], {exact: true}).first();
    for (let n = 0; n < 150 && !(await choice.isVisible()); n++) {
      await page.mouse.click(800, 350); await page.waitForTimeout(30);
    }
    if (!(await choice.isVisible())) throw new Error(`组合 ${a}-${b} 未到第二选项: ${await current(page)}`);
    await choice.click();
    for (let n = 0; n < 100 && clean(await current(page)) !== clean(firstLines[b]); n++) {
      await page.waitForTimeout(100);
      if (!(await current(page))) await page.mouse.click(800, 350);
    }
    if (clean(await current(page)) !== clean(firstLines[b]))
      throw new Error(`组合 ${a}-${b} 首句不符: ${await current(page)}`);
    const target = `/game/scene/choice_${a}_${b}_002.txt`;
    if (!scenes.some(s => s.path === target && s.status === 200))
      throw new Error(`组合 ${a}-${b} 未加载正确场景: ${JSON.stringify(scenes)}`);
    if (a === 0 && b === 0) {
      await page.waitForTimeout(1200);
      await page.getByText('快速存档', {exact: true}).first().click();
      await page.waitForTimeout(800);
      for (let n = 0; n < 30 && clean(await current(page)) === clean(firstLines[b]); n++) {
        await page.mouse.click(800, 350); await page.waitForTimeout(100);
      }
      if (clean(await current(page)) === clean(firstLines[b])) throw new Error('第二选项存档后未前进');
      await page.getByText('快速读档', {exact: true}).first().click();
      for (let n = 0; n < 60 && clean(await current(page)) !== clean(firstLines[b]); n++) await page.waitForTimeout(100);
      if (clean(await current(page)) !== clean(firstLines[b])) throw new Error('第二选项读档未恢复');
      const marker = '流程验证：选择 1-1 已进入第三个选项，后续尚未接入。';
      let done = false;
      for (let n = 0; n < 2500; n++) {
        if (clean(await current(page)) === clean(marker)) { done = true; break; }
        await page.mouse.click(800, 350); await page.waitForTimeout(8);
      }
      if (!done) throw new Error('组合 0-0 未到第三选项标记: ' + await current(page));
      if (!scenes.some(s => s.path === '/game/scene/choice_0_0_003.txt' && s.status === 200))
        throw new Error('组合 0-0 未加载第三章');
      console.log('组合 0-0：快速存读档及第三章完整推进通过');
    }
    if (errors.length) throw new Error('页面错误: ' + JSON.stringify(errors));
    console.log(`组合 ${a}-${b}: 第二选项和分支首句通过`);
  } finally { await context.close(); }
}
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio']});
  try { for (let a = 0; a < 3; a++) for (let b = 0; b < 4; b++) await run(browser, a, b); }
  finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
