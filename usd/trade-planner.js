(function () {
  'use strict';
  const root = document.getElementById('trade-planner');
  if (!root || !window.USDTradePlanner) return;
  const $ = id => document.getElementById('tp-' + id);
  const core = window.USDTradePlanner;
  const KEY = 'usdthb_trade_planner_contracts_v2';
  const settingsFields = ['capital', 'commission', 'fee-mode', 'im', 'mm', 'fm', 'reserve', 'risk', 'series', 'recommend-mode'];
  const planFields = ['entry', 'step', 'count', 'contracts', 'stop', 'exit', 'mark'];
  const generatorFields = ['entry', 'step', 'count', 'contracts'];
  const metricFields = ['equity', 'excess', 'free', 'total', 'average', 'breakeven', 'margin', 'net', 'stop-loss', 'fees', 'cash', 'reserved', 'risk-used', 'mm-price', 'fm-price', 'unrealized'];
  const readNumber = element => element.value.trim() === '' ? NaN : Number(element.value);
  const format = (value, dp = 2) => Number.isFinite(value) ? value.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp }) : '—';
  const TICK_SIZE = 0.01;
  const executableExit = (price, direction) => {
    if (!Number.isFinite(price)) return NaN;
    const scaled = price / TICK_SIZE;
    const ticks = direction === 1 ? Math.ceil(scaled - 1e-9) : Math.floor(scaled + 1e-9);
    return Number((ticks * TICK_SIZE).toFixed(2));
  };
  const defaults = side => ({ entry: '33.30', step: '0.20', count: '4', contracts: '20',
    stop: side === 'long' ? '32.50' : '34.10', exit: side === 'long' ? '33.90' : '32.70', mark: '33.30',
    rows: core.buildRows(33.3, 0.2, 4, 20, side).map(row => ({ price: String(row.price), contracts: String(row.contracts) })) });
  let state = { side: 'long', settings: {}, plans: { long: defaults('long'), short: defaults('short') } };
  let generationError = '';

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY));
      if (!saved || !saved.plans || !saved.settings || typeof saved.settings !== 'object' || Array.isArray(saved.settings) || !['long', 'short'].includes(saved.side)) return;
      const valid = ['long', 'short'].every(side => {
        const plan = saved.plans[side];
        return plan && planFields.every(key => typeof plan[key] === 'string') && Array.isArray(plan.rows) &&
          plan.rows.length > 0 && plan.rows.length <= 12 && plan.rows.every(row => row && typeof row.price === 'string' && typeof row.contracts === 'string');
      });
      if (!valid) return;
      state = saved;
      settingsFields.forEach(id => { if (saved.settings && typeof saved.settings[id] === 'string') $(id).value = saved.settings[id]; });
    } catch (_) { $('save-status').textContent = 'บันทึกแผนไม่ได้ในเบราว์เซอร์นี้ แต่ยังใช้คำนวณได้'; }
  }
  function save() {
    settingsFields.forEach(id => { state.settings[id] = $(id).value; });
    try { localStorage.setItem(KEY, JSON.stringify(state)); }
    catch (_) { $('save-status').textContent = 'บันทึกแผนไม่ได้ในเบราว์เซอร์นี้ แต่ยังใช้คำนวณได้'; }
  }
  function capturePlan() { planFields.forEach(id => { state.plans[state.side][id] = $(id).value; }); }
  function showPlan() {
    planFields.forEach(id => { $(id).value = state.plans[state.side][id]; });
    ['long', 'short'].forEach(side => $('' + side).setAttribute('aria-pressed', String(side === state.side)));
    renderRows();
    generationError = '';
    calculate();
  }
  function renderRows() {
    $('rows').replaceChildren();
    state.plans[state.side].rows.forEach((row, i) => {
      const tr = document.createElement('tr');
      const index = document.createElement('td');
      index.textContent = i + 1;
      tr.append(index);
      ['price', 'contracts'].forEach(key => {
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.type = 'number'; input.min = key === 'price' ? '0.01' : '0'; input.step = key === 'price' ? '0.01' : '1'; input.value = row[key];
        input.setAttribute('aria-label', (key === 'price' ? 'ราคา' : 'จำนวนสัญญา') + 'ไม้ ' + (i + 1));
        input.addEventListener('input', () => {
          row[key] = input.value;
          generationError = '';
          calculate(); save();
        });
        td.append(input); tr.append(td);
      });
      ['spent', 'count', 'average', 'margin', 'equity', 'excess', 'free', 'status'].forEach(key => {
        const td = document.createElement('td'); td.dataset.result = key; td.textContent = '—'; tr.append(td);
      });
      $('rows').append(tr);
    });
  }
  function setMetric(id, value, dp = 2, colored = false) {
    const node = $(id);
    node.textContent = format(value, dp);
    node.className = colored && Number.isFinite(value) ? (value >= 0 ? 'good' : 'bad') : '';
  }
  function renderSurvivalPlan(settings, result, plan) {
    const ids = ['plan-capital', 'plan-reserve', 'plan-mm-price', 'plan-fm-price', 'plan-average', 'plan-breakeven', 'plan-exit', 'plan-exit-pnl'];
    const body = $('action-plan-rows');
    body.replaceChildren();
    if (!result || result.errors.length || !result.count) {
      ids.forEach(id => { $(id).textContent = '—'; });
      $('plan-action').textContent = 'กรอกแผนเพื่อประเมิน';
      return;
    }
    $('plan-capital').textContent = format(settings.capital) + ' บาท';
    $('plan-reserve').textContent = format(result.reserve) + ' บาท';
    $('plan-mm-price').textContent = format(result.mmPrice, 4);
    $('plan-fm-price').textContent = format(result.fmPrice, 4);
    $('plan-average').textContent = format(result.average, 4);
    const direction = state.side === 'long' ? 1 : -1;
    $('plan-breakeven').textContent = format(executableExit(result.breakEven, direction), 4);
    $('plan-exit').textContent = format(plan && Number.isFinite(plan.exit) ? plan.exit : NaN, 4);
    $('plan-exit-pnl').textContent = format(result.net, 2) + ' บาท';
    const action = result.marginStatus === 'FM' ? 'แดง · หยุดเปิดและจัดการสถานะ'
      : result.marginStatus === 'MM' ? 'ส้ม · ห้ามเพิ่ม เตรียมเติมเงิน/ลดสถานะ'
        : result.reserveBreached || result.free < 0 ? 'เหลือง · เงินกันชนไม่พอ'
          : 'เขียว · ยังอยู่เหนือ MM';
    $('plan-action').textContent = action;
    result.rows.filter(row => row.lots > 0).forEach(row => {
      const tr = document.createElement('tr');
      const breakeven = executableExit(row.average + direction * result.feeRT / 1000, direction);
      const rowAction = row.canOpen && row.free >= 0 ? 'ถัวได้ตามแผน' : 'หยุดถัว · เติมเงิน/ลดสถานะ';
      [format(row.price, 4), format(row.count, 0), format(row.average, 4), format(breakeven, 4), rowAction].forEach((value, i) => {
        const td = document.createElement('td'); td.textContent = value;
        if (i === 4) td.className = rowAction.startsWith('หยุด') ? 'tp-action-danger' : 'tp-action-ok';
        tr.append(td);
      });
      body.append(tr);
    });
  }
  function renderLegacyRescuePlan(settings, plan, result, decision) {
    let rescue = document.getElementById('tp-rescue-summary');
    if (!rescue) {
      rescue = document.createElement('div');
      rescue.id = 'tp-rescue-summary';
      rescue.className = 'tp-rescue-summary';
      decision.after(rescue);
    }
    rescue.replaceChildren();
    const mark = Number(plan.mark);
    if (!result || result.errors.length || !result.count || !Number.isFinite(mark)) {
      rescue.textContent = 'แผนแก้เกม: ต้องมีสถานะปัจจุบันและราคาประเมินพอร์ต';
      return [];
    }
    const direction = state.side === 'long' ? 1 : -1;
    const feeOpen = result.feeRT / 2;
    const reserve = result.reserve;
    // Smaller first rescue, larger only at deeper levels. This keeps the
    // first decision reversible and reserves margin for the next two stages.
    const pyramidRatio = '1:2:3';
    const mmSafetyBuffer = Math.max(0.20, step);
    let count = result.count;
    let cost = result.average * result.count;
    let equity = result.equity;
    let free = Math.max(0, result.free);
    const step = readNumber($('step'));
    const rows = [];
    for (let i = 0; i < 3; i++) {
      const price = Math.round((mark - direction * step * (i + 1)) * 100) / 100;
      if (!Number.isFinite(price) || price <= 0 || free <= 0) break;
      const lots = Math.max(0, Math.floor((free * portions[i]) / (settings.im + feeOpen)));
      cost += price * lots;
      count += lots;
      equity = settings.capital + direction * (price * count - cost) * 1000 - count * feeOpen;
      free = equity - count * (settings.im + feeOpen) - reserve;
      const average = count ? cost / count : null;
      const breakEven = average + direction * result.feeRT / 1000;
      const mmPrice = average + direction * (count * settings.mm - settings.capital + count * feeOpen) / (1000 * count);
      const fmPrice = average + direction * (count * settings.fm - settings.capital + count * feeOpen) / (1000 * count);
      rows.push({ price, lots, count, average, breakEven, mmPrice, fmPrice, free: Math.max(0, free) });
    }
    const title = document.createElement('strong');
    title.textContent = 'ACTION PLAN · ทำอะไรเมื่อราคาไปถึงแต่ละระดับ';
    rescue.append(title);
    const note = document.createElement('span');
    note.textContent = ' · แผนจำลองจากเงินเหลือ แบ่งเป็น 3 ไม้ และห้ามเพิ่มเมื่อแตะ MM/FM';
    rescue.append(note);
    const current = document.createElement('div');
    current.className = 'tp-action-now';
    current.textContent = 'ตอนนี้: ถือสถานะเดิม · รอราคาแตะ Trigger ถัดไป · ห้ามถัวระหว่างระดับ';
    rescue.append(current);
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>Trigger</th><th>Action</th><th>เพิ่ม</th><th>หลังทำรายการ</th><th>แผนออก</th><th>จุดหยุดถัว</th></tr></thead><tbody></tbody>';
    const body = table.querySelector('tbody');
    rows.forEach(row => {
      const tr = document.createElement('tr');
      const action = row.lots > 0 ? 'เปิดเพิ่มทันที' : 'ห้ามเพิ่ม';
      const after = format(row.count, 0) + ' สัญญา · เฉลี่ย ' + format(row.average, 4);
      const executableBreakEven = executableExit(row.breakEven, direction);
      const exit2 = executableExit(row.breakEven + direction * 0.03, direction);
      const exit = 'ปิด 50% ≥ ' + format(executableBreakEven, 4) + ' · ที่เหลือ ≥ ' + format(exit2, 4);
      const stop = 'MM ' + format(row.mmPrice, 4) + ' / FM ' + format(row.fmPrice, 4);
      [format(row.price, 4), action, format(row.lots, 0), after, exit, stop].forEach(value => {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      });
      tr.className = row.lots > 0 ? 'tp-action-row' : 'tp-action-stop-row';
      body.append(tr);
    });
    const next = rows.find(row => direction === 1 ? mark <= row.price : mark >= row.price);
    if (next) {
      current.textContent = 'ตอนนี้: ราคาแตะ/ผ่าน Trigger ' + format(next.price, 4) + ' แล้ว · ' + (next.lots > 0 ? 'ทำ Action: เปิดเพิ่ม ' + format(next.lots, 0) + ' สัญญา' : 'ห้ามเพิ่ม · รอเติมเงินหรือลดสถานะ');
    } else {
      current.textContent = 'ตอนนี้: ยังไม่ถึง Trigger ถัดไป · ถือสถานะเดิมและรอราคาเท่านั้น';
    }
    rescue.append(table);
    const foot = document.createElement('p');
    foot.textContent = rows.length ? (reserve <= 0 ? 'กติกา: ใช้ได้เฉพาะเมื่อเงินเหลือพอ · แตะ MM/FM = หยุดถัวและลดสถานะ · เด้งกลับถึงราคาออกให้ทยอยปิด ไม่รอให้กลับไปจุดเดิมทั้งหมด' : 'กติกา: แตะ Trigger จึงทำตาม Action · แตะ MM/FM ให้หยุดถัวทันที · เด้งถึงราคาออกให้ทยอยปิดสถานะ') : 'เงินเหลือไม่พอสำหรับการถัวเพิ่ม';
    rescue.append(foot);
    return rows;
  }
  function renderThreeStagePlanLegacy(settings, plan, result, decision) {
    let rescue = document.getElementById('tp-rescue-summary');
    if (!rescue) {
      rescue = document.createElement('div');
      rescue.id = 'tp-rescue-summary';
      rescue.className = 'tp-rescue-summary';
      decision.after(rescue);
    }
    rescue.replaceChildren();
    const direction = state.side === 'long' ? 1 : -1;
    const rows = Array.isArray(plan.rows) ? plan.rows : [];
    const validRows = rows.filter(row => Number(row.contracts) > 0 && Number.isFinite(Number(row.price)));
    const count0 = validRows.reduce((sum, row) => sum + Number(row.contracts), 0);
    const cost0 = validRows.reduce((sum, row) => sum + Number(row.price) * Number(row.contracts), 0);
    const floor = validRows.length ? Number(validRows[validRows.length - 1].price) : NaN;
    if (!result || result.errors.length || !count0 || !Number.isFinite(floor)) {
      rescue.textContent = 'แผนหลังหลุดไม้สุดท้าย: ต้องมีแผนเดิมและราคาประเมินพอร์ตให้ครบ';
      return [];
    }
    const feeOpen = result.feeRT / 2;
    const feePerContract = result.feeRT / 1000;
    const reserve = result.reserve;
    const step = Math.max(0.01, readNumber($('step')));
    const recoveryBuffer = 0.01;
    const targetExit = floor + direction * recoveryBuffer;
    const maxFutureRows = 3;
    let count = count0;
    let cost = cost0;
    const moneyAt = price => settings.capital + direction * (price * count - cost) * 1000 - count * feeOpen;
    const marginPrice = level => {
      const average = cost / count;
      return average + direction * (count * level - settings.capital + count * feeOpen) / (1000 * count);
    };
    const requiredToExit = price => {
      const threshold = targetExit - direction * feePerContract;
      if (direction === 1) {
        if (threshold <= price) return Infinity;
        return Math.max(0, Math.ceil((cost - threshold * count) / (threshold - price)));
      }
      if (threshold >= price) return Infinity;
      return Math.max(0, Math.ceil((threshold * count - cost) / (price - threshold)));
    };
    const planRows = [];
    for (let i = 1; i <= maxFutureRows; i++) {
      const price = Math.round((floor - direction * step * i) * 100) / 100;
      if (!Number.isFinite(price) || price <= 0) break;
      const beforeCount = count;
      const beforeCost = cost;
      const beforeAverage = beforeCost / beforeCount;
      const beforeMM = marginPrice(settings.mm);
      const beforeFM = marginPrice(settings.fm);
      const beforeEquity = moneyAt(price);
      const beforeFree = beforeEquity - beforeCount * (settings.im + feeOpen) - reserve;
      const maxLots = Math.max(0, Math.floor(Math.max(0, beforeFree) / (settings.im + feeOpen)));
      const needed = requiredToExit(price);
      const allowed = price > beforeMM && price > beforeFM && beforeFree > 0;
      const lots = allowed ? Math.min(needed, maxLots) : 0;
      count += lots;
      cost += price * lots;
      const average = cost / count;
      const breakEven = average + direction * feePerContract;
      const executableBreakEven = executableExit(breakEven, direction);
      const afterEquity = settings.capital + direction * (price * count - cost) * 1000 - count * feeOpen;
      const afterFree = afterEquity - count * (settings.im + feeOpen) - reserve;
      const afterMM = marginPrice(settings.mm);
      const afterFM = marginPrice(settings.fm);
      const achieved = direction === 1 ? breakEven <= targetExit + 1e-9 : breakEven >= targetExit - 1e-9;
      planRows.push({ price, lots, count, average, breakEven, executableBreakEven, targetExit, beforeMM, beforeFM, afterMM, afterFM, afterFree: Math.max(0, afterFree), maxLots, needed, achieved, allowed, beforeAverage });
      if (!allowed || !achieved) break;
    }
    const title = document.createElement('strong');
    title.textContent = 'ACTION PLAN หลังหลุดแผนเดิม';
    rescue.append(title);
    const note = document.createElement('span');
    note.textContent = ' · ไม้สุดท้ายของแผนเดิมคือ ' + format(floor, 4) + ' · ราคาออกปัดตาม tick 0.01 (Long ปัดขึ้น / Short ปัดลง) · ไม่ใช่ถัวทุกครั้งที่ราคาแดง';
    rescue.append(note);
    const current = document.createElement('div');
    current.className = 'tp-action-now';
    current.textContent = 'ก่อนหลุด ' + format(floor, 4) + ': ห้ามใช้เงินเพิ่ม · ถ้าหลุดให้รอ Trigger ถัดไป แล้วทำตามแผนด้านล่างเท่านั้น';
    rescue.append(current);
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>ถ้าราคาหลุดถึง</th><th>Action</th><th>เพิ่ม</th><th>เป้าหมายหลุดดอย</th><th>ทนได้ถึง</th><th>เงินเหลือ</th></tr></thead><tbody></tbody>';
    const body = table.querySelector('tbody');
    planRows.forEach(row => {
      const tr = document.createElement('tr');
      const action = row.lots > 0 && row.achieved ? 'ถัวตามแผน แล้วรอเด้ง' : row.lots > 0 ? 'ถัวได้ แต่ยังไม่หลุดดอย' : 'ห้ามถัว · ลดสถานะ/เติมเงิน';
      const exit = row.achieved ? 'ออกทั้งหมด ≥ ' + format(executableExit(row.targetExit, direction), 4) : 'ยังไม่ถึงเป้าหมาย';
      const survive = 'MM ' + format(row.afterMM, 4) + ' · FM ' + format(row.afterFM, 4);
      [format(row.price, 4), action, format(row.lots, 0), exit, survive, format(row.afterFree, 0)].forEach(value => {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      });
      tr.className = row.achieved ? 'tp-action-row' : 'tp-action-stop-row';
      body.append(tr);
    });
    rescue.append(table);
    const foot = document.createElement('p');
    const first = planRows[0];
    foot.textContent = first && first.achieved
      ? 'กติกา: เมื่อแตะ ' + format(first.price, 4) + ' จึงเพิ่ม ' + format(first.lots, 0) + ' สัญญา · ถ้าดีดถึง ' + format(first.targetExit, 4) + ' ให้ปิดทั้งหมดเพื่อจบเกม · MM = หยุดถัว · FM = เขตเสี่ยง Force Sell'
      : 'กติกา: แผนนี้ไม่สามารถทำให้หลุดดอยตามเป้าหมายได้ด้วยเงินที่เหลือ · ห้ามเร่งถัว · ต้องลดสถานะหรือเติมเงินก่อน';
    rescue.append(foot);
    return planRows;
  }
  function renderRescuePlan(settings, plan, result, decision) {
    let rescue = document.getElementById('tp-rescue-summary');
    if (!rescue) {
      rescue = document.createElement('div');
      rescue.id = 'tp-rescue-summary';
      rescue.className = 'tp-rescue-summary';
      decision.after(rescue);
    }
    rescue.replaceChildren();
    const direction = state.side === 'long' ? 1 : -1;
    const entered = (Array.isArray(plan.rows) ? plan.rows : []).filter(row => Number(row.contracts) > 0 && Number.isFinite(Number(row.price)));
    const baseCount = entered.reduce((sum, row) => sum + Number(row.contracts), 0);
    const baseCost = entered.reduce((sum, row) => sum + Number(row.price) * Number(row.contracts), 0);
    const floor = entered.length ? Number(entered[entered.length - 1].price) : NaN;
    if (!result || result.errors.length || !baseCount || !Number.isFinite(floor)) {
      rescue.textContent = 'แผน 3 ไม้หลังหลุดแผนเดิม: ต้องมีแผนเดิมและราคาประเมินพอร์ตให้ครบ';
      return [];
    }
    const feeOpen = result.feeRT / 2;
    const feePerContract = result.feeRT / 1000;
    const reserve = result.reserve;
    const step = Math.max(0.01, readNumber($('step')));
    const prices = [1, 2, 3].map(i => Math.round((floor - direction * step * i) * 100) / 100);
    const pyramidRatio = '1:2:3';
    const mmSafetyBuffer = Math.max(0.20, step);
    const targetExit = executableExit(floor + direction * 0.01, direction);
    const quantitiesForScale = unit => [
      Math.floor(unit * 1),
      Math.floor(unit * 2),
      Math.floor(unit * 3)
    ];
    const evaluate = quantities => {
      const count = baseCount + quantities.reduce((sum, lots) => sum + lots, 0);
      const cost = baseCost + quantities.reduce((sum, lots, i) => sum + prices[i] * lots, 0);
      const average = cost / count;
      const breakEven = average + direction * feePerContract;
      return { count, cost, average, breakEven, meets: direction === 1 ? breakEven <= targetExit + 1e-9 : breakEven >= targetExit - 1e-9 };
    };
    let scale = 0;
    let high = 1;
    while (!evaluate(quantitiesForScale(high)).meets && high < 1000000) high *= 2;
    if (evaluate(quantitiesForScale(high)).meets) {
      let low = 0;
      while (low + 1 < high) {
        const mid = Math.floor((low + high) / 2);
        if (evaluate(quantitiesForScale(mid)).meets) high = mid; else low = mid;
      }
      scale = Math.max(3, high);
    }
    const marginThreshold = (level, count, cost) => {
      const average = cost / count;
      return average + direction * (count * level - settings.capital + count * feeOpen) / (1000 * count);
    };
    const canExecutePyramid = unit => {
      const quantities = quantitiesForScale(unit);
      let trialCount = baseCount;
      let trialCost = baseCost;
      for (let i = 0; i < prices.length; i++) {
        const beforeMM = marginThreshold(settings.mm, trialCount, trialCost);
        const beforeFM = marginThreshold(settings.fm, trialCount, trialCost);
        const beforeEquity = settings.capital + direction * (prices[i] * trialCount - trialCost) * 1000 - trialCount * feeOpen;
        const beforeFree = beforeEquity - trialCount * (settings.im + feeOpen) - reserve;
        const safe = direction * (prices[i] - beforeMM) > mmSafetyBuffer && direction * (prices[i] - beforeFM) > 0;
        const maxLots = Math.max(0, Math.floor(Math.max(0, beforeFree) / (settings.im + feeOpen)));
        if (!safe || maxLots < quantities[i]) return false;
        trialCount += quantities[i];
        trialCost += prices[i] * quantities[i];
      }
      return true;
    };
    let capacity = 0;
    let capacityHigh = 1;
    while (canExecutePyramid(capacityHigh) && capacityHigh < 1000000) capacityHigh *= 2;
    if (canExecutePyramid(capacityHigh)) capacity = capacityHigh;
    else if (capacityHigh > 1) {
      let low = 0;
      let highCapacity = capacityHigh;
      while (low + 1 < highCapacity) {
        const mid = Math.floor((low + highCapacity) / 2);
        if (canExecutePyramid(mid)) { capacity = mid; low = mid; } else highCapacity = mid;
      }
    }
    if (scale > capacity) scale = capacity;
    const requested = quantitiesForScale(scale);
    let count = baseCount;
    let cost = baseCost;
    let blocked = scale === 0;
    const marginPrice = level => {
      const average = cost / count;
      return average + direction * (count * level - settings.capital + count * feeOpen) / (1000 * count);
    };
    const rows = prices.map((price, i) => {
      const beforeMM = marginPrice(settings.mm);
      const beforeFM = marginPrice(settings.fm);
      const beforeEquity = settings.capital + direction * (price * count - cost) * 1000 - count * feeOpen;
      const beforeFree = beforeEquity - count * (settings.im + feeOpen) - reserve;
      const maxLots = Math.max(0, Math.floor(Math.max(0, beforeFree) / (settings.im + feeOpen)));
      const marginSafe = direction * (price - beforeMM) > mmSafetyBuffer && direction * (price - beforeFM) > 0;
      const allowed = !blocked && marginSafe && beforeFree > 0;
      const lots = allowed && maxLots >= requested[i] ? requested[i] : 0;
      if (lots < requested[i]) blocked = true;
      count += lots;
      cost += price * lots;
      const average = cost / count;
      const breakEven = average + direction * feePerContract;
      const executableBreakEven = executableExit(breakEven, direction);
      const afterEquity = settings.capital + direction * (price * count - cost) * 1000 - count * feeOpen;
      const afterFree = afterEquity - count * (settings.im + feeOpen) - reserve;
      const afterMM = marginPrice(settings.mm);
      const afterFM = marginPrice(settings.fm);
      const meets = direction === 1 ? breakEven <= targetExit + 1e-9 : breakEven >= targetExit - 1e-9;
      return { stage: i + 1, price, lots, requested: requested[i], count, cost, average, breakEven, executableBreakEven, targetExit, beforeMM, beforeFM, afterMM, afterFM, afterFree: Math.max(0, afterFree), maxLots, meets, allowed, marginSafe };
    });
    const title = document.createElement('strong');
    title.textContent = 'ACTION PLAN หลังหลุดแผนเดิม · PROFESSIONAL RISK PLAN · 3 ไม้';
    rescue.append(title);
    const note = document.createElement('span');
    note.textContent = ' · ไม้สุดท้ายของแผนเดิมคือ ' + format(floor, 4) + ' · พีระมิดสัญญาอัตรา ' + pyramidRatio + ' · ราคาออกปัดตาม tick 0.01';
    rescue.append(note);
    const current = document.createElement('div');
    current.className = 'tp-action-now';
    current.textContent = 'ก่อนหลุด ' + format(floor, 4) + ': ไม่เพิ่มสถานะ · หลังหลุดให้ทำทีละไม้ตามลำดับ · ถ้าเด้งถึงราคาออกให้ปิดและยกเลิกไม้ถัดไป';
    rescue.append(current);
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>ไม้</th><th>ถัวที่</th><th>Action</th><th>เพิ่ม</th><th>เฉลี่ยหลังไม้</th><th>ออกขั้นต่ำ</th><th>MM / FM</th><th>เงินเหลือ</th></tr></thead><tbody></tbody>';
    const body = table.querySelector('tbody');
    rows.forEach(row => {
      const tr = document.createElement('tr');
      const action = row.lots === 0 ? 'ห้ามถัว · ลดสถานะ/เติมเงิน' : 'เปิดไม้ ' + row.stage + ' · ตั้งปิดทั้งหมด';
      const exit = row.lots > 0 ? '≥ ' + format(row.executableBreakEven, 4) : '—';
      const margin = format(row.afterMM, 4) + ' / ' + format(row.afterFM, 4);
      [String(row.stage), format(row.price, 4), action, format(row.lots, 0), format(row.average, 4), exit, margin, format(row.afterFree, 0)].forEach(value => {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      });
      tr.className = row.lots > 0 ? 'tp-action-row' : 'tp-action-stop-row';
      body.append(tr);
    });
    rescue.append(table);
    const foot = document.createElement('p');
    const final = rows[rows.length - 1];
    foot.textContent = final && final.meets && rows.every(row => row.lots > 0)
      ? 'กติกา: ทุกไม้ต้องตั้งปิดทั้งหมดที่ราคาออกขั้นต่ำของไม้นั้น · ถ้าไม่เด้งและลงถึง Trigger ถัดไปจึงทำไม้ถัดไป · ห้ามเพิ่มเมื่อราคาเข้าใกล้ MM ภายใน ' + format(mmSafetyBuffer, 2) + ' บาท · FM = เขตเสี่ยง Force Sell'
      : 'กติกา: เงินหรือมาร์จินไม่พอให้ทำครบ 3 ไม้ · ห้ามเร่งถัว · เมื่อเข้าใกล้ MM ภายใน ' + format(mmSafetyBuffer, 2) + ' บาทให้หยุดถัว · FM = เขตเสี่ยง Force Sell';
    rescue.append(foot);
    return rows;
  }
  function renderRecommendation(settings, plan, currentResult) {
    $('recommend-title').textContent = 'แผนแก้เกมในอนาคต';
    const body = $('recommend-rows');
    const panel = document.querySelector('.tp-recommendation');
    let decision = document.getElementById('tp-decision-summary');
    if (!decision && panel) {
      decision = document.createElement('div');
      decision.id = 'tp-decision-summary';
      decision.className = 'tp-decision-summary';
      const tableScroll = panel.querySelector('.tp-table-scroll');
      if (tableScroll) tableScroll.before(decision);
    }
    const header = document.querySelector('.tp-recommend-table thead tr');
    if (header) {
      header.replaceChildren();
      ['ราคา', 'เปิดเพิ่ม', 'สัญญาสะสม', 'ราคาเฉลี่ยหลังถัว', 'ราคาเสมอตัว', 'เงินเหลือหลังไม้*', 'เงินเติมตามจำนวนฐาน'].forEach(label => {
        const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; header.append(th);
      });
    }
    body.replaceChildren();
    const total = $('recommend-total');
    const status = $('recommend-status');
    let result;
    try {
      result = core.recommend(settings, { side: state.side, entry: readNumber($('entry')), step: readNumber($('step')), count: readNumber($('count')), targetContracts: readNumber($('contracts')), stop: Number(plan.stop), mode: $('recommend-mode').value });
    } catch (_) { result = { errors: ['กรอกข้อมูลให้ครบเพื่อสร้างคำแนะนำ'], rows: [] }; }
    if (result.errors.length) {
      total.textContent = '—'; status.textContent = result.errors[0]; status.className = 'tp-status tp-warning'; return;
    }
    const integer = value => Number.isFinite(value) ? Math.round(value).toLocaleString('en-US') : '—';
    result.rows.forEach(row => {
      const tr = document.createElement('tr');
      const direction = state.side === 'long' ? 1 : -1;
      [format(row.price, 4), integer(row.recommended), integer(row.count), format(row.average, 4), format(executableExit(row.breakEven, direction), 4), integer(row.free), Number.isFinite(row.topUp) ? integer(row.topUp) : 'คำนวณไม่ได้'].forEach((value, i) => {
        const td = document.createElement('td'); td.textContent = value;
        if (i === 5 && row.free < 0) td.className = 'tp-topup';
        if (i === 6 && row.topUp > 0) td.className = 'tp-topup';
        tr.append(td);
      });
      const action = row.recommended === 0
        ? 'ห้ามเพิ่ม · รอเติมเงิน/ลดสถานะ'
        : row.topUp > 0
          ? 'เปิดตามเงินที่มี · เติมเงินถ้าจะเปิดตามเป้า'
          : 'เปิดได้ตาม IM · เฝ้าระวัง MM/FM';
      const actionCell = document.createElement('td');
      actionCell.textContent = action;
      actionCell.className = row.recommended === 0 ? 'tp-action-danger' : row.topUp > 0 ? 'tp-action-warn' : 'tp-action-ok';
      // Keep row-level action out of the table; the status line below summarizes exceptions.
      body.append(tr);
    });
    const last = result.rows[result.rows.length - 1];
    total.textContent = last ? integer(last.count) + ' สัญญา' : '—';
    const viable = result.rows.filter(row => row.recommended > 0);
    const final = viable[viable.length - 1] || last;
    if (decision && final) {
      const topUp = final.topUp > 0 ? ' · ถ้าจะเปิดตามเป้าต้องเติม ' + integer(final.topUp) + ' บาท' : '';
      const rescueRows = renderRescuePlan(settings, plan, currentResult, decision);
      const next = rescueRows[0];
      if (next) {
        decision.textContent = 'แผนอนาคต: ถ้าราคาถึง ' + format(next.price, 4) + ' → ถัวเพิ่ม ' + integer(next.lots) + ' สัญญา → เฉลี่ย ' + format(next.average, 4) + ' → ออกเมื่อ ≥ ' + format(executableExit(next.breakEven, state.side === 'long' ? 1 : -1), 4) + (settings.reservePct <= 0 ? ' · กันเงิน 0 บาท = ไม่มีไม้สำรอง' : '');
      } else {
        decision.textContent = 'แผนอนาคต: เงินเหลือไม่พอถัวเพิ่ม · ห้ามเพิ่มสถานะ';
      }
    }
    const topUpRows = result.rows.filter(row => row.topUp > 0).length;
    const cappedRows = result.rows.filter(row => row.recommended < row.targetContracts).length;
    const messages = [];
    if (topUpRows) messages.push('ถ้าต้องการเปิดตามจำนวนฐาน จะต้องเติมเงินตามราคาที่แสดง');
    if (cappedRows) messages.push('บางระดับแนะนำต่ำกว่าจำนวนฐาน เพราะติดข้อจำกัดทุนสำรองหรือกรอบขาดทุน');
    if (!messages.length) messages.push('ทุนรองรับจำนวนฐานที่กรอกในทุกระดับตามสมมติฐานนี้');
    status.textContent = messages.join(' · '); status.className = 'tp-status' + (topUpRows || cappedRows ? ' tp-warning' : '');
  }
  function showErrors(errors) {
    const box = $('validation');
    box.hidden = errors.length === 0;
    box.replaceChildren();
    if (!errors.length) return;
    const list = document.createElement('ul'); list.className = 'tp-error-list';
    errors.forEach(error => { const li = document.createElement('li'); li.textContent = error; list.append(li); });
    box.append(list);
    metricFields.forEach(id => setMetric(id, NaN));
    $('rows').querySelectorAll('[data-result]').forEach(cell => { cell.textContent = '—'; cell.className = ''; });
    $('status').textContent = 'กรอกข้อมูลให้ครบและถูกต้องเพื่อคำนวณ';
    $('status').className = 'tp-status tp-warning';
  }
  function calculate() {
    capturePlan();
    const plan = state.plans[state.side];
    const settings = {
      capital: readNumber($('capital')) * 1000000, commission: readNumber($('commission')), commissionMode: $('fee-mode').value,
      im: readNumber($('im')), mm: readNumber($('mm')), fm: readNumber($('fm')),
      reservePct: readNumber($('reserve')), riskPct: readNumber($('risk')), mode: $('recommend-mode').value
    };
    const numeric = value => value.trim() === '' ? NaN : Number(value);
    const result = core.calculate(settings, { side: state.side, stop: numeric(plan.stop), exit: numeric(plan.exit), mark: numeric(plan.mark),
      rows: plan.rows.map(row => ({ price: numeric(row.price), contracts: numeric(row.contracts) })) });
    const title = state.side === 'long' ? 'Long · ซื้อเพิ่ม' : 'Short · ขายเพิ่ม';
    $('caption').textContent = title + ($('series').value.trim() ? ' · ' + $('series').value.trim().toUpperCase() : '') + ' — จำลองตามลำดับไม้';
    const rt = settings.commission * (settings.commissionMode === 'side' ? 2 : 1);
    $('fee-note').textContent = 'ทุน ' + format(settings.capital) + ' บาท · คอมเปิด ' + format(rt / 2) + ' + ปิด ' + format(rt / 2) + ' = ไป–กลับ ' + format(rt) + ' บาท/สัญญา';
    let errors = result.errors.slice();
    if (generationError) errors.unshift(generationError);
    try { core.buildRows(readNumber($('entry')), readNumber($('step')), readNumber($('count')), readNumber($('contracts')), state.side); }
    catch (error) { if (!errors.includes(error.message)) errors.unshift(error.message); }
    // Invalid generator drafts must not leave old successful results visible.
    if (generatorFields.some(id => $('' + id).value === '' || !$(id).validity.valid)) errors.unshift('กรอกราคาแรก ระยะห่าง จำนวนไม้ และสัญญาต่อไม้ให้ถูกต้อง');
    renderRecommendation(settings, plan, result);
    renderSurvivalPlan(settings, result, plan);
    showErrors(errors);
    if (errors.length) return;
    Array.from($('rows').children).forEach((tr, i) => {
      const row = result.rows[i];
      tr.querySelectorAll('[data-result]').forEach(td => {
        const key = td.dataset.result;
        td.textContent = key === 'status' ? row.status : format(row[key], key === 'average' ? 4 : key === 'count' ? 0 : 2);
        td.className = ['free', 'excess'].includes(key) && row[key] < 0 ? 'bad' : '';
      });
    });
    setMetric('total', result.count, 0);
    setMetric('reserved', result.reserve);
    if (!result.count) {
      metricFields.filter(id => !['total', 'reserved'].includes(id)).forEach(id => setMetric(id, NaN));
      setMetric('equity', settings.capital); setMetric('excess', settings.capital);
      setMetric('free', settings.capital - result.reserve); setMetric('margin', 0); setMetric('fees', 0);
      setMetric('net', 0); setMetric('stop-loss', 0); setMetric('unrealized', 0); setMetric('cash', settings.capital);
      $('status').textContent = 'ยังไม่มีสถานะ: กรอกจำนวนสัญญาของไม้ที่ต้องการจำลอง';
      $('status').className = 'tp-status tp-warning';
      return;
    }
    setMetric('equity', result.equity);
    setMetric('excess', result.excess, 2, true);
    setMetric('free', result.free, 2, true);
    setMetric('average', result.average, 4);
    setMetric('breakeven', result.breakEven, 4);
    setMetric('margin', result.margin);
    setMetric('net', result.net, 2, true);
    setMetric('stop-loss', result.stopNet, 2, true);
    setMetric('fees', result.fees);
    setMetric('cash', result.cashAfterClose);
    setMetric('unrealized', result.unrealized, 2, true);
    $('risk-used').textContent = settings.mode === 'max-capital' ? 'ไม่จำกัด Stop loss / ใช้ IM' : format(result.riskPct) + '% / งบ ' + format(settings.riskPct) + '%';
    ['mm', 'fm'].forEach(level => {
      const price = result[level + 'Price'];
      $(level + '-price').textContent = price > 0 ? format(price, 4) : 'ไม่ถึงในช่วงราคาบวก';
    });
    const messages = [];
    if (!result.fundingFeasible) messages.push('ทุนไม่พอเปิดตามลำดับแผน: ผลลัพธ์เป็นกรณีสมมติที่เปิดครบตามจำนวนที่กรอก');
    if (result.overRisk) messages.push('ขาดทุนที่จุดหยุดเกินกรอบที่กำหนด');
    if (result.reserveBreached) messages.push('เงินสำรองไม่พอในบางไม้');
    if (result.marginStatus === 'FM') messages.push('ราคาประเมิน: Equity แตะ/ต่ำกว่า FM');
    else if (result.marginStatus === 'MM') messages.push('ราคาประเมิน: Equity แตะ/ต่ำกว่า MM');
    else if (result.marginStatus === 'IM') messages.push('ราคาประเมิน: Excess Equity ติดลบ (ต่ำกว่า IM)');
    else if (result.free < 0) messages.push('ราคาประเมิน: เงินเหลือต่ำกว่าเงินสำรองที่ตั้งไว้');
    const direction = state.side === 'long' ? 1 : -1;
    if (direction * (numeric(plan.mark) - numeric(plan.stop)) <= 0) messages.push('ราคาประเมินผ่านจุดหยุดแล้ว: แสดงผลกรณียังไม่ปิดสถานะ');
    if (direction * (numeric(plan.exit) - numeric(plan.stop)) < 0) messages.push('ราคาปิดผ่านจุดหยุด: ผลขาดทุนอาจเกินงบที่วางไว้');
    $('status').textContent = messages.length ? messages.join(' · ') : 'แผนอยู่ในงบที่กำหนด · Equity ใช้ราคาประเมินพอร์ต · กำไรสุทธิใช้ราคาจำลองปิดหลังเปิดครบ';
    $('status').className = 'tp-status' + (messages.length ? ' tp-warning' : '');
  }
  function generate() {
    capturePlan();
    const plan = state.plans[state.side];
    try {
      plan.rows = core.buildRows(readNumber($('entry')), readNumber($('step')), readNumber($('count')), readNumber($('contracts')), state.side)
        .map(row => ({ price: String(row.price), contracts: String(row.contracts) }));
      generationError = ''; renderRows();
    } catch (error) { generationError = error.message; }
    calculate(); save();
  }
  settingsFields.forEach(id => $(id).addEventListener('input', () => { calculate(); save(); }));
  planFields.forEach(id => $(id).addEventListener('input', generatorFields.includes(id) ? generate : () => { calculate(); save(); }));
  ['long', 'short'].forEach(side => $(side).addEventListener('click', () => { capturePlan(); state.side = side; showPlan(); save(); }));
  $('generate').addEventListener('click', generate);
  load();
  if (!state.settings) state.settings = {};
  showPlan();
})();
