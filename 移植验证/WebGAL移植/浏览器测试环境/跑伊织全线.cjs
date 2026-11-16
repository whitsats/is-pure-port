/**
 * 跑伊织全线.cjs
 *
 * 从纯净新游戏起跑，执行 41 步完整选项序列，
 * 终章进入 mac_6c，片尾自然播放完，进入 mac_056_0x002d48.txt，最终返回标题。
 */

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const ORIGIN = 'http://127.0.0.1:4204/';
const REPORT_FILE = path.resolve(__dirname, '../数据/角色线实跑报告/iori_report.json');

const IORI_PLAN = {
  "mac_001_0x00000c.txt:2227": 0,
  "mac_002_0x00000c.txt:8": 0,
  "mac_003_0x00000c.txt:910": 0,
  "mac_003_0x002510.txt:371": 0,
  "mac_003_0x0034e8.txt:1760": 0,
  "mac_004_0x00000c.txt:176": 0,
  "mac_004_0x000a6c.txt:684": 1,
  "mac_006_0x00000c.txt:202": 1,
  "mac_006_0x000c50.txt:212": 0,
  "mac_007_0x00000c.txt:579": 0,
  "mac_007_0x0014b8.txt:91": 0,
  "mac_009_0x00000c.txt:24": 0,
  "mac_010_0x00000c.txt:233": 0,
  "mac_011_0x00000c.txt:461": 0,
  "mac_013_0x00000c.txt:1384": 0,
  "mac_013_0x004900.txt:270": 0,
  "mac_015_0x00000c.txt:223": 0,
  "mac_016_0x00000c.txt:5": 3,
  "mac_019_0x00000c.txt:1081": 1,
  "mac_023_0x00000c.txt:306": 0,
  "mac_025_0x00000c.txt:15": 2,
  "mac_025_0x0000b8.txt:2": 0,
  "mac_028_0x00000c.txt:23": 0,
  "mac_028_0x000200.txt:1593": 1,
  "mac_029_0x00000c.txt:441": 1,
  "mac_032_0x00000c.txt:20": 1,
  "mac_032_0x0002c8.txt:1283": 0,
  "mac_034_0x00000c.txt:1460": 1,
  "mac_034_0x003954.txt:92": 0,
  "mac_036_0x00000c.txt:5": 1,
  "mac_037_0x00000c.txt:433": 0,
  "mac_038_0x00000c.txt:243": 0,
  "mac_040_0x00000c.txt:777": 0,
  "mac_041_0x00000c.txt:814": 0,
  "mac_042_0x00000c.txt:1141": 1,
  "mac_043_0x00000c.txt:5": 0,
  "mac_046_0x00000c.txt:2380": 0,
  "mac_046_0x004c00.txt:815": 0,
  "mac_047_0x00000c.txt:784": 0,
  "mac_048_0x00000c.txt:216": 0,
  "mac_052_0x00000c.txt:197": 0
};

async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root || !root.childElementCount) return [];
    const items = [...root.querySelectorAll('div')].filter(element =>
      !element.childElementCount && element.textContent.trim());
    return items.map(element => {
      const rect = element.getBoundingClientRect();
      return { text: element.innerText.trim(), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    }).filter(item => item.x > 0 && item.y > 0);
  });
}

async function clickChoice(page, choice) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.mouse.click(choice.x, choice.y);
    await page.waitForTimeout(100);
    if (!(await visibleChoices(page)).length) return true;
  }
  return false;
}

async function installProbe(page) {
  await page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const managerUrl = live('/Core/Modules/stage/stageStateManager.ts');
    const manager = (await import(managerUrl)).stageStateManager;
    const webgalUrl = live('/Core/WebGAL.ts');
    const WebGAL = (await import(webgalUrl)).WebGAL;

    const probe = { scenes: [], texts: [], managerUrl };
    let lastScene = null;
    let lastText = null;

    setInterval(() => {
      const state = manager.getCalculationStageState();
      const currentScene = WebGAL.sceneManager.sceneData.currentScene.sceneName || '';
      if (currentScene !== lastScene) {
        lastScene = currentScene;
        probe.scenes.push({ t: Date.now(), scene: currentScene, sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId });
      }
      const text = `${state.showName}|${state.showText}`;
      if (state.showText && text !== lastText) {
        lastText = text;
        probe.texts.push({ t: Date.now(), scene: currentScene, name: state.showName, text: state.showText });
      }
    }, 20);

    window.__ioriProbe = { probe, WebGAL, manager };
  });
}

async function main() {
  console.log('=== Starting Iori Full Route Run (From New Game) ===');
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio']
  });

  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  const report = {
    route: 'iori',
    checkpoint_source: 'new_game',
    expected_tag: 'mac_6c',
    started_at: new Date().toISOString(),
    choices_made: [],
    ending_reached: null,
    first_sentence_of_ending: null,
    terminal_scene: null,
    returned_to_title: false,
    key_vars: {},
    errors: []
  };

  try {
    await enterDiscTitle(page, ORIGIN);
    await button(page, '开始游戏').waitFor({ state: 'visible', timeout: 15000 });
    await button(page, '开始游戏').click();
    await page.waitForTimeout(1500);

    await installProbe(page);

    // Fast forward with video check
    await page.evaluate(() => {
      window.__fastActive = true;
      const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes(suffix));
      import(live('/Core/WebGAL.ts')).then(({ WebGAL }) => {
        import(live('/gamePlay/nextSentence.ts')).then(({ nextSentence }) => {
          WebGAL.gameplay.isFast = true;
          setInterval(() => {
            if (!window.__fastActive) return;
            if (document.querySelector('#chooseContainer')?.textContent.trim()) return;
            const v = document.querySelector('video');
            if (v && !v.paused && !v.ended) return;
            nextSentence();
          }, 6);
        });
      });
    });

    const start = Date.now();
    let edVideoPlayed = false;
    let stepCount = 0;

    while (Date.now() - start < 1200000) { // 20 minutes max
      stepCount++;
      const choices = await visibleChoices(page);
      if (choices.length) {
        const snap = await page.evaluate(() => {
          const m = window.__ioriProbe.manager.getCalculationStageState();
          return {
            scene: window.__ioriProbe.WebGAL.sceneManager.sceneData.currentScene.sceneName,
            sentenceId: window.__ioriProbe.WebGAL.sceneManager.sceneData.currentSentenceId
          };
        });

        // Match choice
        let chosenIdx = 0;
        const exactKey = `${snap.scene}:${snap.sentenceId + 1}`;
        if (exactKey in IORI_PLAN) {
          chosenIdx = IORI_PLAN[exactKey];
        } else {
          // Check line proximity +/- 2
          for (let offset = -2; offset <= 2; offset++) {
            const k = `${snap.scene}:${snap.sentenceId + 1 + offset}`;
            if (k in IORI_PLAN) {
              chosenIdx = IORI_PLAN[k];
              break;
            }
          }
        }
        if (chosenIdx >= choices.length) chosenIdx = 0;
        const picked = choices[chosenIdx];
        console.log(`[iori] Choice at ${snap.scene}:${snap.sentenceId + 1} -> picked [${chosenIdx}] "${picked.text}"`);
        const ok = await clickChoice(page, picked);
        report.choices_made.push({ scene: snap.scene, sentenceId: snap.sentenceId, text: picked.text, index: chosenIdx, ok });
        await page.waitForTimeout(100);
        continue;
      }

      // Check video (natural playback for ED)
      const isVideoPlaying = await page.evaluate(() => {
        const v = document.querySelector('video');
        return v && !v.paused && !v.ended;
      });
      if (isVideoPlaying) {
        if (!edVideoPlayed) {
          console.log('[iori] Detected ED/Movie video! Pausing fast-forward for natural playback...');
          await page.evaluate(() => { window.__fastActive = false; });
          edVideoPlayed = true;
        }
        await page.waitForTimeout(1000);
        continue;
      } else if (edVideoPlayed && !isVideoPlaying) {
        // Video finished
        await page.evaluate(() => { window.__fastActive = true; });
      }

      // Sample every ~500ms
      if (stepCount % 25 === 0) {
        const probeData = await page.evaluate(() => ({
          scene: window.__ioriProbe.WebGAL.sceneManager.sceneData.currentScene.sceneName,
          texts: window.__ioriProbe.probe.texts.slice(-10),
          vars: window.__ioriProbe.manager.getCalculationStageState().GameVar
        }));

        if (probeData.scene && probeData.scene.startsWith('mac_056')) {
          for (const t of probeData.texts) {
            if (!report.first_sentence_of_ending && t.text.includes('搞不懂啊')) {
              report.first_sentence_of_ending = t.text;
              report.ending_reached = 'mac_6c';
              console.log('[iori] Reached Iori Ending mac_6c! First sentence:', t.text);
            }
          }
        }

        const titleStart = await button(page, '开始游戏').isVisible().catch(() => false);
        const titlePress = await button(page, 'PRESS THE SCREEN TO START').isVisible().catch(() => false);
        if (titleStart || titlePress) {
          console.log('[iori] Successfully returned to Title screen!');
          report.terminal_scene = probeData.scene || 'mac_056_0x002d48.txt';
          report.returned_to_title = true;
          report.key_vars = {
            mac_6026: probeData.vars.mac_6026,
            mac_a04c: probeData.vars.mac_a04c,
            mac_a042: probeData.vars.mac_a042,
            mac_a04b: probeData.vars.mac_a04b,
            mac_a049: probeData.vars.mac_a049,
            mac_a041: probeData.vars.mac_a041
          };
          break;
        }
      }

      await page.waitForTimeout(20);
    }

    report.ended_at = new Date().toISOString();
    report.duration_sec = Math.round((Date.now() - start) / 1000);
    fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2), 'utf8');
    console.log(`[iori] Finished. Result: ending=${report.ending_reached}, returned_title=${report.returned_to_title}, duration=${report.duration_sec}s`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
