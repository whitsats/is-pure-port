const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio'] });
  try {
    const cn = process.argv.includes('--chinese');
    const cases = cn ? [['道歉', '38C4'], ['少扯了！', '3C2C'], ['…………', '40B8']]
                     : [['謝る', '38C4'], ['ふざけろ！', '3C2C'], ['…………', '40B8']];
    for (const [label, target] of cases) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${cn ? 4181 : 4180}/`, { waitUntil: 'networkidle', timeout: 60000 });
      await page.getByText('PRESS THE SCREEN TO START', { exact: true }).click();
      await page.getByText('简体中文', { exact: true }).first().click();
      await page.getByText('开始游戏', { exact: true }).first().click();
      await page.waitForTimeout(3000);
      await page.mouse.click(800, 350);
      await page.waitForTimeout(1000);
      if (!(await page.getByText(label, { exact: true }).count())) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(1000);
      }
      console.log('BEFORE_CHOICE:', (await page.locator('body').innerText()).slice(0, 300));
      await page.getByText(label, { exact: true }).first().click({ timeout: 10000 });
      await page.waitForTimeout(3000);
      const body = (await page.locator('body').innerText()).replace(/\s/g, '').replace(/(.)\1\1/g, '$1');
      console.log(label, '=>', target, 'matched:', body.includes(target), 'errors:', JSON.stringify(errors));
      if (!body.includes(target) || errors.length) throw new Error('选项未到达预期核查标签');
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
