const { chromium } = require('playwright');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const MANIFEST_PATH = path.resolve(__dirname, '../新游戏打盘高清版/public/game/manga/manifest.json');
const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));

async function setSliderPage(page, targetPage) {
  await page.evaluate((target) => {
    const slider = document.querySelector('input[type="range"]');
    if (slider) {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(slider, target);
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      slider.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, targetPage);
}

(async () => {
  console.log('========================================================');
  console.log('=== WebGAL 漫画单页阅读器改造全量 E2E 验证 (Port 4204) ===');
  console.log('========================================================\n');

  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio']
  });

  try {
    // =========================================================
    // 阶段 1: 移动端竖屏模式 (412 x 915) - 单页、顺序与翻页手势
    // =========================================================
    console.log('>>> [阶段 1] 移动端竖屏模式 (412x915) 验证');
    const portraitContext = await browser.newContext({
      viewport: { width: 412, height: 915 },
      deviceScaleFactor: 2.625,
      isMobile: true,
      hasTouch: true
    });
    const pPage = await portraitContext.newPage();
    const pErrors = [];
    pPage.on('pageerror', err => {
      console.error('[Portrait page error]:', err.message);
      pErrors.push(err.message);
    });

    await enterDiscTitle(pPage, 'http://127.0.0.1:4204/');
    const mangaBtnP = button(pPage, '原著漫画');
    await mangaBtnP.waitFor({ state: 'visible', timeout: 5000 });
    await mangaBtnP.click();
    await pPage.waitForTimeout(800);

    // 1.1 检查只有一张图
    const imgCountP = await pPage.locator('img[class*="mangaPage"]').count();
    console.log(`1.1 竖屏图片数量: ${imgCountP}`);
    assert.equal(imgCountP, 1, '竖屏下必须严格只有一张图片');

    // 1.2 封面检查 (001.webp)
    let curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    let subTitle = await pPage.locator('div[class*="subTitle"]').first().textContent();
    console.log(`1.2 初始封面图: ${curSrc}, 副标题: "${subTitle?.trim()}"`);
    assert(curSrc.includes('vol_01/001.webp'), '初始必须是第1卷封面 001.webp');
    assert(subTitle.includes('第 1 页 (封面)'), '副标题应标明封面');

    // 1.3 操作验证：点右侧进入第 2 页
    console.log('1.3 点击右侧热区 (zoneRight) -> 进入第 2 页...');
    await pPage.locator('div[class*="zoneRight"]').click();
    await pPage.waitForTimeout(500);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    subTitle = await pPage.locator('div[class*="subTitle"]').first().textContent();
    console.log(`    当前页: ${curSrc}, 副标题: "${subTitle?.trim()}"`);
    assert(curSrc.includes('vol_01/002.webp'), '第2页应为 002.webp');
    assert.equal(await pPage.locator('img[class*="mangaPage"]').count(), 1, '依然只有1张图');

    // 1.4 操作验证：按右方向键进入第 3 页
    console.log('1.4 按右方向键 (ArrowRight) -> 进入第 3 页...');
    await pPage.keyboard.press('ArrowRight');
    await pPage.waitForTimeout(500);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    subTitle = await pPage.locator('div[class*="subTitle"]').first().textContent();
    console.log(`    当前页: ${curSrc}, 副标题: "${subTitle?.trim()}"`);
    assert(curSrc.includes('vol_01/003.webp'), '第3页应为 003.webp');
    assert.equal(await pPage.locator('img[class*="mangaPage"]').count(), 1, '依然只有1张图');

    // 1.5 操作验证：向左滑 (Swipe Left) 进入第 4 页
    console.log('1.5 触摸向左滑 (Swipe Left: x 300 -> 100) -> 进入第 4 页...');
    await pPage.evaluate(() => {
      const el = document.querySelector('div[class*="readerOverlay"]');
      const touchStart = new Touch({
        identifier: Date.now(),
        target: el,
        clientX: 300,
        clientY: 400
      });
      const touchEnd = new Touch({
        identifier: Date.now(),
        target: el,
        clientX: 100,
        clientY: 400
      });
      el.dispatchEvent(new TouchEvent('touchstart', { touches: [touchStart], changedTouches: [touchStart], bubbles: true }));
      el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [touchEnd], bubbles: true }));
    });
    await pPage.waitForTimeout(500);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    subTitle = await pPage.locator('div[class*="subTitle"]').first().textContent();
    console.log(`    当前页: ${curSrc}, 副标题: "${subTitle?.trim()}"`);
    assert(curSrc.includes('vol_01/004.webp'), '第4页应为 004.webp');
    assert.equal(await pPage.locator('img[class*="mangaPage"]').count(), 1, '依然只有1张图');

    // 截图保存第 4 页竖屏单页实拍
    const shotPage4 = path.resolve(__dirname, '../验证/manga_single_portrait_page4.png');
    await pPage.screenshot({ path: shotPage4 });
    console.log(`    PASS: 保存竖屏第4页实拍截图: ${shotPage4}`);

    // 1.6 反向操作验证：回上一页
    console.log('1.6 验证反向操作回退 (第4页 -> 第3页 -> 第2页 -> 第1页)...');
    // 点左侧回第 3 页
    await pPage.locator('div[class*="zoneLeft"]').click();
    await pPage.waitForTimeout(300);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curSrc.includes('vol_01/003.webp'), '点左侧应回第 3 页');

    // 按左方向键回第 2 页
    await pPage.keyboard.press('ArrowLeft');
    await pPage.waitForTimeout(300);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curSrc.includes('vol_01/002.webp'), '按左键应回第 2 页');

    // 向右滑回第 1 页 (Swipe Right)
    await pPage.evaluate(() => {
      const el = document.querySelector('div[class*="readerOverlay"]');
      const touchStart = new Touch({ identifier: Date.now(), target: el, clientX: 100, clientY: 400 });
      const touchEnd = new Touch({ identifier: Date.now(), target: el, clientX: 300, clientY: 400 });
      el.dispatchEvent(new TouchEvent('touchstart', { touches: [touchStart], changedTouches: [touchStart], bubbles: true }));
      el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [touchEnd], bubbles: true }));
    });
    await pPage.waitForTimeout(300);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curSrc.includes('vol_01/001.webp'), '向右滑应回第 1 页');

    // 在第 1 页继续点左侧/按左键，保持在第 1 页
    await pPage.keyboard.press('ArrowLeft');
    await pPage.waitForTimeout(200);
    curSrc = await pPage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curSrc.includes('vol_01/001.webp'), '第1页无法再向前，边界守卫正常');
    console.log('    PASS: 封面到第4页正向与反向操作完全通过！');

    assert.equal(pErrors.length, 0, '竖屏测试无控制台错误');
    await portraitContext.close();

    // =========================================================
    // 阶段 2: 桌面横屏模式 (1280 x 720) - 单页显示、无双页/方向按钮、M 键失效
    // =========================================================
    console.log('\n>>> [阶段 2] 桌面横屏模式 (1280x720) 验证');
    const landscapePage = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const lErrors = [];
    landscapePage.on('pageerror', err => {
      console.error('[Landscape page error]:', err.message);
      lErrors.push(err.message);
    });

    await enterDiscTitle(landscapePage, 'http://127.0.0.1:4204/');
    const mangaBtnL = button(landscapePage, '原著漫画');
    await mangaBtnL.click();
    await landscapePage.waitForTimeout(800);

    // 2.1 检查横屏下依然严格只有 1 张图
    const imgCountL = await landscapePage.locator('img[class*="mangaPage"]').count();
    console.log(`2.1 横屏图片数量: ${imgCountL}`);
    assert.equal(imgCountL, 1, '横屏下必须严格单页显示（只有1张图片）');

    // 2.2 验证顶栏无双页切换按钮、无方向切换按钮
    const dualBtn = await landscapePage.locator('button:has-text("双页"), button:has-text("单页")').count();
    console.log(`2.2 双页/单页切换按钮数量: ${dualBtn}`);
    assert.equal(dualBtn, 0, '双页切换按钮必须已彻底移除');

    const dirBtn = await landscapePage.locator('button:has-text("右翻"), button:has-text("左翻")').count();
    console.log(`2.2 方向切换按钮数量: ${dirBtn}`);
    assert.equal(dirBtn, 0, '方向切换按钮必须已彻底移除');

    // 2.3 按键盘 M 键，验证不切换双页
    console.log('2.3 按键盘 M 键测试...');
    await landscapePage.keyboard.press('m');
    await landscapePage.waitForTimeout(300);
    assert.equal(await landscapePage.locator('img[class*="mangaPage"]').count(), 1, '按 M 键后依然只有1张图');
    console.log('    PASS: M 快捷键已失效');

    // 2.4 截图横屏单页
    const shotLandscape = path.resolve(__dirname, '../验证/manga_single_landscape_page1.png');
    await landscapePage.screenshot({ path: shotLandscape });
    console.log(`    PASS: 保存横屏单页实拍截图: ${shotLandscape}`);

    // =========================================================
    // 阶段 3: 12 卷首尾页与卷末边界全量验证
    // =========================================================
    console.log('\n>>> [阶段 3] 12 卷首尾页与卷末边界全量验证 (共 2,982 页)');
    for (const vol of manifest.volumes) {
      const volId = vol.id;
      const totalPages = vol.pages.length;
      const expectedFirst = vol.pages[0].file;
      const expectedLast = vol.pages[totalPages - 1].file;

      // 打开卷目抽屉选择该卷
      const volMenuBtn = landscapePage.locator('button:has-text("卷目")');
      await volMenuBtn.click();
      await landscapePage.waitForTimeout(300);

      // 点击对应卷的卡片 (按数组索引精准获取)
      const volCard = landscapePage.locator('div[class*="volCard"]').nth(volId - 1);
      await volCard.click();
      await landscapePage.waitForTimeout(400);

      // 验证首页
      let curImg = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
      assert(curImg.includes(`vol_${String(volId).padStart(2, '0')}/${expectedFirst}`), `Vol ${volId} 首页必须为 ${expectedFirst}`);

      // 拖动/设置进度条到末页
      await setSliderPage(landscapePage, totalPages);
      await landscapePage.waitForTimeout(400);

      // 验证末页
      curImg = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
      assert(curImg.includes(`vol_${String(volId).padStart(2, '0')}/${expectedLast}`), `Vol ${volId} 末页必须为 ${expectedLast}`);

      // 在末页按右键，验证卷末边界守卫
      await landscapePage.keyboard.press('ArrowRight');
      await landscapePage.waitForTimeout(200);
      curImg = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
      assert(curImg.includes(`vol_${String(volId).padStart(2, '0')}/${expectedLast}`), `Vol ${volId} 末页无法再后进，边界正常`);

      console.log(`  PASS: 第 ${volId} 卷 (${vol.title}): 共 ${totalPages} 页 | 首页 ${expectedFirst} -> 末页 ${expectedLast} 验证通过`);
    }

    // =========================================================
    // 阶段 4: 书签功能与跨卷跳转验证
    // =========================================================
    console.log('\n>>> [阶段 4] 书签功能与跨卷跳转验证');
    // 跳转到第 1 卷第 3 页
    await landscapePage.locator('button:has-text("卷目")').click();
    await landscapePage.waitForTimeout(300);
    await landscapePage.locator('div[class*="volCard"]').first().click();
    await landscapePage.waitForTimeout(400);
    // 按两次右键到达第 3 页
    await landscapePage.keyboard.press('ArrowRight');
    await landscapePage.keyboard.press('ArrowRight');
    await landscapePage.waitForTimeout(300);

    let curP = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curP.includes('vol_01/003.webp'), '当前应在第 1 卷第 3 页');

    // 点击存书签
    const bmBtn = landscapePage.locator('button:has-text("存书签"), button:has-text("已书签")');
    await bmBtn.click();
    await landscapePage.waitForTimeout(300);
    const bmText = await bmBtn.textContent();
    console.log(`4.1 书签按钮状态: "${bmText?.trim()}"`);
    assert(bmText.includes('已书签'), '书签按钮状态应为已书签');

    // 打开书签夹验证存在
    const bmDrawerBtn = landscapePage.locator('button:has-text("书签夹")');
    await bmDrawerBtn.click();
    await landscapePage.waitForTimeout(400);
    const bmCardText = await landscapePage.locator('div[class*="bmTitle"]').first().textContent();
    console.log(`4.2 书签夹条目: "${bmCardText?.trim()}"`);
    assert(bmCardText.includes('第 1 卷 · 第 3 页'), '书签夹必须包含第 1 卷第 3 页');

    // 关闭书签夹，切换到第 2 卷第 10 页
    await landscapePage.locator('div[class*="drawerOverlay"]').click();
    await landscapePage.waitForTimeout(300);

    await landscapePage.locator('button:has-text("卷目")').click();
    await landscapePage.waitForTimeout(300);
    await landscapePage.locator('div[class*="volCard"]').nth(1).click();
    await landscapePage.waitForTimeout(400);
    await setSliderPage(landscapePage, 10);
    await landscapePage.waitForTimeout(400);
    curP = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curP.includes('vol_02/010.webp'), '当前已切换至第 2 卷第 10 页');

    // 重新打开书签夹，点击书签项跳转回第 1 卷第 3 页
    console.log('4.3 测试从第 2 卷跨卷跳转回第 1 卷第 3 页...');
    await bmDrawerBtn.click();
    await landscapePage.waitForTimeout(400);
    await landscapePage.locator('div[class*="bmCard"]').first().click();
    await landscapePage.waitForTimeout(500);

    curP = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    console.log(`    跨卷跳转后图片: ${curP}`);
    assert(curP.includes('vol_01/003.webp'), '点击书签必须精确跨卷恢复到 vol_01/003.webp');

    // 清理书签测试：在书签抽屉中删除该书签
    await bmDrawerBtn.click();
    await landscapePage.waitForTimeout(400);
    await landscapePage.locator('div[class*="bmDelBtn"]').first().click();
    await landscapePage.waitForTimeout(300);
    const emptyTip = await landscapePage.locator('div[class*="emptyDrawerTip"]').textContent();
    assert(emptyTip.includes('暂无书签记录'), '书签删除后应提示暂无书签记录');
    await landscapePage.locator('div[class*="drawerOverlay"]').click();
    await landscapePage.waitForTimeout(300);
    console.log('    PASS: 书签保存、跨卷直达与删除验证全部通过！');

    // =========================================================
    // 阶段 5: 页面刷新断点续读验证
    // =========================================================
    console.log('\n>>> [阶段 5] 页面刷新断点续读验证');
    // 跳转到第 4 卷第 15 页
    await landscapePage.locator('button:has-text("卷目")').click();
    await landscapePage.waitForTimeout(300);
    await landscapePage.locator('div[class*="volCard"]').nth(3).click();
    await landscapePage.waitForTimeout(400);
    await setSliderPage(landscapePage, 15);
    await landscapePage.waitForTimeout(600);
    curP = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    assert(curP.includes('vol_04/015.webp'), '当前定位到第 4 卷第 15 页');

    // 刷新页面
    console.log('5.1 正在执行 page.reload()...');
    await landscapePage.reload();
    await landscapePage.waitForTimeout(1000);

    console.log('5.2 重新进入标题界面并打开原著漫画...');
    await enterDiscTitle(landscapePage, 'http://127.0.0.1:4204/');
    const mangaBtnReload = button(landscapePage, '原著漫画');
    await mangaBtnReload.click();
    await landscapePage.waitForTimeout(800);

    // 验证续读提示弹窗
    const toastLocator = landscapePage.locator('div[class*="historyToast"]');
    await toastLocator.waitFor({ state: 'visible', timeout: 3000 });
    const toastText = await toastLocator.textContent();
    console.log(`5.3 续读 Toast 文本: "${toastText?.trim()}"`);
    assert(toastText.includes('上次读到：第 4 卷 第 15 页'), '断点续读必须提示第 4 卷第 15 页');

    // 点击「继续阅读」
    console.log('5.4 点击「继续阅读」按钮...');
    await landscapePage.locator('button[class*="historyBtn"]').click();
    await landscapePage.waitForTimeout(600);

    curP = await landscapePage.locator('img[class*="mangaPage"]').first().getAttribute('src');
    console.log(`    续读恢复后图片: ${curP}`);
    assert(curP.includes('vol_04/015.webp'), '续读恢复后必须是 vol_04/015.webp');
    console.log('    PASS: 页面刷新断点续读验证通过！');

    assert.equal(lErrors.length, 0, '横屏测试无控制台错误');
    await landscapePage.close();

    console.log('\n========================================================');
    console.log('ALL MANGA SINGLE-PAGE READER E2E TESTS PASSED (100%)!');
    console.log('========================================================');
  } finally {
    await browser.close();
  }
})();
