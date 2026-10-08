const { test } = require('node:test');
const assert = require('node:assert/strict');
const { calculate, buildRows } = require('./trade-planner-core.js');
const settings = { capital: 1000000, commission: 8, commissionMode: 'roundtrip', im: 770, mm: 541.2, fm: 233.2, reservePct: 20, riskPct: 5 };
const lots = [20, 25, 25, 30];
const plan = { side: 'long', mark: 32.7, exit: 33.5, stop: 32.6,
  rows: [33.3, 33.1, 32.9, 32.7].map((price, i) => ({ price, contracts: lots[i] })) };
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-6, `${actual} != ${expected}`);

test('Long: weighted average, commissions, Equity and EE reconcile independently', () => {
  const r = calculate(settings, plan);
  assert.deepEqual(r.errors, []);
  assert.deepEqual(r.rows.map(row => row.lots), lots);
  assert.equal(r.count, 100);
  near(r.average, 32.97); near(r.breakEven, 32.978);
  near(r.margin, 77000); near(r.fees, 800);
  near(r.unrealized, -27000); near(r.equity, 972600);
  near(r.excess, 895600); near(r.free, 695200);
  near(r.net, 52200); near(r.cashAfterClose, 1052200);
  near(r.stopNet, -37800);
  near(r.rows[1].equity, 995820);
  near(r.rows[1].excess, 961170);
  near(r.mmPrice, 23.5152); near(r.fmPrice, 23.2072);
});
test('Short mirrors Long and moves fee-adjusted breakeven downward', () => {
  const short = { ...plan, side: 'short', mark: 33.9, exit: 33.1, stop: 34,
    rows: [33.3, 33.5, 33.7, 33.9].map((price, i) => ({ price, contracts: lots[i] })) };
  const r = calculate(settings, short);
  assert.deepEqual(r.errors, []); assert.equal(r.count, 100);
  near(r.average, 33.63); near(r.breakEven, 33.622);
  near(r.net, 52200); near(r.stopNet, -37800);
  near(r.equity, 972600); near(r.excess, 895600);
  assert.ok(r.mmPrice > r.average && r.fmPrice > r.mmPrice);
});
test('4 baht per side is equivalent to 8 baht round trip; zero commission stays zero', () => {
  assert.deepEqual(calculate({ ...settings, commission: 4, commissionMode: 'side' }, plan), calculate(settings, plan));
  const r = calculate({ ...settings, commission: 0 }, plan);
  near(r.fees, 0); near(r.breakEven, r.average);
  near(r.excess, r.equity - r.margin);
});
test('hypothetical exit P/L does not change mark-to-market Equity or contract sizing', () => {
  const a = calculate(settings, plan), b = calculate(settings, { ...plan, exit: 36.5 });
  near(a.equity, b.equity); assert.equal(a.count, b.count);
  near(b.net - a.net, 300000);
});
test('generator uses integer contracts per leg and rounds prices to ticks', () => {
  const rows = buildRows(33.3, 0.2, 3, 20, 'long');
  assert.deepEqual(rows.map(row => row.price), [33.3, 33.1, 32.9]);
  assert.deepEqual(rows.map(row => row.contracts), [20, 20, 20]);
  assert.deepEqual(buildRows(33.3, 0.2, 3, 20, 'short').map(row => row.price), [33.3, 33.5, 33.7]);
  assert.throws(() => buildRows(0.1, 0.2, 4, 20, 'long'));
  assert.throws(() => buildRows(33.3, 0.2, 1.5, 20, 'long'));
  assert.throws(() => buildRows(33.3, 0.2, 4, 2.5, 'long'));
  assert.throws(() => buildRows(33.3, 0.2, 4, 0, 'long'));
});
test('exceeding risk budget warns without changing entered contracts or P/L', () => {
  const r = calculate({ ...settings, riskPct: 1 }, plan);
  assert.ok(r.overRisk); assert.equal(r.count, 100);
  assert.deepEqual(r.rows.map(row => row.lots), lots);
  near(r.stopNet, -37800); near(r.average, 32.97);
  assert.ok(r.rows.some(row => row.status === 'เกินกรอบขาดทุน'));
});
test('unaffordable additional contracts remain in the simulation with a funding warning', () => {
  const r = calculate({ ...settings, capital: 10000, reservePct: 20, riskPct: 100 },
    { side: 'long', mark: 32.8, exit: 33.5, stop: 32.5, rows: [{ price: 33.3, contracts: 8 }, { price: 32.8, contracts: 8 }] });
  assert.equal(r.rows[0].lots, 8);
  assert.equal(r.rows[1].lots, 8);
  assert.equal(r.count, 16); assert.equal(r.fundingFeasible, false);
  near(r.rows[1].equity, 5936); near(r.rows[1].excess, -6384);
  assert.equal(r.rows[1].status, 'ทุนไม่พอเปิดตามแผน');
});
test('zero entered contracts create no position or fees and no division by zero', () => {
  const r = calculate(settings, { ...plan, rows: [{ price: 33.3, contracts: 0 }] });
  assert.equal(r.count, 0); assert.deepEqual(r.errors, []);
  assert.equal(r.rows[0].average, null);
  near(r.rows[0].excess, settings.capital);
  near(r.rows[0].spent, 0); near(r.rows[0].fees, 0);
});
test('blank, infinite, negative and fractional tick inputs are rejected', () => {
  for (const patch of [{ capital: NaN }, { commission: -1 }, { im: 0 }, { mm: 1000 }, { fm: -1 }, { reservePct: 100 }, { riskPct: 0 }]) {
    assert.ok(calculate({ ...settings, ...patch }, plan).errors.length);
  }
  for (const patch of [{ mark: NaN }, { exit: Infinity }, { stop: 33.4 }, { mark: 33.333 }]) {
    assert.ok(calculate(settings, { ...plan, ...patch }).errors.length);
  }
  for (const contracts of [NaN, Infinity, -1, 1.5, '20', 1000001]) {
    assert.ok(calculate(settings, { ...plan, rows: [{ price: 33.3, contracts }] }).errors.length);
  }
});
test('MM and FM price thresholds solve the Equity equations for both directions', () => {
  for (const side of ['long', 'short']) {
    const p = { side, mark: 33.3, exit: 33.3, stop: side === 'long' ? 32.5 : 34.1, rows: [{ price: 33.3, contracts: 100 }] };
    const r = calculate(settings, p);
    const sign = side === 'long' ? 1 : -1;
    for (const key of ['mm', 'fm']) {
      const equity = settings.capital + sign * (r[key + 'Price'] - r.average) * r.count * 1000 - r.count * 4;
      near(equity, r.count * settings[key]);
    }
  }
});
test('negative EE is retained and margin status follows the assessment price', () => {
  const s = { ...settings, capital: 10000, reservePct: 0, riskPct: 100 };
  const p = { side: 'long', mark: 32.75, exit: 34, stop: 32.5, rows: [{ price: 33.3, contracts: 10 }] };
  const r = calculate(s, p);
  assert.equal(r.count, 10); near(r.equity, 4460); near(r.excess, -3240);
  assert.equal(r.marginStatus, 'MM');
  assert.equal(calculate(s, { ...p, mark: 32.5 }).marginStatus, 'FM');
});
test('stop before entry and ordered adverse legs are mandatory on both sides', () => {
  assert.ok(calculate(settings, { ...plan, stop: 32.7 }).errors.length);
  assert.ok(calculate(settings, { ...plan, rows: [{ price: 33.3, contracts: 1 }, { price: 33.5, contracts: 1 }] }).errors.length);
  assert.ok(calculate(settings, { ...plan, side: 'short', stop: 34 }).errors.length);
});
test('changing capital, commission or reserve never silently resizes a contract plan', () => {
  for (const patch of [{ capital: 1000 }, { commission: 80 }, { reservePct: 99 }]) {
    const r = calculate({ ...settings, ...patch }, plan);
    assert.deepEqual(r.errors, []);
    assert.equal(r.count, 100); near(r.average, 32.97);
    assert.deepEqual(r.rows.map(row => row.lots), lots);
  }
});
test('zero-quantity intermediate leg is excluded from weighted average and commission', () => {
  const r = calculate(settings, { ...plan, rows: [{ price: 33.3, contracts: 20 }, { price: 33.1, contracts: 0 }, { price: 32.9, contracts: 30 }] });
  assert.equal(r.count, 50); near(r.average, 33.06); near(r.fees, 400);
  assert.equal(r.rows[1].status, 'ไม่เพิ่มสัญญา');
});
test('maintenance breaches flag an infeasible path while preserving the planned additional lots', () => {
  const r = calculate({ ...settings, capital: 10000, reservePct: 0, riskPct: 100 },
    { side: 'long', mark: 32.7, exit: 34, stop: 32.5, rows: [{ price: 33.3, contracts: 10 }, { price: 32.7, contracts: 5 }] });
  assert.equal(r.count, 15); assert.equal(r.fundingFeasible, false);
  assert.equal(r.rows[1].status, 'เปิดเพิ่มไม่ได้: แตะ MM/FM');
});
test('one contract calculates required cash and fees in baht without a notional purchase cost', () => {
  const r = calculate(settings, { ...plan, rows: [{ price: 33.3, contracts: 1 }], mark: 33.3, exit: 33.31 });
  near(r.rows[0].spent, 778); near(r.margin, 770); near(r.fees, 8);
  near(r.equity, 999996); near(r.excess, 999226); near(r.net, 2);
});
