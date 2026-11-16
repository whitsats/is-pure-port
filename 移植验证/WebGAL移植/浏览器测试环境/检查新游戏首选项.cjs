// 无头浏览器以隔离存储运行真实开头和三条首选项路径。
const { chromium } = require('playwright');

const origin = 'http://127.0.0.1:4190/';
const options = [
  {label: '道歉', first: '一贵「苇月！」'},
  {label: '少扯了！', first: '一贵「站住！」'},
  {label: '…………', first: '一贵「…………」'},
];
const clean = s => (s || '').replace(/\s+/gu, '');

async function current(page) {
  return page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')]
    .map(e => e.textContent || '').map(t => {
      const n = t.length / 3;
      return Number.isInteger(n) && n > 0 && t === t.slice(0, n).repeat(3) ? t.slice(0, n) : t;
    }).join(''));
}

async function run(browser, index) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage();
  const errors = [], scenes = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {
    if (new URL(r.url()).pathname.startsWith('/game/scene/'))
      scenes.push({path: new URL(r.url()).pathname, status: r.status()});
  });
  try {
    await page.goto(origin, {waitUntil: 'networkidle', timeout: 60000});
    await page.getByText('PRESS THE SCREEN TO START', {exact: true}).click();
    await page.getByText('简体中文', {exact: true}).first().click();
    await page.getByText('开始游戏', {exact: true}).first().click();
    const choice = page.getByText(options[index].label, {exact: true}).first();
    let step = 0;
    for (; step < 2600 && !(await choice.isVisible()); step++) {
      await page.mouse.click(800, 350);
      await page.waitForTimeout(8);
    }
    if (!(await choice.isVisible())) throw new Error('未从开头抵达首个选项，当前文本：' + await current(page));
    console.log(`选项 ${index}: 开头推进 ${step} 次，已到选择`);
    await choice.click();
    for (let n = 0; n < 80 && clean(await current(page)) !== clean(options[index].first); n++) {
      await page.waitForTimeout(100);
      if (!(await current(page))) await page.mouse.click(800, 350);
    }
    if (clean(await current(page)) !== clean(options[index].first))
      throw new Error(`选项 ${index} 首句不符: ${await current(page)}`);
    if (index === 0) {
      await page.waitForTimeout(1200);
      await page.getByText('快速存档', {exact: true}).first().click();
      await page.waitForTimeout(800);
      for (let n = 0; n < 30 && clean(await current(page)) === clean(options[index].first); n++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(100);
      }
      if (clean(await current(page)) === clean(options[index].first)) throw new Error('存档后未前进');
      await page.getByText('快速读档', {exact: true}).first().click();
      for (let n = 0; n < 60 && clean(await current(page)) !== clean(options[index].first); n++)
        await page.waitForTimeout(100);
      if (clean(await current(page)) !== clean(options[index].first)) throw new Error('快速读档未恢复分支首句');
      console.log('选项 0: 快速存档、推进及读档恢复通过');
    }
    const marker = `流程验证：第 ${index + 1} 条分支已进入下一章，后续选项尚未接入。`;
    let done = false;
    for (let n = 0; n < 1600; n++) {
      if (clean(await current(page)) === clean(marker)) { done = true; break; }
      await page.mouse.click(800, 350);
      await page.waitForTimeout(8);
    }
    if (!done) throw new Error(`选项 ${index} 未抵达下一章标记，当前: ${await current(page)}`);
    const wanted = `/game/scene/branch_${index}_002.txt`;
    if (!scenes.some(s => s.path === wanted && s.status === 200))
      throw new Error(`选项 ${index} 未成功加载下一章场景: ${JSON.stringify(scenes)}`);
    if (errors.length) throw new Error('页面错误: ' + JSON.stringify(errors));
    console.log(`选项 ${index}: 分支首句、跨章和结束标记通过，无页面错误`);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio']});
  try {
    for (let i = 0; i < options.length; i++) await run(browser, i);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
