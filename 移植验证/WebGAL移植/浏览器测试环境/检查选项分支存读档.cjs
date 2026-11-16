// 隔离浏览器上下文检查真实选项样片的快速存读档，不操作用户实际存档。
const { chromium } = require('playwright');
const clean = s => s.replace(/\s+/g, '');

(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args:['--mute-audio']});
  try {
    const context = await browser.newContext({viewport:{width:1280,height:720}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const current = () => page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')].map(e => e.textContent || '').map(t => {
      const n = t.length / 3;
      return Number.isInteger(n) && n > 0 && t === t.slice(0,n).repeat(3) ? t.slice(0,n) : t;
    }).join(''));
    const waitText = async (want, allowClick=false) => {
      for (let i=0; i<80; i++) {
        const got = clean(await current());
        if (got === clean(want)) return;
        if (allowClick && (!got || clean(want).startsWith(got))) await page.mouse.click(800,350);
        await page.waitForTimeout(200);
      }
      throw new Error(`等待文本失败: wanted=${want} actual=${await current()}`);
    };
    await page.goto('http://127.0.0.1:4186/',{waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    await page.getByText('简体中文',{exact:true}).first().click();
    await page.getByText('开始游戏',{exact:true}).first().click();
    await page.waitForTimeout(2500);
    for (let i=0;i<20 && !(await page.getByText('道歉',{exact:true}).count());i++) {
      await page.mouse.click(800,350);
      await page.waitForTimeout(250);
    }
    await page.getByText('道歉',{exact:true}).first().click();
    await waitText('一贵「苇月！」',true);
    await page.waitForTimeout(1500);
    await page.getByText('快速存档',{exact:true}).first().click();
    await page.waitForTimeout(800);
    await page.mouse.click(800,350);
    await page.waitForTimeout(700);
    await page.mouse.click(800,350);
    await waitText('伊织「什、什么？」',true);
    await page.getByText('快速读档',{exact:true}).first().click();
    await waitText('一贵「苇月！」');
    await page.getByText('快速存档',{exact:true}).first().click();
    await page.waitForTimeout(2000);
    await page.reload({waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    if (await page.getByText('简体中文',{exact:true}).count()) {
      await page.getByText('简体中文',{exact:true}).first().click();
    }
    await page.getByText('继续游戏',{exact:true}).first().click({timeout:10000});
    await waitText('一贵「苇月！」');
    if (errors.length) throw new Error(`页面错误: ${JSON.stringify(errors)}`);
    console.log('选择“道歉”后快速存档、推进、读档和刷新后继续游戏，均恢复到原句；page errors=0');
    await context.close();
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
