// 定点载入第二章开头，核查已对照的背景图片确实被浏览器请求。
const { chromium } = require('playwright');
const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const sum = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
(async () => {
  const asset = path.resolve(__dirname, '../历史样片/新游戏三选项样片/public/game/background/verified_corridor.png');
  const original = path.resolve(__dirname, '../../输出-保护边修复/BG/BG_0016.png');
  if (sum(asset) !== sum(original)) throw new Error('样片背景与已核对的提取素材不一致');
  const browser = await chromium.launch({headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio']});
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage(), errors = [], images = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => {
    if (new URL(r.url()).pathname.endsWith('/verified_corridor.png')) images.push(r.status());
  });
  await page.route('**/game/scene/start.txt', route => route.fulfill({status: 200, contentType: 'text/plain',
    body: 'changeScene:opening_001.txt;\n'}));
  try {
    await page.goto('http://127.0.0.1:4192/', {waitUntil: 'networkidle', timeout: 60000});
    await page.getByText('PRESS THE SCREEN TO START', {exact: true}).click();
    await page.getByText('简体中文', {exact: true}).first().click();
    await page.getByText('开始游戏', {exact: true}).first().click();
    for (let i = 0; i < 150 && !images.includes(200); i++) {
      await page.mouse.click(800, 350); await page.waitForTimeout(100);
    }
    if (!images.includes(200) || errors.length) throw new Error(JSON.stringify({images, errors}));
    await page.screenshot({path: path.resolve(__dirname, '../验证/第二章走廊_WebGAL.png')});
    console.log('第二章走廊：素材 SHA-256 一致、浏览器响应 200、无页面错误');
  } finally { await context.close(); await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
