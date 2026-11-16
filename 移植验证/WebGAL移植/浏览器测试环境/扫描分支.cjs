// 逐选项分支扫描：对主线报告的每个选项点、每个选项各跑一次。
// 每次只把 扫描分支/w<N>/public/game/scene/start.txt 改成“初始化变量 + changeScene:<该选项场景>”，
// 然后从开局按钮真实点击到选项，点选目标项，继续点击到回归主线 / end / 卡住。
//
// 用法（在 浏览器测试环境）：node 扫描分支.cjs [--workers 3] [--only mac_009_0x00000c.txt]

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const MAIN = path.resolve(__dirname, '../数据/主线实跑_全流程.json');
const SAMPLE_SCENE = path.resolve(__dirname, '../新游戏打盘版/public/game/scene');
const SCAN_ROOT = path.resolve(__dirname, '../scan');
const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index > -1 ? process.argv[index + 1] : fallback;
};
const WORKERS = Number(arg('--workers', 3));
const ONLY = arg('--only', null);
const OPTION_INDEX = arg('--option-index', null);
const PORTS = Array.from({ length: WORKERS }, (_, index) => Number(arg('--port-base', 4212)) + index);

const main = JSON.parse(fs.readFileSync(MAIN, 'utf8'));
const mainlineScenes = [];
for (const event of main.probe.scenes) {
  if (event.scene && mainlineScenes[mainlineScenes.length - 1] !== event.scene) mainlineScenes.push(event.scene);
}
const varHeader = fs.readFileSync(path.join(SAMPLE_SCENE, 'start.txt'), 'utf8').split(/\r?\n/)
  .filter(line => line.startsWith('setVar:'));

// 选项点：按场景去重，保留报告里见到的选项文本与项数。
const points = [];
for (const choice of main.choices) {
  if (!choice.scene) continue;
  const known = points.find(point => point.scene === choice.scene);
  if (known) continue;
  points.push({ scene: choice.scene, options: choice.options.slice() });
}
const selected = ONLY ? points.filter(point => point.scene === ONLY) : points;

const tasks = [];
for (const point of selected) {
  for (let index = 0; index < point.options.length; index++) {
    if (OPTION_INDEX !== null && index !== Number(OPTION_INDEX)) continue;
    tasks.push({ scene: point.scene, index, expected: point.options });
  }
}

const button = (page, name) => page.getByText(name, { exact: true }).first();

function writeJump(worker, scene) {
  const file = path.join(SCAN_ROOT, `w${worker}/public/game/scene/start.txt`);
  fs.writeFileSync(file, `${varHeader.join('\n')}\nchangeScene:${scene};\n`);
}

async function clickVisibleLast(page, label) {
  const matches = page.getByText(label, { exact: true });
  for (let index = await matches.count() - 1; index >= 0; index--) {
    const candidate = matches.nth(index);
    if (await candidate.isVisible().catch(() => false)) {
      await candidate.click({ timeout: 12000 });
      return true;
    }
  }
  return false;
}

async function startGame(page, port) {
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'networkidle' });
  await button(page, 'PRESS THE SCREEN TO START').first().click();
  await page.waitForTimeout(500);
  const chinese = button(page, '简体中文');
  if (await chinese.isVisible().catch(() => false)) await chinese.click();
  await page.waitForTimeout(500);
  const start = button(page, '开始游戏');
  let visibleStart = null;
  for (let i = 0; i < await start.count(); i++) {
    if (await start.nth(i).isVisible().catch(() => false)) { visibleStart = start.nth(i); break; }
  }
  if (!visibleStart) throw new Error('开始游戏菜单项没有可见文本实例');
  await visibleStart.click();
  await page.waitForTimeout(600);
}

async function installProbe(page) {
  await page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const manager = (await import(live('/Core/Modules/stage/stageStateManager.ts'))).stageStateManager;
    const webgalUrl = live('/Core/WebGAL.ts');
    const WebGAL = webgalUrl ? (await import(webgalUrl)).WebGAL : null;
    const scene = () => {
      try { return WebGAL.sceneManager.sceneData.currentScene.sceneName || ''; } catch (error) { return ''; }
    };
    const probe = { texts: [], scenes: [], snapshot: () => {
      const state = manager.getCalculationStageState();
      let sentenceId = -1;
      try { sentenceId = WebGAL.sceneManager.sceneData.currentSentenceId; } catch (error) { sentenceId = -1; }
      return { scene: scene(), sentenceId, showText: state.showText || '', showName: state.showName || '',
               GameVar: { ...state.GameVar } };
    } };
    let lastScene = null;
    let lastText = null;
    probe.timer = setInterval(() => {
      const data = probe.snapshot();
      if (data.scene !== lastScene) {
        lastScene = data.scene;
        probe.scenes.push({ t: Date.now(), scene: data.scene });
      }
      const key = `${data.showName}|${data.showText}`;
      if (data.showText && key !== lastText) {
        lastText = key;
        probe.texts.push({ t: Date.now(), scene: data.scene, name: data.showName, text: data.showText });
      }
    }, 10);
    window.__probe = probe;
  });
}

const snapshot = page => page.evaluate(() => window.__probe.snapshot());

async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root || !root.childElementCount) return [];
    return [...root.querySelectorAll('div')].filter(element => !element.childElementCount && element.textContent.trim())
      .map(element => {
        const rect = element.getBoundingClientRect();
        return { text: element.textContent.trim(), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      }).filter(item => item.x > 0 && item.y > 0);
  });
}

const endSeen = page => page.evaluate(() =>
  window.__probe.texts.some(item => item.text.includes('0x2D88')));

async function runTask(browser, task, worker) {
  const port = PORTS[worker];
  writeJump(worker, task.scene);
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const voices = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    const file = new URL(response.url()).pathname.split('/').pop() || '';
    if (/^VOICE_\d+\.wav$/i.test(file)) voices.push({ t: Date.now(), file, status: response.status() });
  });
  const result = { scene: task.scene, index: task.index, expected_options: task.expected, started_at: Date.now() };
  try {
    await startGame(page, port);
    await installProbe(page);
    let options = [];
    for (let click = 0; click < 900 && !options.length; click++) {
      options = await visibleChoices(page);
      if (!options.length) await page.mouse.click(640, 80);
    }
    result.options_visible = options.map(item => item.text);
    if (!options.length) {
      result.status = 'choice_not_reached';
      return result;
    }
    const before = await snapshot(page);
    result.scene_before = before.scene;
    result.vars_before = before.GameVar;
    const picked = options[Math.min(task.index, options.length - 1)];
    result.picked = picked.text;
    result.picked_index = options.indexOf(picked);
    const voicesBefore = voices.length;
    for (let attempt = 0; attempt < 4; attempt++) {
      await page.mouse.click(picked.x, picked.y);
      await page.waitForTimeout(120);
      if (!(await visibleChoices(page)).length) break;
    }
    await page.waitForTimeout(80);
    const afterClick = await snapshot(page);
    result.target_scene = afterClick.scene;
    result.vars_after_click = afterClick.GameVar;

    const choicePosition = mainlineScenes.indexOf(task.scene);
    const convergence = new Set(choicePosition > -1 ? mainlineScenes.slice(choicePosition + 1) : []);
    const branchScenes = new Set();
    let convergedAt = null;
    let ended = false;
    let clicked = 0;
    for (; clicked < 900; clicked++) {
      const optionsNow = await visibleChoices(page);
      if (optionsNow.length) {
        result.nested_choices = (result.nested_choices || []).concat(optionsNow.map(item => item.text));
        await page.mouse.click(optionsNow[0].x, optionsNow[0].y);
        await page.waitForTimeout(120);
        continue;
      }
      await page.mouse.click(640, 80);
      if (clicked % 10 !== 0) continue;
      const current = await snapshot(page);
      if (current.scene) branchScenes.add(current.scene);
      if (await endSeen(page)) { ended = true; break; }
      if (current.scene && convergence.has(current.scene) && current.scene !== afterClick.scene) {
        convergedAt = current.scene;
        break;
      }
      if (await button(page, 'PRESS THE SCREEN TO START').isVisible().catch(() => false)) { ended = true; break; }
    }
    await page.evaluate(() => clearInterval(window.__probe.timer));
    const probe = await page.evaluate(() => ({ texts: window.__probe.texts, scenes: window.__probe.scenes }));
    result.branch_texts = probe.texts.slice(0, 24).map(item => item.text);
    result.branch_scenes = [...branchScenes];
    result.scene_path = probe.scenes.map(event => event.scene).filter(Boolean).slice(0, 40);
    result.converged_at = convergedAt;
    result.ended = ended;
    result.voices = voices.slice(voicesBefore).map(voice => (voice.file.match(/\d+/) || [''])[0])
      .filter((value, index, array) => value && array.indexOf(value) === index);
    result.clicks = clicked;
    result.status = convergedAt ? 'converged' : ended ? 'end' : 'stalled';
    result.errors = errors;
    return result;
  } catch (error) {
    result.status = 'error';
    result.error = String(error && error.stack || error);
    return result;
  } finally {
    await context.close();
  }
}

async function mainRun() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  const results = [];
  const queue = tasks.slice();
  let done = 0;
  const worker = async index => {
    while (queue.length) {
      const task = queue.shift();
      const result = await runTask(browser, task, index);
      results.push(result);
      done++;
      if (done % 5 === 0) console.log(`进度 ${done}/${tasks.length}：${result.scene} 第 ${result.index + 1} 项 → ${result.status}`);
      fs.writeFileSync(path.resolve(__dirname, `../数据/分支扫描_w${index}.json`),
        JSON.stringify(results.filter(item => item._worker === index || true), null, 2));
      result._worker = index;
    }
  };
  // 每个 worker 只写自己的文件；上面循环结束时统一落盘一次即可。
  const workers = Array.from({ length: WORKERS }, (_, index) => worker(index));
  await Promise.all(workers);
  await browser.close();
  const merged = { origin: [4204, 4205, 4206].slice(0, WORKERS), finished_at: new Date().toISOString(),
                   tasks: tasks.length, results };
  fs.writeFileSync(path.resolve(__dirname, '../数据/分支扫描.json'), `${JSON.stringify(merged, null, 2)}\n`);
  const counts = results.reduce((acc, item) => { acc[item.status] = (acc[item.status] || 0) + 1; return acc; }, {});
  console.log('状态统计', JSON.stringify(counts));
  console.log('报告 数据/分支扫描.json');
}

mainRun().catch(error => { console.error(error); process.exit(1); });
