const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton } = require('./进入打盘版标题.cjs');

const origin = process.env.IS_PURE_WEBGAL_URL || 'http://127.0.0.1:4204/';
const firstTrack = 'IS_Pure_BGM_SE_00146.mp3';
const secondTrack = 'IS_Pure_BGM_SE_00149.mp3';

async function advanceUntil(page, check, message) {
  for (let attempt = 0; attempt < 8; attempt++) {
    if (await check()) return;
    await page.mouse.click(612, 365);
    await page.waitForTimeout(220);
  }
  assert.fail(message);
}

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 620 } });
    await page.addInitScript(() => {
      window.AndroidBridge = {
        getStartupOpeningResult: () => 'played',
        getToolbarInsets: () => '0,0,0',
      };
    });
    const scene = [
      'bgm:' + firstTrack + ' -next;',
      '第一首播放中。;',
      'bgm:none -next;',
      '立即停播。;',
      'bgm:' + firstTrack + ' -next;',
      '重播同一首。;',
      'bgm:none -enter=240 -next;',
      '淡出并停播。;',
      'bgm:' + firstTrack + ' -next;',
      '再次重播。;',
      'bgm:none -enter=2000 -next;',
      '正在淡出。;',
      'bgm:' + secondTrack + ' -next;',
      '第二首播放中。;',
    ].join('\n');
    await page.route('**/game/scene/start.txt*', route => route.fulfill({
      body: scene,
      contentType: 'text/plain; charset=utf-8',
    }));
    await enterDiscTitle(page, origin);
    await discButton(page, '开始游戏').click();

    const player = page.locator('#currentBgm');
    const state = () => player.evaluate(audio => ({
      src: audio.currentSrc,
      paused: audio.paused,
      time: audio.currentTime,
      volume: audio.volume,
    }));
    const playing = file => async () => {
      const audio = await state();
      return !audio.paused && audio.time > 0.1 && audio.src.endsWith(file);
    };
    const silent = async () => {
      const audio = await state();
      return audio.paused && !audio.src;
    };

    await page.waitForFunction(file => {
      const audio = document.getElementById('currentBgm');
      return audio && !audio.paused && audio.currentTime > 0.1 && audio.currentSrc.endsWith(file);
    }, firstTrack);
    const oldPlayer = await player.elementHandle();
    await advanceUntil(page, silent, 'bgm:none must stop the previous track');
    assert.equal(await oldPlayer.evaluate(audio => audio.paused), true);
    const stoppedAt = await oldPlayer.evaluate(audio => audio.currentTime);
    await page.waitForTimeout(300);
    assert.equal(await oldPlayer.evaluate(audio => audio.currentTime), stoppedAt);

    await advanceUntil(page, playing(firstTrack), 'the same track must restart');
    await advanceUntil(page, silent, 'fade-out must end in silence');
    await advanceUntil(page, playing(firstTrack), 'restart after fade-out');
    const beforeFade = await state();
    await advanceUntil(page, async () => {
      const audio = await state();
      return audio.src === beforeFade.src && !audio.paused && audio.volume < beforeFade.volume;
    }, 'the first track must begin to fade');
    await advanceUntil(page, playing(secondTrack), 'the incoming track must start during the old fade');
    await page.waitForTimeout(2100);
    assert.equal(await playing(secondTrack)(), true, 'the old fade must not stop the second track');
    console.log('PASS: instant stop, same-track restart, fade-out stop, and track replacement during fade-out');
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
