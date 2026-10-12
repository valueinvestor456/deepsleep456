(function(root, factory){
  var api = factory(typeof module === 'object' && module.exports ? require('./signal-score.js') : root.UsdScore);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.UsdSignals = api; api.mount(root.document); }
})(typeof globalThis !== 'undefined' ? globalThis : this, function(Score){
  'use strict';
  function number(value){
    if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') return null;
    var result = Number(value);
    return Number.isFinite(result) ? result : null;
  }
  function pressure(kind, value){
    var n = number(value);
    var sign = {dxy:1, us2:1, oil:1, gold:1, foreign:-1, account:-1}[kind];
    if (n === null || !sign) return 'missing';
    if (Math.abs(n) < 1e-10) return 'flat';
    return n * sign > 0 ? 'up' : 'down';
  }
  function fundNet(stocks, bonds){
    var s = number(stocks), b = number(bonds);
    return s === null || b === null || !Number.isFinite(s+b) ? null : s+b;
  }
  function assessYield(mode, quote, current, previous, now){
    var auto = mode !== 'manual';
    quote = quote || {};
    var last = number(auto ? quote.last : current), prev = number(auto ? quote.previous : previous);
    var result = {last:last, previous:prev, bps:null, available:false, reason:'รอข้อมูล US 2Y'};
    if (last === null || prev === null) return result;
    if (auto){
      var validDate = function(value){
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
        var n = Date.parse(value+'T00:00:00Z');
        return Number.isFinite(n) && new Date(n).toISOString().slice(0,10) === value ? n : null;
      };
      var date = validDate(quote.date), before = validDate(quote.previous_date), time = now === undefined ? Date.now() : now;
      if (date === null || before === null || before >= date || date > time || time-date > 10*86400000 || date-before > 7*86400000){
        result.reason = 'วันที่ไม่ถูกต้องหรือข้อมูลเก่าเกินเกณฑ์'; return result;
      }
    }
    result.bps = (last-prev)*100;
    result.available = Number.isFinite(result.bps);
    result.reason = result.available ? '' : 'ค่าผลตอบแทนไม่ถูกต้อง';
    return result;
  }
  var dom, market = {};
  var fields = ['sg-horizon','sg-us2-mode','sg-us2-last','sg-us2-prev','sg-gold-mode','sg-gold-flow','sg-gold-date','sg-foreign-mode','sg-stock-net','sg-bond-net','sg-foreign-date','sg-account-mode','sg-ca-value','sg-ca-month'];
  var manualFields={'sg-us2-mode':['sg-us2-last','sg-us2-prev'],'sg-foreign-mode':['sg-stock-net','sg-bond-net','sg-foreign-date'],'sg-account-mode':['sg-ca-value','sg-ca-month']};
  function el(id){ return dom.getElementById(id); }
  function format(value, dp){ return value === null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US',{minimumFractionDigits:dp,maximumFractionDigits:dp}); }
  function signed(value, dp){ return (value > 0 ? '+' : '') + format(value,dp); }
  function show(kind, value, reading, source){
    var direction = pressure(kind,value);
    el('sg-'+kind+'-value').textContent = reading;
    var badge = el('sg-'+kind+'-impact');
    badge.dataset.direction = direction;
    badge.textContent = {up:'↑ หนุน USD/THB ขึ้น · บาทอ่อน',down:'↓ หนุน USD/THB ลง · บาทแข็ง',flat:'→ ไม่มีแรงหนุนจากค่าปัจจัยนี้',missing:'— รอข้อมูล ไม่สรุปทิศทาง'}[direction];
    el('sg-'+kind+'-source').textContent = source;
  }
  function manualStamp(date, monthly){ return 'กรอกจำลองเอง · ' + (date ? (monthly ? 'งวด ' : 'วันที่ ') + date : 'ยังไม่ระบุ'+(monthly ? 'งวด' : 'วันที่')); }
  function fill(id,value){el(id).value=value === null || value === undefined ? '' : value;}
  function readOnly(ids,auto){ids.forEach(function(id){el(id).readOnly=auto;});}
  function renderScore(observations){
    var result=Score.composite(observations,el('sg-horizon').value);
    var verdict={strong:'เอนเอียงไปทางบาทแข็ง · USD/THB ลง',weak:'เอนเอียงไปทางบาทอ่อน · USD/THB ขึ้น',mixed:'แรงหนุนผสม · ยังไม่ชัดเจน',missing:'ข้อมูลไม่พอให้สรุปทิศทาง'}[result.direction];
    ['sg-score','sg-score-top'].forEach(function(id){el(id).textContent=result.score===null?'—':signed(result.score,1);el(id).dataset.direction=result.direction;});
    ['sg-verdict','sg-verdict-top'].forEach(function(id){el(id).textContent=verdict;});
    var coverage='ใช้ได้ '+result.count+'/6 ปัจจัย · น้ำหนักที่ใช้ได้ '+format(result.coverage,0)+'%';
    el('sg-coverage').textContent=coverage+' · ค่านี้บอกความครอบคลุมข้อมูล ไม่ใช่โอกาสทายถูก';
    el('sg-top-coverage').textContent=coverage;
    el('sg-scenario').textContent=result.scenario?'โหมดจำลอง · มีค่าที่กรอกเอง':'โหมดข้อมูลอัตโนมัติ · ใช้ข้อมูลล่าสุดที่เผยแพร่';
    el('sg-score-pin').style.left=(result.score===null?50:(result.score+100)/2)+'%';
    el('sg-score-pin').hidden=!result.ready;
    el('sg-drivers').textContent=result.leaders.length?'ตัวขับหลัก: '+result.leaders.map(function(r){return r.label+' '+signed(r.contribution,1)+' คะแนน';}).join(' · '):'รอแหล่งข้อมูลก่อนคำนวณ';
    var body=el('sg-weights');body.replaceChildren();
    result.rows.forEach(function(r){
      var tr=dom.createElement('tr');
      [r.label,r.manual?'จำลอง':r.period||'—',format(r.base,0)+'%',(r.shock>1?'×'+format(r.shock,2):'×1.00'),r.available?format(r.freshness*100,0)+'%':'—',format(r.quality*100,0)+'%',format(r.effectiveWeight,1)+'%',r.available?signed(r.contribution,1):'—'].forEach(function(value){var td=dom.createElement('td');td.textContent=value;tr.appendChild(td);});
      body.appendChild(tr);
      el('sg-'+r.key+'-weight').textContent=r.available?'น้ำหนักใช้จริง '+format(r.effectiveWeight,1)+'% · ต่อคะแนนรวม '+signed(r.contribution,1):'ยังไม่นำมาคำนวณ · ข้อมูลไม่ครบหรือเก่าเกินเกณฑ์';
    });
  }
  function render(){
    if (!dom) return;
    var dq=market.dxy||{}, da=assessYield('auto',dq), oil = market.oil || {};
    var futures = oil.market_type === 'futures';
    var dxy=market.dxyManual?number(market.dxyChange):da.available&&da.last>0&&da.previous>0?(da.last/da.previous-1)*100:null;
    show('dxy',dxy,dxy === null ? 'Δ รอข้อมูล' : (market.dxyManual?'Δ ':format(da.last,2)+' · ')+signed(dxy,2)+'%',
      market.dxyManual ? 'จำลองจาก Δ% ที่กรอก' : 'Synthetic DXY · ECB ผ่าน Frankfurter · '+(dq.date?dq.date+' เทียบ '+dq.previous_date:'รอข้อมูลรายวัน')+' · ไม่ใช่ราคา ICE เรียลไทม์');
    show('oil',oil.available ? oil.pct : null,oil.available ? '$'+format(oil.last,2)+' · '+signed(oil.pct,2)+'%' : 'รอราคา Brent',
      oil.manual ? 'กรอกจำลองเอง · Brent USD/บาร์เรล' : (futures ? 'Yahoo Finance · BZ=F · ราคา delayed · เปลี่ยนแปลงระหว่าง '+(oil.date ? oil.previousDate+' → '+oil.date : 'วันที่ยังไม่ทราบ') : 'EIA / FRED · เปลี่ยนแปลงระหว่าง '+(oil.date ? oil.previousDate+' → '+oil.date : 'วันที่ยังไม่ทราบ'))+' · ใช้ช่วงนี้คำนวณคะแนน'+(oil.available ? '' : ' · งดสรุปทิศทาง'));
    el('sg-oil-title').textContent=oil.manual?'Brent · จำลอง':(futures?'Brent Futures · BZ=F':'Brent Spot · EIA');
    el('sg-oil-date').textContent=oil.manual?'ราคาที่กรอกจำลองเอง':oil.date?'ราคา ณ '+(oil.timestamp || oil.date)+' · '+(Number.isFinite(oil.ageDays)?Math.floor(oil.ageDays)+' วันก่อน':(futures?'ฟีดดีเลย์':'ข้อมูลรายวัน')):'ราคาอ้างอิง · ยังไม่มีข้อมูล';
    el('sg-oil-context').textContent=oil.manual?'ใช้ราคาปัจจุบันและราคาอ้างอิงของสินค้าชนิดเดียวกันและแหล่งเดียวกัน':(futures?'Brent Futures BZ=F · ราคา delayed จาก Yahoo Finance สำหรับเทียบตลาด TradingView · ไม่ใช่ Europe Brent Spot FOB':'Europe Brent Spot FOB · ไม่ใช่ราคา Brent Futures / CFD ที่ซื้อขายขณะนี้ใน TradingView');
    var mode = el('sg-us2-mode').value, quote = market.us2 || {};
    var yields = assessYield(mode,quote,el('sg-us2-last').value,el('sg-us2-prev').value);
    el('sg-us2-last').readOnly = el('sg-us2-prev').readOnly = mode !== 'manual';
    if(mode !== 'manual'){
      el('sg-us2-last').value = yields.last === null ? '' : yields.last;
      el('sg-us2-prev').value = yields.previous === null ? '' : yields.previous;
    }
    show('us2',yields.available ? yields.bps : null,yields.available ? format(yields.last,2)+'% · '+signed(yields.bps,1)+' bp' : 'รอผลตอบแทน US 2Y',
      (mode === 'manual' ? 'กรอกจำลองเอง' : 'U.S. Treasury · '+(quote.date ? quote.date+' เทียบ '+quote.previous_date : 'ยังไม่มีข้อมูล'))+(yields.reason ? ' · '+yields.reason : ''));
    var gold = el('sg-gold-flow').value, ga=Score.assessGoldTrade(market.goldTrade), goldAuto=el('sg-gold-mode').value!=='manual';
    var goldValues = {buy:1,sell:-1,flat:0}, goldLabels = {buy:'ซื้อ USD สุทธิ',sell:'ขาย USD สุทธิ',flat:'สมดุล / ไม่มีทิศทาง'};
    el('sg-gold-auto-fields').hidden=!goldAuto;el('sg-gold-manual-fields').hidden=goldAuto;
    fill('sg-gold-exports',ga.exports);fill('sg-gold-imports',ga.imports);fill('sg-gold-month',ga.period);
    el('sg-gold-rule').textContent=goldAuto?'ส่งออกทองสุทธิ → อาจหนุนบาทแข็ง · นำเข้าสุทธิ → อาจหนุนบาทอ่อน':'ซื้อ USD สุทธิ → หนุนบาทอ่อน · ขาย USD สุทธิ → หนุนบาทแข็ง';
    show('gold',goldAuto?(ga.available?-ga.net:null):goldValues[gold],goldAuto?(ga.available?(ga.net>=0?'ส่งออก':'นำเข้า')+'สุทธิ '+format(Math.abs(ga.net),2)+' ลบ.':'รอข้อมูลการค้าทอง'):goldLabels[gold]||'รอทิศทางธุรกรรม USD',
      goldAuto?'อัตโนมัติ · Gold Flow Proxy รายเดือน '+(ga.period||'—')+' · ศุลกากร / ธปท.':manualStamp(el('sg-gold-date').value));
    var foreignAuto=el('sg-foreign-mode').value!=='manual', fa=Score.assessForeign(market.foreignFlow);
    readOnly(['sg-stock-net','sg-bond-net','sg-foreign-date'],foreignAuto);
    if(foreignAuto){fill('sg-stock-net',fa.stocks);fill('sg-bond-net',fa.bonds);fill('sg-foreign-date',fa.date);}
    var net = foreignAuto?fa.net:fundNet(el('sg-stock-net').value,el('sg-bond-net').value);
    var foreignSource=foreignAuto?'อัตโนมัติ · '+(fa.included==='both'?'SET + ThaiBMA':fa.included==='bonds'?'เฉพาะพันธบัตร ThaiBMA · ขาดฝั่งหุ้น SET':fa.included==='stocks'?'เฉพาะหุ้น SET · ขาดฝั่งพันธบัตร':'ยังดึงข้อมูลไม่ได้')+' · '+(fa.date||'—')+(fa.reason?' · '+fa.reason:''):manualStamp(el('sg-foreign-date').value)+' · ใช้ยอดสุทธิของวันเดียวกัน';
    show('foreign',net,net === null ? 'รอยอดเงินทุนต่างชาติ' : 'สุทธิ '+signed(net,2)+' ลบ.',foreignSource);
    var accountAuto=el('sg-account-mode').value!=='manual', ca=Score.assessMonthly(market.currentAccount);
    readOnly(['sg-ca-value','sg-ca-month'],accountAuto);
    if(accountAuto){fill('sg-ca-value',ca.value);fill('sg-ca-month',ca.period);}
    var account = accountAuto?(ca.available?ca.value:null):number(el('sg-ca-value').value);
    show('account',account,account === null ? 'รอดุลบัญชีเดินสะพัด' : signed(account,2)+' ล้าน USD',accountAuto?'อัตโนมัติ · ธปท. · งวด '+(ca.period||'—')+' · ข้อมูลรายเดือน มีความล่าช้า':manualStamp(el('sg-ca-month').value,true));
    renderScore({
      dxy:{value:dxy,date:dq.date,manual:market.dxyManual},
      us2:{value:yields.available?yields.bps:null,date:quote.date,manual:mode==='manual'},
      oil:{value:oil.available?oil.pct:null,date:oil.date,manual:oil.manual},
      gold:goldAuto?{value:ga.available?ga.net:null,frequency:'monthly',period:ga.period,quality:.6}:{value:goldValues[gold]===undefined?null:-goldValues[gold],scale:1,manual:true,quality:.5},
      foreign:{value:net,date:fa.date,manual:!foreignAuto,quality:foreignAuto?fa.coverage:1},
      account:{value:account,frequency:'monthly',period:ca.period,manual:!accountAuto}
    });
  }
  function mount(document){
    if(!document || !document.getElementById('usd-signals')) return;
    dom = document;
    fields.forEach(function(id){
      try { var value = localStorage.getItem('usdthb_'+id); if(value !== null) el(id).value = value; } catch (_) {}
      el(id).addEventListener('input',function(){
        try {
          localStorage.setItem('usdthb_'+id,el(id).value);
          if(manualFields[id] && el(id).value==='manual') manualFields[id].forEach(function(field){var stored=localStorage.getItem('usdthb_'+field);if(stored!==null)fill(field,stored);});
        } catch (_) {}
        render();
      });
    });
    el('sg-auto-all').addEventListener('click',function(){
      ['sg-us2-mode','sg-gold-mode','sg-foreign-mode','sg-account-mode'].forEach(function(id){fill(id,'auto');try{localStorage.setItem('usdthb_'+id,'auto');}catch(_){};});
      dom.dispatchEvent(new dom.defaultView.Event('usd-signals-auto'));
      render();
    });
    render();
  }
  return {pressure:pressure,fundNet:fundNet,assessYield:assessYield,mount:mount,updateMarket:function(value){market=value || {};render();}};
});
