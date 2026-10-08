(function () {
  'use strict';
  const root = document.getElementById('trade-planner');
  if (!root || !window.USDTradePlanner) return;
  const $ = id => document.getElementById('tp-' + id);
  const core = window.USDTradePlanner;
  const KEY = 'usdthb_trade_planner_contracts_v2';
  const settingsFields = ['capital', 'commission', 'fee-mode', 'im', 'mm', 'fm', 'reserve', 'risk', 'series'];
  const planFields = ['entry', 'step', 'count', 'contracts', 'stop', 'exit', 'mark'];
  const generatorFields = ['entry', 'step', 'count', 'contracts'];
  const metricFields = ['equity', 'excess', 'free', 'total', 'average', 'breakeven', 'margin', 'net', 'stop-loss', 'fees', 'cash', 'reserved', 'risk-used', 'mm-price', 'fm-price', 'unrealized'];
  const readNumber = element => element.value.trim() === '' ? NaN : Number(element.value);
  const format = (value, dp = 2) => Number.isFinite(value) ? value.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp }) : '—';
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
      reservePct: readNumber($('reserve')), riskPct: readNumber($('risk'))
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
    $('risk-used').textContent = format(result.riskPct) + '% / งบ ' + format(settings.riskPct) + '%';
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
