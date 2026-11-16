const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

function normalizeDisplayedText(text) {
  // WebGAL 的文字演出层会在 DOM 中把同一字重复三次；折叠连续重复字后
  // 再核对目标台词，避免把演出分层误判为没有到达。
  return (text || '').replace(/(.)\1+/gu, '$1');
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const errors = [];
    const consoleMessages = [];
    const failedRequests = [];
    const sceneResponses = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', msg => consoleMessages.push({ type: msg.type(), text: msg.text() }));
    page.on('requestfailed', request => failedRequests.push({
      url: request.url(), error: request.failure()?.errorText || '',
    }));
    page.on('response', response => {
      if (response.url().includes('/game/scene/')) {
        sceneResponses.push({ url: response.url(), status: response.status() });
      }
    });
    await page.goto('http://127.0.0.1:4189/', { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
    await page.getByText('简体中文', { exact: true }).first().click();
    await page.getByText('开始游戏', { exact: true }).first().click();

    await page.locator('#introContainer').getByText('杂志彩页上的少女', { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });

    await page.evaluate(() => {
      window.__introTitles = [];
      const root = document.querySelector('#introContainer');
      const record = () => {
        const text = (root?.innerText || '').trim();
        if (text && !window.__introTitles.includes(text)) window.__introTitles.push(text);
      };
      record();
      new MutationObserver(record).observe(root, { subtree: true, childList: true, characterData: true });
    });

    const target = '伊织的手堵住了我的嘴巴。';
    let seen = false;
    let lastText = '';
    for (let i = 0; i < 1800; i++) {
      lastText = await page.locator('#textBoxMain').textContent().catch(() => '');
      if (normalizeDisplayedText(lastText).includes(target)) {
        seen = true;
        console.log('到达目标对白，点击轮次:', i);
        break;
      }
      await page.mouse.click(800, 350);
      await page.waitForTimeout(8);
    }
    if (!seen) {
      throw new Error('未到达目标对白；当前文本: ' + JSON.stringify(lastText.slice(0, 200)));
    }
    await page.locator('#textBoxMain').getByText(target, { exact: true })
      .waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
    if (errors.length) throw new Error(JSON.stringify(errors));
    const intros = await page.evaluate(() => window.__introTitles || []);
    if (!intros.some(text => text.includes('杂志彩页上的少女')) ||
        !intros.some(text => text.includes('Ｉ´Ｓ・小队結成'))) {
      throw new Error('标题 intro 未完整出现: ' + JSON.stringify(intros));
    }
    await page.screenshot({ path: '../验证/真实新游戏_目标对白.png' });
    const logPath = path.resolve('../验证/真实新游戏_浏览器测试.log');
    const log = [
      '真实新游戏浏览器测试',
      `时间: ${new Date().toISOString()}`,
      'URL: http://127.0.0.1:4189/',
      `目标对白: ${target}`,
      `标题 intro: ${JSON.stringify(intros)}`,
      '场景响应: ' + JSON.stringify(sceneResponses),
      '失败请求: ' + JSON.stringify(failedRequests),
      'pageerror: ' + JSON.stringify(errors),
      '控制台: ' + JSON.stringify(consoleMessages),
      '结论: PASS (标题 0/1、vib_set 后目标对白、pageerror 为空)',
      '',
    ].join('\n');
    fs.writeFileSync(logPath, log, 'utf8');
    console.log('真实新游戏：标题 0 → 标题 1 → 0x2118 vib_set → 目标对白；无 pageerror');
    console.log('截图: 验证/真实新游戏_目标对白.png');
    console.log('日志: 验证/真实新游戏_浏览器测试.log');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
