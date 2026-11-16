const button = (page, text) => {
  const exact = page.getByText(text, {exact: true}).and(page.locator(':visible'));
  const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const layered = page.locator('.App div:visible').filter({
    hasText: new RegExp(`^(?:${escaped}){3}$`),
  });
  return exact.or(layered).first();
};

async function enterDiscTitle(page, origin = 'http://127.0.0.1:4203/', options = {}) {
  await page.goto(origin, {waitUntil: 'domcontentloaded'});
  const opening = page.locator('video[src*="MV_OP01_phone60"]');
  const start = button(page, '开始游戏');
  const launch = button(page, 'PRESS THE SCREEN TO START');
  const language = button(page, '简体中文');
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await button(page, '播放片头').isVisible()) await button(page, '播放片头').click();
    else if (await opening.isVisible()) {
      if (options.waitForOpeningPlayback) {
        const playing = await opening.evaluate(video => video.currentTime > 0).catch(() => false);
        if (!playing) {
          await page.waitForTimeout(150);
          continue;
        }
      }
      await opening.click();
    }
    else if (await start.isVisible()) return;
    else if (await launch.isVisible()) await launch.click();
    else if (await language.isVisible()) await language.click();
    await page.waitForTimeout(150);
  }
  throw new Error(`未到达打盘版标题 ${await page.locator('body').innerText()}`);
}

module.exports = {enterDiscTitle, discButton: button};
