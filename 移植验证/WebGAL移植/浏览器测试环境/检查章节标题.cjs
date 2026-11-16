const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--mute-audio']});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:720}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:4188/',{waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    await page.getByText('简体中文',{exact:true}).first().click();
    await page.getByText('开始游戏',{exact:true}).first().click();
    await page.waitForTimeout(2500);
    for (let i=0; i<25 && !(await page.locator('#introContainer').getByText('杂志彩页上的少女',{exact:true}).isVisible()); i++) {
      await page.mouse.click(800,350);
      await page.waitForTimeout(250);
    }
    await page.locator('#introContainer').getByText('杂志彩页上的少女',{exact:true}).waitFor({state:'visible',timeout:10000});
    await page.waitForFunction(() => document.querySelector('#textBoxMain')?.textContent?.includes('伊'), null,{timeout:15000});
    if (errors.length) throw new Error(JSON.stringify(errors));
    console.log('章节标题显示，随后进入原开头对白；无页面脚本错误');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
