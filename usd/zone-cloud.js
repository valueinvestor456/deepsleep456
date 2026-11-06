(function startZoneCard() {
  const card = document.getElementById('zone-live-card');
  if (!card) return;
  const byId = (id) => document.getElementById(id);
  const action = byId('zone-live-action');
  const foot = byId('zone-live-foot');
  const title = card.querySelector('.zone-live-title');
  title.textContent = 'USD1! ZONE · ราคาปิดแท่ง 15 นาที';
  byId('zone-live-spot').textContent = 'Last: —';
  function clearReadings() {
    byId('zone-live-spot').textContent = 'Last: —';
    for (const key of ['premium', 'equilibrium', 'discount']) byId('zone-live-' + key).textContent = '—';
  }
  function waiting(message, label = 'WAIT · ยังไม่ยืนยันราคา', stale = false) {
    card.className = stale ? 'zone-live-card zone-stale' : 'zone-live-card';
    action.textContent = label;
    foot.textContent = message;
  }
  const fmt = (n, digits = 2) => Number.isFinite(n) ? n.toFixed(digits) : '—';
  function marketClosedNow() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Bangkok', weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }).formatToParts(new Date()).map(part => [part.type, part.value]));
    const minutes = Number(parts.hour) * 60 + Number(parts.minute);
    const daytime = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(parts.weekday);
    const nightContinuation = ['Tue', 'Wed', 'Thu', 'Fri', 'Sat'].includes(parts.weekday);
    const morningStart = `${parts.year}-${parts.month}-${parts.day}` >= '2026-11-16' ? 8 * 60 : 9 * 60 + 45;
    return !(daytime && ((minutes >= morningStart && minutes < 12 * 60 + 30) ||
      (minutes >= 13 * 60 + 45 && minutes < 16 * 60 + 55) || minutes >= 18 * 60 + 50) ||
      (nightContinuation && minutes < 3 * 60));
  }
  function outsidePosition(p) {
    if (p.spot > p.premium.high) return 'เหนือช่วง Premium';
    if (p.spot < p.discount.low) return 'ต่ำกว่าช่วง Discount';
    return 'อยู่นอกช่วงโซน';
  }
  function render(data) {
    const p = data?.payload;
    if (!data?.ok || !p) { clearReadings(); waiting('รอแท่งจริงจาก TradingView · ไม่ใช่ราคาจำลอง'); return; }
    if (p.symbol !== 'TFEX:USD1!' || p.timeframe !== '15') { clearReadings(); waiting('ข้อมูลไม่ตรงกับ USD1! 15m'); return; }
    const ranges = ['premium', 'equilibrium', 'discount'];
    if (!Number.isFinite(p.spot) || p.spot <= 0 || !Number.isFinite(p.bar_close) || p.bar_close > Date.now() + 60000 ||
        ranges.some(key => !Number.isFinite(p[key]?.low) || !Number.isFinite(p[key]?.high) || p[key].low <= 0 || p[key].low > p[key].high) ||
        p.discount.high >= p.equilibrium.low || p.equilibrium.high >= p.premium.low) {
      clearReadings(); waiting('ข้อมูลราคา/ขอบเขตโซนไม่สมบูรณ์ · รอข้อมูลใหม่'); return;
    }
    const actualZone = ranges.find(key => p.spot >= p[key].low && p.spot <= p[key].high)?.toUpperCase() || 'OUTSIDE';
    if (p.zone !== actualZone) { clearReadings(); waiting('สถานะโซนไม่ตรงกับราคา · รอข้อมูลใหม่'); return; }
    const position = p.zone === 'OUTSIDE' ? outsidePosition(p) : '';
    byId('zone-live-spot').textContent = `Last: ${fmt(p.spot)} · TFEX:USD1! (Futures)`;
    for (const key of ranges) {
      byId('zone-live-' + key).textContent = `${fmt(p[key]?.low, 4)} – ${fmt(p[key]?.high, 4)}`;
    }
    const time = new Date(p.bar_close).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' });
    const closeTime = new Intl.DateTimeFormat('th-TH', { timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(p.bar_close));
    if (data.stale || Date.now() - p.bar_close > 30 * 60000) {
      clearReadings();
      byId('zone-live-spot').textContent = `Last close: ${fmt(p.spot)} · TFEX:USD1! · ${time} (ไทย)`;
      const closed = marketClosedNow();
      waiting((closed ? 'TFEX นอกช่วงซื้อขาย · Spot อาจเคลื่อนไหวต่อได้' : 'ช่วงซื้อขายแต่ยังไม่มีแท่งยืนยันใหม่ · ตรวจ TradingView Alert') +
        ' · ซ่อนระดับโซนเก่า · ไม่ใช่สัญญาณเปิดสถานะ',
        (closed ? 'ตลาดปิด/พัก' : 'WAIT · รอแท่งใหม่') + ` · USD1! ${fmt(p.spot)} (${closeTime})`, true);
      return;
    }
    const zone = p.zone;
    if (zone === 'OUTSIDE') {
      waiting('TradingView · แท่งปิด ' + time + ' (ไทย) · ไม่ใช่สัญญาณเข้าโซน', `WAIT · ${position} · ${fmt(p.spot)}`);
      return;
    }
    const signal = zone === 'PREMIUM' ? 'เฝ้า SHORT' : zone === 'DISCOUNT' ? 'เฝ้า LONG' : 'WAIT';
    card.className = 'zone-live-card zone-' + String(zone).toLowerCase();
    action.textContent = `${signal} · ${zone} · ${fmt(p.spot)}`;
    foot.textContent = 'TradingView · แท่งปิด ' + time + ' (ไทย) · ตรวจข้อมูลทุก 30 วินาที';
  }
  async function poll() {
    try {
      const response = await fetch('/api/member/latest', { cache: 'no-store', credentials: 'same-origin', signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw Error('Unavailable');
      render(await response.json());
    } catch { clearReadings(); waiting('เชื่อมต่อ Cloud ไม่ได้ · อย่าใช้สัญญาณเดิมส่งคำสั่ง'); }
  }
  waiting('กำลังตรวจข้อมูล Cloud…');
  poll();
  setInterval(poll, 30000);
})();
