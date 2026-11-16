const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton } = require('./进入打盘版标题.cjs');

const origin = process.env.IS_PURE_WEBGAL_URL || 'http://127.0.0.1:4204/';
const firstTrack = '/game/bgm/IS_Pure_BGM_SE_00146.mp3';
const secondTrack = '/game/bgm/IS_Pure_BGM_SE_00149.mp3';

async function applyBgmCommand(page, content, enter = 0) {
  await page.evaluate(async ({ content, enter }) => {
    const { bgm } = await import('/src/Core/gameScripts/bgm.ts');
    const { stageStateManager } = await import('/src/Core/Modules/stage/stageStateManager.ts');
    bgm({ content, args: [{ key: 'enter', value: enter }] });
    stageStateManager.commit();
  }, { content, enter });
}

async function waitForTrack(page, track) {
  await page.waitForFunction(expected => {
    const player = document.getElementById('currentBgm');
    return player && !player.paused && player.currentTime > 0.12 && player.currentSrc.endsWith(expected);
  }, track, { timeout: 10000 });
}

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 580 } });
    await page.addInitScript(() => {
      window.AndroidBridge = {
        getStartupOpeningResult: () => 'played',
        getToolbarInsets: () => '0,0,0',
      };
    });
    await enterDiscTitle(page, origin);
    await discButton(page, '开始游戏').click();
    await page.waitForFunction(() => document.getElementById('currentBgm')?.getAttribute('src') == null);

    const player = page.locator('#currentBgm');
    await applyBgmCommand(page, firstTrack);
    await waitForTrack(page, firstTrack);
    const oldPlayer = await player.elementHandle();
    await applyBgmCommand(page, '');
    await page.waitForFunction(() => document.getElementById('currentBgm')?.getAttribute('src') == null);
    assert.equal(await oldPlayer.evaluate(audio => audio.paused), true, 'old audio must stop immediately');
    assert.equal(await player.evaluate(audio => audio.currentSrc), '', 'silent stage must have no active source');
    const stoppedTime = await oldPlayer.evaluate(audio => audio.currentTime);
    await page.waitForTimeout(300);
    assert.equal(await oldPlayer.evaluate(audio => audio.currentTime), stoppedTime);

    await applyBgmCommand(page, firstTrack);
    await waitForTrack(page, firstTrack);
    await applyBgmCommand(page, '', 240);
    await page.waitForFunction(() => {
      const audio = document.getElementById('currentBgm');
      return audio?.paused && !audio.currentSrc;
    }, null, { timeout: 3500 });

    await applyBgmCommand(page, firstTrack);
    await waitForTrack(page, firstTrack);
    await applyBgmCommand(page, '', 400);
    await page.waitForTimeout(80);
    await applyBgmCommand(page, secondTrack);
    await waitForTrack(page, secondTrack);
    await page.waitForTimeout(500);
    assert.equal(await player.evaluate(audio => audio.paused), false);
    assert.match(await player.evaluate(audio => audio.currentSrc), /SE_00149\.mp3$/);
    console.log('PASS: instant stop, same-track restart, fade-out stop, and track replacement during fade-out');
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
