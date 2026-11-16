const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton } = require('./进入打盘版标题.cjs');

const origin = process.env.IS_PURE_WEBGAL_URL || 'http://127.0.0.1:4204/';

async function startScene(browser, scene) {
  const page = await browser.newPage({ viewport: { width: 1100, height: 620 } });
  await page.addInitScript(() => {
    window.AndroidBridge = {
      getStartupOpeningResult: () => 'played',
      getToolbarInsets: () => '0,0,0',
    };
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (this.src.includes('/vocal/disc-se/')) window.testAmbience = this;
      return play.call(this);
    };
  });
  await page.route('**/game/scene/start.txt*', route => route.fulfill({
    body: scene.join('\n'),
    contentType: 'text/plain; charset=utf-8',
  }));
  await enterDiscTitle(page, origin);
  await discButton(page, '开始游戏').click();
  return page;
}

async function setForeground(page, foreground) {
  await page.evaluate(value => window.webgalSetAppForeground(value), foreground);
}

async function advanceUntil(page, check, failure) {
  for (let attempt = 0; attempt < 8; attempt++) {
    if (await check()) return;
    await page.mouse.click(612, 365);
    await page.waitForTimeout(180);
  }
  assert.fail(failure);
}

async function testAmbience(browser) {
  const page = await startScene(browser, [
    'playEffect:disc-se/SE_00138.opus -id=disc-se-2 -next;',
    '环境音播放中。;',
    'playEffect:none -id=disc-se-2 -next;',
    '环境音已停止。;',
  ]);
  try {
    await page.waitForFunction(() => window.testAmbience?.currentTime > 0.08);
    await setForeground(page, false);
    assert.equal(await page.evaluate(() => window.testAmbience.paused), true);

    await setForeground(page, true);
    await page.waitForFunction(() => !window.testAmbience.paused);
    await setForeground(page, false);
    await advanceUntil(page, () => page.evaluate(() => !window.testAmbience.isConnected), 'stop command did not release the effect');
    await setForeground(page, true);

    assert.equal(await page.evaluate(() => window.testAmbience.paused), true, 'removed effect resumed');
    console.log('PASS: ambience pauses in background, resumes only while active, and stays stopped after disposal');
  } finally {
    await page.close();
  }
}

async function testGallery(browser) {
  const page = await startScene(browser, [
    'bgm:IS_Pure_BGM_SE_00149.mp3 -unlockname=试听曲目06 -next;',
    '试听解锁。;',
    'end;',
  ]);
  try {
    await page.waitForFunction(() => document.getElementById('currentBgm')?.currentTime > 0.12);
    await advanceUntil(page, () => discButton(page, '开始游戏').isVisible(), 'scene did not return to title');
    const titlePlayer = page.locator('#currentBgm');
    const titleSource = await titlePlayer.getAttribute('src');

    await discButton(page, '鉴赏模式').click();
    const controls = page.locator('[class*="bgmControlButton"]');
    await controls.nth(4).click();
    await page.getByText('试听曲目06', { exact: true }).click();
    const preview = await page.locator('[class*="bgmContainer"] audio').elementHandle();
    await page.waitForFunction(audio => audio.currentTime > 0.1 && !audio.paused, preview);
    assert.equal(await titlePlayer.evaluate(audio => audio.paused), true);

    await controls.nth(3).click();
    assert.equal(await preview.evaluate(audio => audio.paused), true);
    await controls.nth(1).click();
    await page.waitForFunction(audio => !audio.paused, preview);
    await page.locator('[class*="extra_top_icon"]').first().click();
    await discButton(page, '开始游戏').waitFor({ state: 'visible' });

    assert.equal(await preview.evaluate(audio => audio.paused && !audio.isConnected), true);
    assert.equal(await titlePlayer.getAttribute('src'), titleSource);
    console.log('PASS: selected gallery track plays, stops, and never replaces the title source');
  } finally {
    await page.close();
  }
}

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
  });
  try {
    await testAmbience(browser);
    await testGallery(browser);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
