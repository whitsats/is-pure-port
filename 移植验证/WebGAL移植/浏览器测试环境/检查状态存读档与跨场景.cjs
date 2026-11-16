// 构造最小脚本，验证 WebGAL 字节状态随快速存档、刷新与场景切换保持。
const { chromium } = require('playwright');
const clean = s => s.replace(/\s+/g, '');

(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args:['--mute-audio']});
  try {
    const context = await browser.newContext({viewport:{width:1280,height:720}});
    const page = await context.newPage();
    const errors = [], loaded = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', r => {
      if (new URL(r.url()).pathname === '/game/scene/mac002_after_choice_2.txt') loaded.push(r.status());
    });
    await page.route('**/game/scene/start.txt', route => route.fulfill({status:200, contentType:'text/plain',
      body:'setVar:mac_b_0022e=1;\n存档点选择编号{mac_b_0022e}。;\nsetVar:mac_b_0022e=2;\n修改后选择编号{mac_b_0022e}。;\nchangeScene:mac002_after_choice_2.txt;\n'}));
    const current = () => page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')].map(e => e.textContent || '').map(t => {
      const n = t.length / 3;
      return Number.isInteger(n) && n > 0 && t === t.slice(0,n).repeat(3) ? t.slice(0,n) : t;
    }).join(''));
    const waitText = async (want, from, click=false) => {
      for (let i=0; i<100; i++) {
        const got = clean(await current());
        if (got === clean(want)) return;
        if (click && (!got || got === clean(from || '') || clean(want).startsWith(got))) await page.mouse.click(800,350);
        await page.waitForTimeout(200);
      }
      throw new Error(`等待文本失败: wanted=${want} actual=${await current()}`);
    };
    await page.goto('http://127.0.0.1:4187/',{waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    await page.getByText('简体中文',{exact:true}).first().click();
    await page.getByText('开始游戏',{exact:true}).first().click();
    await waitText('存档点选择编号1。',null,true);
    await page.waitForTimeout(1500);
    await page.getByText('快速存档',{exact:true}).first().click();
    await page.waitForTimeout(800);
    await waitText('修改后选择编号2。','存档点选择编号1。',true);
    await page.getByText('快速读档',{exact:true}).first().click();
    await waitText('存档点选择编号1。');
    await page.getByText('快速存档',{exact:true}).first().click();
    await page.waitForTimeout(2000);
    await page.reload({waitUntil:'networkidle',timeout:60000});
    await page.getByText('PRESS THE SCREEN TO START',{exact:true}).click();
    if (await page.getByText('简体中文',{exact:true}).count()) await page.getByText('简体中文',{exact:true}).first().click();
    await page.getByText('继续游戏',{exact:true}).first().click({timeout:10000});
    await waitText('存档点选择编号1。');
    await waitText('修改后选择编号2。','存档点选择编号1。',true);
    await waitText('本次选择编号：2。','修改后选择编号2。',true);
    if (!loaded.includes(200) || errors.length) throw new Error(`场景加载或页面异常: ${JSON.stringify({loaded,errors})}`);
    console.log('构造脚本：状态值 1 存档、改为 2、读档恢复 1；刷新后继续恢复 1，再改为 2 并跨场景显示 2；page errors=0');
    await context.close();
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
