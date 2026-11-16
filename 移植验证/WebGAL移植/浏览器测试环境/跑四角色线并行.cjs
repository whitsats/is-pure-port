/**
 * 跑四角色线并行.cjs
 *
 * 启动四个独立的 Playwright BrowserContext，共用 http://127.0.0.1:4204/。
 * 每条线分别写独立的存档、日志和报告：
 * 1. 伊织线：纯净新游戏起跑，执行 41 步序列，终章进入 mac_6c，片尾自然播完，汇合到 mac_056_0x002d48.txt 返回标题。
 * 2. 季子线：从第 44 章检查点选择「叫住她」，终章进入 mac_608，返回标题。
 * 3. 泉线：从第 50 章检查点出发，依该档的剧情旗标进入 mac_cd8，返回标题。
 * 4. 蓝子线：Playwright route 拦截 start.txt 注入 ch50 检查点，选「我也是一样的心情！」，终章进入 mac_1c88，返回标题。
 */

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const ORIGIN = 'http://127.0.0.1:4204/';
const REPORT_DIR = path.resolve(process.env.DISC_ROUTE_REPORT_DIR || path.join(__dirname, '../数据/角色线实跑报告'));
const MAX_ROUTE_MS = 30 * 60 * 1000;
if (!fs.existsSync(REPORT_DIR)) fs.mkdirSync(REPORT_DIR, { recursive: true });

const CHECKPOINTS = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/四角色线检查点.json'), 'utf8'));

// 伊织线 41 步完整序列
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

function generateStartTxt(vars, targetScene) {
  const lines = [];
  for (const [k, v] of Object.entries(vars)) {
    lines.push(`setVar:${k}=${v} -next;`);
  }
  lines.push(`changeScene:${targetScene};`);
  return lines.join('\r\n');
}

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
    if (!managerUrl) throw new Error('页面没有加载 stageStateManager');
    const manager = (await import(managerUrl)).stageStateManager;
    const webgalUrl = live('/Core/WebGAL.ts');
    const WebGAL = webgalUrl ? (await import(webgalUrl)).WebGAL : null;

    const sceneName = () => {
      try { return WebGAL.sceneManager.sceneData.currentScene.sceneName || ''; } catch (error) { return ''; }
    };
    const snapshot = () => {
      const state = manager.getCalculationStageState();
      const data = {
        scene: sceneName(),
        showText: state.showText || '',
        showName: state.showName || '',
        choose: (state.choose || []).map(item => item.text || item.key),
        GameVar: { ...state.GameVar }
      };
      try {
        data.sentenceId = WebGAL.sceneManager.sceneData.currentSentenceId;
      } catch (e) {
        data.sentenceId = -1;
      }
      return data;
    };

    const probe = { scenes: [], texts: [], choices: [], snapshot, managerUrl };
    let lastScene = null;
    let lastText = null;
    let lastChoice = '';

    const recordText = () => {
      const state = manager.getCalculationStageState();
      const key = `${state.showName}|${state.showText}`;
      if (state.showText && key !== lastText) {
        lastText = key;
        probe.texts.push({ t: Date.now(), scene: sceneName(), name: state.showName, text: state.showText });
      }
    };
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(recordText).observe(document.body, { subtree: true, childList: true, characterData: true });
    }

    probe.timer = setInterval(() => {
      const data = snapshot();
      if (data.scene !== lastScene) {
        lastScene = data.scene;
        probe.scenes.push({ t: Date.now(), scene: data.scene, sentenceId: data.sentenceId, GameVar: { ...data.GameVar } });
      }
      const text = `${data.showName}|${data.showText}`;
      if (data.showText && text !== lastText) {
        lastText = text;
        probe.texts.push({ t: Date.now(), scene: data.scene, name: data.showName, text: data.showText });
      }
      const choiceKey = `${data.scene}#${data.choose.join('\u0001')}`;
      if (data.choose.length && choiceKey !== lastChoice) {
        lastChoice = choiceKey;
        probe.choices.push({ t: Date.now(), scene: data.scene, options: data.choose.slice() });
      }
      if (!data.choose.length) lastChoice = '';
    }, 15);

    window.__probe = probe;
  });
}

async function runRoute(browser, routeName, config) {
  const log = (...args) => console.log(`[${routeName}]`, ...args);
  log('Starting route run...');

  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });

  // If checkpoint interception is specified
  if (config.checkpoint) {
    const cpData = CHECKPOINTS[config.checkpoint];
    const customStart = generateStartTxt(cpData.GameVar, cpData.scene);
    await context.route('**/scene/start.txt', route => {
      log(`Intercepted start.txt! Injecting checkpoint ${config.checkpoint} -> scene: ${cpData.scene}`);
      route.fulfill({
        status: 200,
        contentType: 'text/plain',
        body: customStart
      });
    });
  }

  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', err => {
    errors.push(err.message);
    log('PAGEERROR:', err.message);
  });

  const report = {
    route: routeName,
    checkpoint_source: config.checkpoint || 'new_game',
    expected_tag: config.expected_tag,
    started_at: new Date().toISOString(),
    choices_made: [],
    ending_reached: null,
    first_sentence_of_ending: null,
    terminal_scene: null,
    returned_to_title: false,
    key_vars: {},
    errors
  };

  try {
    await enterDiscTitle(page, ORIGIN);
    await button(page, '开始游戏').waitFor({ state: 'visible', timeout: 15000 });
    await button(page, '开始游戏').click();
    await page.waitForTimeout(1500);

    await installProbe(page);

    // Fast-forward controller
    await page.evaluate(() => {
      window.__fastEnabled = true;
      const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes(suffix));
      import(live('/Core/WebGAL.ts')).then(({ WebGAL }) => {
        import(live('/gamePlay/nextSentence.ts')).then(({ nextSentence }) => {
          WebGAL.gameplay.isFast = true;
          window.__probe.fastTimer = setInterval(() => {
            if (!window.__fastEnabled) return;
            // Pause if choice is visible
            if (document.querySelector('#chooseContainer')?.textContent.trim()) return;
            // Pause if video is playing
            if (document.getElementById('playVideoElement')) return;
            nextSentence();
          }, 8);
        });
      });
    });

    const start = Date.now();
    const plan = config.plan || {};
    let stallCount = 0;
    let lastSig = '';
    let edVideoHandled = false;

    while (Date.now() - start < MAX_ROUTE_MS) {
      // 1. Check for options
      const choices = await visibleChoices(page);
      if (choices.length) {
        const snap = await page.evaluate(() => window.__probe.snapshot());
        const key = `${snap.scene}:${snap.sentenceId}`;
        let chosenIdx = 0;
        if (key in plan) {
          chosenIdx = plan[key];
        } else if (snap.scene in plan) {
          chosenIdx = plan[snap.scene];
        }
        if (chosenIdx >= choices.length) chosenIdx = 0;
        const picked = choices[chosenIdx];
        log(`Choice at ${key}: picked [${chosenIdx}] "${picked.text}" among ${JSON.stringify(choices.map(c => c.text))}`);
        const ok = await clickChoice(page, picked);
        report.choices_made.push({ scene: snap.scene, sentenceId: snap.sentenceId, text: picked.text, index: chosenIdx, ok });
        await page.waitForTimeout(120);
        continue;
      }

      // 2. Check for video / ED
      const isVideoPlaying = await page.evaluate(() => {
        return !!document.getElementById('playVideoElement');
      });
      if (isVideoPlaying) {
        if (!edVideoHandled) {
          log('Detected video playing (ED/Movie). Pausing fast-forward for natural playback...');
          await page.evaluate(() => { window.__fastEnabled = false; });
          edVideoHandled = true;
        }
        await page.waitForTimeout(500);
        continue;
      } else if (edVideoHandled && !isVideoPlaying) {
        // Video finished, resume or proceed
        await page.evaluate(() => { window.__fastEnabled = true; });
      }

      // 3. Click upper screen to push if fast is paused
      await page.mouse.click(640, 80);
      await page.waitForTimeout(30);

      // 4. Sample state & ending check
      const snap = await page.evaluate(() => window.__probe.snapshot());
      const sig = `${snap.scene}#${snap.sentenceId}`;
      if (sig === lastSig) {
        stallCount++;
      } else {
        lastSig = sig;
        stallCount = 0;
      }

      // Check ending scenes
      if (snap.scene && snap.scene.startsWith('mac_056')) {
        if (Object.keys(snap.GameVar).length > 0) report.key_vars = snap.GameVar;
        // Look for ending branch label and first sentence
        const probeData = await page.evaluate(() => ({
          scenes: window.__probe.scenes,
          texts: window.__probe.texts.slice(-30)
        }));

        for (const t of probeData.texts) {
          if (!report.first_sentence_of_ending) {
            if (routeName === 'iori' && t.text.includes('搞不懂啊')) {
              report.first_sentence_of_ending = t.text;
              report.ending_reached = 'mac_6c';
              log('Reached Iori ending mac_6c! First sentence:', t.text);
            } else if (routeName === 'itsuki' && t.text.includes('连你也要走了啊')) {
              report.first_sentence_of_ending = t.text;
              report.ending_reached = 'mac_608';
              log('Reached Itsuki ending mac_608! First sentence:', t.text);
            } else if (routeName === 'izumi' && t.text.includes('要迟到了要迟到了')) {
              report.first_sentence_of_ending = t.text;
              report.ending_reached = 'mac_cd8';
              log('Reached Izumi ending mac_cd8! First sentence:', t.text);
            } else if (routeName === 'aiko' && t.text.includes('嗯……嗯嗯……')) {
              report.first_sentence_of_ending = t.text;
              report.ending_reached = 'mac_1c88';
              log('Reached Aiko ending mac_1c88! First sentence:', t.text);
            }
          }
        }
      }

      // Check return to title
      if (snap.scene === 'mac_056_0x002d48.txt') report.terminal_scene = snap.scene;
      const titleStart = await button(page, '开始游戏').isVisible().catch(() => false);
      const titlePress = await button(page, 'PRESS THE SCREEN TO START').isVisible().catch(() => false);
      if (titleStart || titlePress) {
        if (!report.terminal_scene) {
          report.terminal_scene = await page.evaluate(() => window.__probe.scenes
            .findLast(item => item.scene === 'mac_056_0x002d48.txt')?.scene ?? null);
        }
        log('Successfully returned to Title screen!');
        report.returned_to_title = true;
        break;
      }

      if (stallCount >= 180) {
        log(`Warning: Possible stall at ${snap.scene}:${snap.sentenceId} text: "${snap.showText}"`);
        report.stall = { scene: snap.scene, sentenceId: snap.sentenceId, text: snap.showText, GameVar: snap.GameVar };
        break;
      }
    }

    report.ended_at = new Date().toISOString();
    report.duration_sec = Math.round((Date.now() - start) / 1000);
    fs.writeFileSync(path.join(REPORT_DIR, `${routeName}_report.json`), JSON.stringify(report, null, 2), 'utf8');
    log(`Finished route ${routeName}. Result: ending=${report.ending_reached}, returned_title=${report.returned_to_title}`);
  } finally {
    await context.close();
  }

  return report;
}

async function main() {
  console.log('=== Starting 4 Heroine Routes in Parallel Playwright Contexts ===');
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio']
  });

  const routes = [
    {
      name: 'iori',
      config: {
        checkpoint: null, // Full run from new game
        expected_tag: 'mac_6c',
        plan: IORI_PLAN
      }
    },
    {
      name: 'itsuki',
      config: {
        checkpoint: 'itsuki',
        expected_tag: 'mac_608',
        plan: CHECKPOINTS.itsuki.plan
      }
    },
    {
      name: 'izumi',
      config: {
        checkpoint: 'izumi',
        expected_tag: 'mac_cd8',
        plan: CHECKPOINTS.izumi.plan
      }
    },
    {
      name: 'aiko',
      config: {
        checkpoint: 'aiko',
        expected_tag: 'mac_1c88',
        plan: CHECKPOINTS.aiko.plan
      }
    }
  ];

  try {
    const results = await Promise.allSettled(routes.map(r => runRoute(browser, r.name, r.config)));
    console.log('\n=== All 4 Routes Completed ===');
    for (const [index, result] of results.entries()) {
      if (result.status === 'rejected') {
        console.error(`[${routes[index].name}] Run failed:`, result.reason);
        process.exitCode = 1;
        continue;
      }
      const res = result.value;
      console.log(`[${res.route.toUpperCase()}] Tag: ${res.ending_reached} (Expected: ${res.expected_tag}) | Title: ${res.returned_to_title} | FirstSentence: "${res.first_sentence_of_ending}"`);
      if (res.ending_reached !== res.expected_tag || !res.returned_to_title || res.errors.length) {
        process.exitCode = 1;
      }
    }
  } catch (err) {
    console.error('Fatal error during parallel run:', err);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
