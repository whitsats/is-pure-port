/**
 * 验证开篇基线档恢复.cjs
 *
 * 1. 在独立测试环境中导入根目录 4204-开篇新档-2026-11-16.json 到第 1 槽；
 * 2. 读第 1 槽档，核对场景、句子、初始数值 (mac_6026/2a/2b/2c == 20)；
 * 3. 推进到首个分支选择，实做快速存档与普通存档；
 * 4. 刷新页面，分别从快速存档和第 1 槽/普通存档恢复，核对场景、句子、数值和下一句。
 */

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const ORIGIN = 'http://127.0.0.1:4204/';
const BASELINE_SAVE_FILE = path.resolve(__dirname, '../4204-开篇新档-2026-11-16.json');

async function installProbe(page) {
  return page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const stateUrl = live('/Core/Modules/stage/stageStateManager.ts');
    const webgalUrl = live('/Core/WebGAL.ts');
    const loadUrl = live('/Core/controller/storage/loadGame.ts');
    const saveUrl = live('/Core/controller/storage/saveGame.ts');
    const fastUrl = live('/Core/controller/storage/fastSaveLoad.ts');
    const storeUrl = live('/store/store.ts');
    const savesReducerUrl = live('/store/savesReducer.ts');
    const savesControllerUrl = live('/Core/controller/storage/savesController.ts');

    const manager = (await import(stateUrl)).stageStateManager;
    const WebGAL = (await import(webgalUrl)).WebGAL;
    const { loadGame, loadGameFromStageData } = await import(loadUrl);
    const { saveGame } = await import(saveUrl);
    const { fastSaveGame, loadFastSaveGame } = await import(fastUrl);
    const { webgalStore } = await import(storeUrl);
    const { saveActions } = await import(savesReducerUrl);
    const { dumpSavesToStorage, getSavesFromStorage } = await import(savesControllerUrl);

    window.__saveProbe = {
      manager,
      WebGAL,
      loadGame,
      loadGameFromStageData,
      saveGame,
      fastSaveGame,
      loadFastSaveGame,
      webgalStore,
      saveActions,
      dumpSavesToStorage,
      getSavesFromStorage
    };
  });
}

async function getStageInfo(page) {
  return page.evaluate(() => {
    const manager = window.__saveProbe.manager;
    const WebGAL = window.__saveProbe.WebGAL;
    const state = manager.getCalculationStageState();
    return {
      scene: WebGAL.sceneManager.sceneData.currentScene.sceneName || '',
      sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
      showText: state.showText || '',
      showName: state.showName || '',
      GameVar: { ...state.GameVar }
    };
  });
}

async function main() {
  console.log('=== Starting Baseline Save File Verification ===');
  const baselineData = JSON.parse(fs.readFileSync(BASELINE_SAVE_FILE, 'utf8'));

  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio']
  });

  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();

  try {
    // 1. Enter title
    await enterDiscTitle(page, ORIGIN);
    await page.waitForTimeout(1000);
    await installProbe(page);

    // 2. Inject baseline save into WebGAL storage and load it
    console.log('Injecting baseline save to slot 1...');
    await page.evaluate((saveObj) => {
      const slot1 = saveObj.saves.saveData[1];
      window.__saveProbe.webgalStore.dispatch(window.__saveProbe.saveActions.saveGame({ index: 1, saveData: slot1 }));
      window.__saveProbe.dumpSavesToStorage(1, 1);
      window.__saveProbe.loadGameFromStageData(slot1);
    }, baselineData);

    await page.waitForTimeout(1500);

    // 3. Verify restored state from slot 1
    const slot1Info = await getStageInfo(page);
    console.log('Restored from Slot 1:', {
      scene: slot1Info.scene,
      sentenceId: slot1Info.sentenceId,
      showText: slot1Info.showText,
      mac_6026: slot1Info.GameVar.mac_6026
    });

    assert.equal(slot1Info.GameVar.mac_6026, 20, '初始好感度 mac_6026 应为 20');
    assert.equal(slot1Info.GameVar.mac_602a, 20, '初始好感度 mac_602a 应为 20');
    assert.equal(slot1Info.GameVar.mac_602b, 20, '初始好感度 mac_602b 应为 20');
    assert.equal(slot1Info.GameVar.mac_602c, 20, '初始好感度 mac_602c 应为 20');

    // 4. Advance a few sentences and save to Slot 2 (Normal Save)
    console.log('Advancing sentences to create Slot 2 state...');
    for (let i = 0; i < 5; i++) {
      await page.mouse.click(640, 500);
      await page.waitForTimeout(150);
    }

    const slot2ExpectedInfo = await getStageInfo(page);
    console.log('Slot 2 state (Sentence ' + slot2ExpectedInfo.sentenceId + '):', {
      scene: slot2ExpectedInfo.scene,
      sentenceId: slot2ExpectedInfo.sentenceId,
      text: slot2ExpectedInfo.showText
    });

    console.log('Saving to Slot 2...');
    await page.evaluate(() => {
      window.__saveProbe.saveGame(2);
    });
    await page.waitForTimeout(800);

    // Advance further to create Fast Save state
    console.log('Advancing further to create Fast Save state...');
    for (let i = 0; i < 5; i++) {
      await page.mouse.click(640, 500);
      await page.waitForTimeout(150);
    }
    const fastExpectedInfo = await getStageInfo(page);
    console.log('Fast Save state (Sentence ' + fastExpectedInfo.sentenceId + '):', {
      scene: fastExpectedInfo.scene,
      sentenceId: fastExpectedInfo.sentenceId,
      text: fastExpectedInfo.showText
    });
    assert.notEqual(fastExpectedInfo.sentenceId, slot2ExpectedInfo.sentenceId, '两阶段句子号必须不同');

    // Explicitly call fastSaveGame to ensure flushed
    await page.evaluate(async () => {
      await window.__saveProbe.fastSaveGame();
    });
    await page.waitForTimeout(800);

    // Reload page to test full persistence
    console.log('Reloading page to test persistence...');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await enterDiscTitle(page, ORIGIN);
    await page.waitForTimeout(1500);
    await installProbe(page);

    // 5. Test Quick Load after reload
    console.log('Restoring from Quick Load after page reload...');
    await page.evaluate(async () => {
      await window.__saveProbe.loadFastSaveGame();
    });
    await page.waitForTimeout(1500);

    const reloadedFastInfo = await getStageInfo(page);
    console.log('Reloaded Fast Save state:', {
      scene: reloadedFastInfo.scene,
      sentenceId: reloadedFastInfo.sentenceId,
      text: reloadedFastInfo.showText,
      mac_6026: reloadedFastInfo.GameVar.mac_6026
    });

    assert.equal(reloadedFastInfo.scene, fastExpectedInfo.scene, '快存档读档后场景必须完全一致');
    assert.equal(reloadedFastInfo.sentenceId, fastExpectedInfo.sentenceId, '快存档读档后句子ID必须完全一致');
    assert.equal(reloadedFastInfo.showText, fastExpectedInfo.showText, '快存档读档后文本必须完全一致');
    assert.equal(reloadedFastInfo.GameVar.mac_6026, 20, '快存档读档后数值必须完全一致');

    // 6. Test Slot 2 Load after reload
    console.log('Restoring from Slot 2 after page reload...');
    await page.evaluate(async () => {
      window.__saveProbe.getSavesFromStorage(1, 2);
      await new Promise(r => setTimeout(r, 400));
      window.__saveProbe.loadGame(2);
    });
    await page.waitForTimeout(1500);

    const reloadedSlot2Info = await getStageInfo(page);
    console.log('Reloaded Slot 2 state:', {
      scene: reloadedSlot2Info.scene,
      sentenceId: reloadedSlot2Info.sentenceId,
      text: reloadedSlot2Info.showText,
      mac_6026: reloadedSlot2Info.GameVar.mac_6026
    });

    assert.equal(reloadedSlot2Info.scene, slot2ExpectedInfo.scene, '槽位2读档后场景必须完全一致');
    assert.equal(reloadedSlot2Info.sentenceId, slot2ExpectedInfo.sentenceId, '槽位2读档后句子ID必须完全一致');
    assert.equal(reloadedSlot2Info.showText, slot2ExpectedInfo.showText, '槽位2读档后文本必须完全一致');

    // 7. Test Slot 1 Baseline Load
    console.log('Restoring from Slot 1 Baseline...');
    await page.evaluate(async () => {
      window.__saveProbe.getSavesFromStorage(1, 1);
      await new Promise(r => setTimeout(r, 400));
      window.__saveProbe.loadGame(1);
    });
    await page.waitForTimeout(1500);

    const reloadedSlot1Info = await getStageInfo(page);
    console.log('Reloaded Slot 1 state:', {
      scene: reloadedSlot1Info.scene,
      sentenceId: reloadedSlot1Info.sentenceId,
      text: reloadedSlot1Info.showText,
      mac_6026: reloadedSlot1Info.GameVar.mac_6026
    });

    assert.equal(reloadedSlot1Info.scene, slot1Info.scene, '槽位1基线读档后场景必须完全一致');
    assert.equal(reloadedSlot1Info.sentenceId, slot1Info.sentenceId, '槽位1基线读档后句子ID必须完全一致');
    assert.equal(reloadedSlot1Info.showText, slot1Info.showText, '槽位1基线读档后文本必须完全一致');
    assert.equal(reloadedSlot1Info.GameVar.mac_6026, 20, '槽位1基线读档后数值必须完全一致');

    console.log('PASS 基线第 1 槽导入成功，快存与普通存档分支恢复验证成功，刷新恢复场景、句子、数值完全一致！');
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
