// 在真实默认主线路径中捕获每个实际出现的选项点。
// 不改 GameVar：用 WebGAL 的 generateCurrentStageData(0,false) 从运行时生成原生 ISaveData。
// 用法：node 捕获分支检查点.cjs --report ../数据/分支检查点.json

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle} = require('./进入打盘版标题.cjs');
const OUTPUT = path.resolve(__dirname, process.argv.includes('--report')
  ? process.argv[process.argv.indexOf('--report') + 1]
  : '../数据/分支检查点.json');
const ORIGIN = 'http://127.0.0.1:4203/';

const button = (page, label) => page.getByText(label, { exact: true }).first();
async function clickStart(page) {
  await enterDiscTitle(page, ORIGIN);
  await page.waitForTimeout(300);
  const language = button(page, '简体中文');
  if (await language.isVisible().catch(() => false)) await language.click();
  await page.waitForTimeout(300);
  const starts = page.getByText('开始游戏', { exact: true });
  let found = false;
  for (let i = 0; i < await starts.count(); i++) {
    if (await starts.nth(i).isVisible().catch(() => false)) { await starts.nth(i).click(); found = true; break; }
  }
  if (!found) throw new Error('没有可见的开始游戏选项');
  await page.waitForTimeout(500);
}
async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root) return [];
    return [...root.querySelectorAll('div')].filter(e => !e.childElementCount && e.textContent.trim()).map(e => {
      const r = e.getBoundingClientRect(); return { text: e.textContent.trim(), x: r.x + r.width / 2, y: r.y + r.height / 2 };
    }).filter(e => e.x > 0 && e.y > 0);
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio'] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  const checkpoints = [];
  const seen = new Set();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await clickStart(page);
    await page.waitForTimeout(900);
    const modules = await page.evaluate(() => {
      const resources = performance.getEntriesByType('resource').map(e => e.name);
      return {
        stateUrl: resources.find(n => n.includes('/Core/Modules/stage/stageStateManager.ts')),
        webgalUrl: resources.find(n => n.includes('/Core/WebGAL.ts')),
        saveUrl: resources.find(n => n.includes('/Core/controller/storage/saveGame.ts')),
      };
    });
    if (!modules.saveUrl || !modules.stateUrl || !modules.webgalUrl) throw new Error(`运行时模块未出现：${JSON.stringify(modules)}`);
    let noProgress = 0;
    let lastScene = '';
    const started = Date.now();
    for (let clicks = 0; clicks < 36000 && Date.now() - started < 1500_000; ) {
      const options = await visibleChoices(page);
      if (options.length) {
        const actual = await page.evaluate(async urls => {
          const manager = (await import(urls.stateUrl)).stageStateManager;
          const WebGAL = (await import(urls.webgalUrl)).WebGAL;
          const save = await import(urls.saveUrl);
          const scene = WebGAL.sceneManager.sceneData.currentScene.sceneName;
          const state = manager.getCalculationStageState();
          const choices = [...document.querySelectorAll('#chooseContainer div')]
            .filter(e => !e.childElementCount && e.textContent.trim())
            .map(e => e.textContent.trim());
          const checkpoint = save.generateCurrentStageData(0, false);
          return { scene, sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
                   choices, GameVar: { ...state.GameVar }, checkpoint };
        }, modules);
        const key = `${actual.scene}|${actual.sentenceId}`;
        if (!seen.has(key)) {
          seen.add(key);
          checkpoints.push(actual);
          fs.writeFileSync(OUTPUT, JSON.stringify({ origin: ORIGIN, modules,
            captured_at: new Date().toISOString(), checkpoints, errors }, null, 2));
          console.log(`checkpoint ${checkpoints.length}: ${actual.scene} [${actual.choices.length}]`);
        }
        const picked = options[0];
        await page.mouse.click(picked.x, picked.y);
        await page.waitForTimeout(60);
        clicks++;
        continue;
      }
      await page.mouse.click(640, 80);
      clicks++;
      if (clicks % 80 === 0) {
        const scene = await page.evaluate(async url => {
          const W = (await import(url)).WebGAL;
          return W.sceneManager.sceneData.currentScene.sceneName;
        }, modules.webgalUrl);
        if (scene === lastScene) noProgress++; else { lastScene = scene; noProgress = 0; }
        if (noProgress > 120) break;
        if (!scene && checkpoints.length) break;
      }
      if (clicks % 500 === 0) console.log(`clicks ${clicks}; checkpoints ${checkpoints.length}`);
    }
  } finally {
    await context.close(); await browser.close();
  }
  console.log(`完成：${checkpoints.length} 个真实检查点，报告 ${OUTPUT}，pageerror=${errors.length}`);
})().catch(error => { console.error(error); process.exit(1); });
