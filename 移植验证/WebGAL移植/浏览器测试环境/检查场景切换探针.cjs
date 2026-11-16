const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args:['--mute-audio']});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:720}});
    page.on('pageerror', e => console.log('PAGEERROR', e.message));
    page.on('response', r => { if (r.url().includes('/game/scene/')) console.log('SCENE',r.status(),r.url()); });
    await page.route('**/game/scene/start.txt', route => route.fulfill({status:200,contentType:'text/plain',body:'changeScene:mac002_after_choice_0.txt;\n'}));
    await page.goto('http://127.0.0.1:4186/',{waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    await page.getByText('简体中文',{exact:true}).first().click();
    await page.getByText('开始游戏',{exact:true}).first().click();
    await page.waitForTimeout(5000);
    console.log('BODY', (await page.locator('body').innerText()).slice(0,1200));
    console.log('TEXTBOX', await page.locator('#textBoxMain').innerText().catch(()=>''));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
