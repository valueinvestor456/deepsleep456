(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.USDTradePlanner = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const SIZE = 1000;
  const EPS = 1e-7;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const priceOK = value => finite(value) && value > 0 && value <= 100000 && Math.abs(value * 100 - Math.round(value * 100)) < EPS;
  const contractsOK = value => Number.isSafeInteger(value) && value >= 0 && value <= 1000000;

  function buildRows(entry, step, count, contracts, side) {
    if (!priceOK(entry) || !priceOK(step) || !Number.isInteger(count) || count < 1 || count > 12 ||
        !contractsOK(contracts) || contracts === 0 || !['long', 'short'].includes(side)) {
      throw new Error('กรอกราคาและระยะห่างเป็นหน่วย 0.01 จำนวนไม้ 1–12 และสัญญาต่อไม้เป็นจำนวนเต็ม 1–1,000,000');
    }
    const direction = side === 'long' ? 1 : -1;
    const rows = Array.from({ length: count }, (_, i) => ({
      price: Math.round((entry - direction * step * i) * 100) / 100,
      contracts
    }));
    if (rows.some(row => !priceOK(row.price))) throw new Error('ราคาแต่ละไม้ต้องมากกว่า 0');
    return rows;
  }

  function calculate(settings, plan) {
    const errors = [];
    const { capital, commission, commissionMode, im, mm, fm, reservePct, riskPct } = settings;
    if (!finite(capital) || capital <= 0 || capital > 1e12) errors.push('เงินทุนต้องมากกว่า 0 และไม่เกิน 1,000,000 ล้านบาท');
    if (!finite(commission) || commission < 0 || !['side', 'roundtrip'].includes(commissionMode)) errors.push('ค่าคอมมิชชั่นต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป');
    if (![im, mm, fm].every(finite) || !(im > mm && mm > fm && fm >= 0)) errors.push('มาร์จินต้องเรียง IM > MM > FM ≥ 0');
    if (!finite(reservePct) || reservePct < 0 || reservePct >= 100) errors.push('เงินสำรองต้องอยู่ระหว่าง 0 ถึงน้อยกว่า 100%');
    if (!finite(riskPct) || riskPct <= 0 || riskPct > 100) errors.push('งบขาดทุนต้องมากกว่า 0 และไม่เกิน 100%');
    if (!['long', 'short'].includes(plan.side)) errors.push('เลือก Long หรือ Short');
    if (!priceOK(plan.stop) || !priceOK(plan.exit) || !priceOK(plan.mark)) errors.push('ราคาประเมินพอร์ต หยุดขาดทุน และราคาปิดต้องมากกว่า 0 และเป็นหน่วย 0.01');
    if (!Array.isArray(plan.rows) || plan.rows.length < 1 || plan.rows.length > 12) errors.push('ต้องมีแผน 1–12 ไม้');
    const direction = plan.side === 'long' ? 1 : -1;
    (Array.isArray(plan.rows) ? plan.rows : []).forEach((row, i) => {
      if (!priceOK(row.price)) errors.push(`ไม้ ${i + 1}: ราคาต้องมากกว่า 0 และเป็นหน่วย 0.01`);
      if (!contractsOK(row.contracts)) errors.push(`ไม้ ${i + 1}: จำนวนสัญญาต้องเป็นจำนวนเต็ม 0–1,000,000`);
      if (priceOK(row.price) && priceOK(plan.stop) && direction * (row.price - plan.stop) <= 0) errors.push(`ไม้ ${i + 1}: จุดหยุดขาดทุนต้องอยู่${direction === 1 ? 'ต่ำกว่า' : 'สูงกว่า'}ราคาเข้า`);
      if (i && direction * (row.price - plan.rows[i - 1].price) > EPS) errors.push(`ไม้ ${i + 1}: ราคาเพิ่ม Long ต้องไม่สูงขึ้น / เพิ่ม Short ต้องไม่ต่ำลง`);
    });
    if (errors.length) return { errors, rows: [] };

    const feeRT = commission * (commissionMode === 'side' ? 2 : 1);
    const feeOpen = feeRT / 2;
    const reserve = capital * reservePct / 100;
    const riskBudget = capital * riskPct / 100;
    let count = 0, cost = 0, riskUsed = 0, fundingFeasible = true;
    const rows = plan.rows.map(row => {
      const beforePnl = direction * (row.price * count - cost) * SIZE;
      const beforeEquity = capital + beforePnl - count * feeOpen;
      // Keep the entered contract count. Funding/risk checks explain whether the
      // hypothetical plan can be executed; they must never resize it silently.
      const lots = row.contracts;
      const belowMaintenance = count > 0 && beforeEquity <= count * mm + EPS;
      const canOpen = lots === 0 || (!belowMaintenance && beforeEquity - count * im + EPS >= lots * (im + feeOpen));
      fundingFeasible = fundingFeasible && canOpen;
      const riskPerLot = direction * (row.price - plan.stop) * SIZE + feeRT;
      count += lots;
      cost += row.price * lots;
      riskUsed += lots * riskPerLot;
      const gross = direction * (row.price * count - cost) * SIZE;
      const equity = capital + gross - count * feeOpen;
      const free = equity - count * (im + feeOpen) - reserve;
      const overRisk = riskUsed > riskBudget + EPS;
      const belowReserve = free < -EPS;
      let status = lots === 0 ? 'ไม่เพิ่มสัญญา' : 'ตามจำนวนที่กรอก';
      if (!canOpen) status = belowMaintenance ? 'เปิดเพิ่มไม่ได้: แตะ MM/FM' : 'ทุนไม่พอเปิดตามแผน';
      else if (!fundingFeasible) status = 'ไม้ก่อนหน้าทุนไม่พอ';
      else if (overRisk) status = 'เกินกรอบขาดทุน';
      else if (belowReserve) status = 'ต่ำกว่าเงินสำรองที่ตั้ง';
      return { ...row, lots, count, average: count ? cost / count : null,
        margin: count * im, equity, excess: equity - count * im,
        free, gross, riskUsed, fees: count * feeRT, spent: lots * (im + feeRT),
        canOpen, fundingFeasible, overRisk, belowReserve, status };
    });
    if (!count) return { errors: [], rows, count, feeRT, reserve, riskBudget };
    const average = cost / count;
    const gross = direction * (plan.exit * count - cost) * SIZE;
    const net = gross - count * feeRT;
    const unrealized = direction * (plan.mark * count - cost) * SIZE;
    const equity = capital + unrealized - count * feeOpen;
    const threshold = level => average + direction * (level * count - capital + count * feeOpen) / (SIZE * count);
    const marginStatus = equity <= count * fm + EPS ? 'FM' : equity <= count * mm + EPS ? 'MM' : equity < count * im - EPS ? 'IM' : 'OK';
    return { errors: [], rows, count, average, feeRT, reserve, riskBudget,
      fees: count * feeRT, breakEven: average + direction * feeRT / SIZE,
      margin: count * im, gross, net, equity, unrealized, excess: equity - count * im,
      free: equity - count * (im + feeOpen) - reserve, cashAfterClose: capital + net,
      stopNet: -riskUsed, riskPct: riskUsed / capital * 100,
      mmPrice: threshold(mm), fmPrice: threshold(fm), marginStatus,
      fundingFeasible, overRisk: riskUsed > riskBudget + EPS,
      reserveBreached: rows.some(row => row.belowReserve),
      lastFree: rows[rows.length - 1].free };
  }
  return { calculate, buildRows };
});
