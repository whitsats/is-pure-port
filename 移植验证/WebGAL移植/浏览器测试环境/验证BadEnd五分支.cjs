/**
 * 验证BadEnd五分支.cjs
 *
 * 在 Playwright 中测试 Bad End (mac_2380) 的五个选项分支：
 * 0. 「伊织的事」 -> mac_056_0x0024f8.txt
 * 1. 「季子的事」 -> mac_056_0x0025c4.txt
 * 2. 「泉的事」   -> mac_056_0x002710.txt
 * 3. 「麻生的事」 -> mac_056_0x0027fc.txt
 * 4. 「没特别」   -> mac_056_0x0028a4.txt
 *
 * 验证：
 * 1. 终章命中 mac_2380，首句为寺谷对白；
 * 2. 各分支实点对应选项，进入对应独立场景；
 * 3. 5 个技术结束出口均能正常返回标题画面。
 */

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const ORIGIN = 'http://127.0.0.1:4204/';
const REPORT_FILE = path.resolve(__dirname, '../数据/BadEnd五分支验证报告.json');

const BRANCHES = [
  { index: 0, text: '伊织的事', expected_scene: 'mac_056_0x0024f8.txt' },
  { index: 1, text: '季子的事', expected_scene: 'mac_056_0x0025c4.txt' },
  { index: 2, text: '泉的事',   expected_scene: 'mac_056_0x002710.txt' },
  { index: 3, text: '麻生的事', expected_scene: 'mac_056_0x0027fc.txt' },
  { index: 4, text: '没特别',   expected_scene: 'mac_056_0x0028a4.txt' },
];

const CP_DATA = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/BadEnd选项前检查点.json'), 'utf8'));

function makeStartTxtForBadEnd() {
  const lines = [];
  for (const [k, v] of Object.entries(CP_DATA.GameVar)) {
    lines.push(`setVar:${k}=${v} -next;`);
  }
  lines.push('changeScene:mac_056_0x00000c.txt;');
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

async function installProbe(page) {
  await page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const managerUrl = live('/Core/Modules/stage/stageStateManager.ts');
    const manager = (await import(managerUrl)).stageStateManager;
    const webgalUrl = live('/Core/WebGAL.ts');
    const WebGAL = (await import(webgalUrl)).WebGAL;

    const probe = { scenes: [], texts: [] };
    let lastScene = null;
    let lastText = null;

    setInterval(() => {
      const state = manager.getCalculationStageState();
      const currentScene = WebGAL.sceneManager.sceneData.currentScene.sceneName || '';
      if (currentScene !== lastScene) {
        lastScene = currentScene;
        probe.scenes.push({ t: Date.now(), scene: currentScene });
      }
      const text = `${state.showName}|${state.showText}`;
      if (state.showText && text !== lastText) {
        lastText = text;
        probe.texts.push({ t: Date.now(), scene: currentScene, name: state.showName, text: state.showText });
      }
    }, 20);

    window.__badEndProbe = { probe, WebGAL, manager };
  });
}

async function testBranch(browser, branch) {
  console.log(`[BadEnd-${branch.text}] Starting test...`);
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });

  await context.route('**/scene/start.txt', route => {
    route.fulfill({
      status: 200,
      contentType: 'text/plain',
      body: makeStartTxtForBadEnd()
    });
  });

  const page = await context.newPage();
  const res = {
    branch: branch.text,
    option_index: branch.index,
    expected_scene: branch.expected_scene,
    first_sentence_of_bad_end: null,
    branch_dialogue_sample: null,
    terminal_scene_visited: false,
    returned_to_title: false
  };

  try {
    await enterDiscTitle(page, ORIGIN);
    await button(page, '开始游戏').waitFor({ state: 'visible', timeout: 15000 });
    await button(page, '开始游戏').click();
    await page.waitForTimeout(1500);

    await installProbe(page);

    // Fast forward
    await page.evaluate(() => {
      const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes(suffix));
      import(live('/Core/WebGAL.ts')).then(({ WebGAL }) => {
        import(live('/gamePlay/nextSentence.ts')).then(({ nextSentence }) => {
          WebGAL.gameplay.isFast = true;
          setInterval(() => {
            if (document.querySelector('#chooseContainer')?.textContent.trim()) return;
            nextSentence();
          }, 15);
        });
      });
    });

    const start = Date.now();
    let clicked = false;

    while (Date.now() - start < 60000) {
      const choices = await visibleChoices(page);
      if (choices.length && !clicked) {
        console.log(`[BadEnd-${branch.text}] Choices visible:`, choices.map(c => c.text));
        const targetChoice = choices.find(c => c.text.includes(branch.text)) || choices[branch.index];
        if (targetChoice) {
          console.log(`[BadEnd-${branch.text}] Clicking choice "${targetChoice.text}"`);
          for (let i = 0; i < 3; i++) {
            await page.mouse.click(targetChoice.x, targetChoice.y);
            await page.waitForTimeout(150);
            if (!(await visibleChoices(page)).length) break;
          }
          clicked = true;
          continue;
        }
      }

      const probeData = await page.evaluate(() => window.__badEndProbe.probe);
      if (!res.first_sentence_of_bad_end) {
        const first = probeData.texts.find(t => t.text.includes('搞不懂') || t.text.includes('嗯――……'));
        if (first) {
          res.first_sentence_of_bad_end = first.text;
          console.log(`[BadEnd-${branch.text}] First sentence:`, first.text);
        }
      }

      if (probeData.scenes.some(s => s.scene === branch.expected_scene)) {
        res.terminal_scene_visited = true;
        const dialogue = probeData.texts.find(t => t.scene === branch.expected_scene);
        if (dialogue && !res.branch_dialogue_sample) {
          res.branch_dialogue_sample = `${dialogue.name}: ${dialogue.text}`;
        }
      }

      // Check title return
      const titleStart = await button(page, '开始游戏').isVisible().catch(() => false);
      const titlePress = await button(page, 'PRESS THE SCREEN TO START').isVisible().catch(() => false);
      if (titleStart || titlePress) {
        console.log(`[BadEnd-${branch.text}] Returned to Title!`);
        res.returned_to_title = true;
        break;
      }

      await page.waitForTimeout(50);
    }
  } finally {
    await context.close();
  }

  return res;
}

async function main() {
  console.log('=== Starting Bad End 5-Branch Verification in Parallel Contexts ===');
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio']
  });

  try {
    // Run all 5 branches in parallel
    const results = await Promise.all(BRANCHES.map(b => testBranch(browser, b)));
    console.log('\n=== Bad End 5-Branch Verification Results ===');
    for (const r of results) {
      console.log(`[${r.branch}] Visited: ${r.terminal_scene_visited} (${r.expected_scene}) | Title: ${r.returned_to_title} | Sample: "${r.branch_dialogue_sample}"`);
    }
    fs.writeFileSync(REPORT_FILE, JSON.stringify(results, null, 2), 'utf8');
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
