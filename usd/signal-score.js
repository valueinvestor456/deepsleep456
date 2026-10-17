(function(root,factory){
  var api=factory();
  if(typeof module==='object' && module.exports) module.exports=api;
  else root.UsdScore=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  var DAY=86400000;
  var KEYS=['dxy','us2','oil','gold','foreign','account'];
  // Rule-based scenario weights, not fitted coefficients or probabilities.
  var BASE={short:[20,20,15,10,15,20],medium:[20,20,15,10,15,20],long:[15,15,15,10,15,30]};
  var LABELS={dxy:'DXY',us2:'US 2Y',oil:'Brent',gold:'Gold Flow Proxy',foreign:'Foreign Flow',account:'Current Account'};
  var SCALES={dxy:.35,us2:5,oil:2,gold:25000,foreign:5000,account:2000};
  var SIGN={dxy:-1,us2:-1,oil:-1,gold:1,foreign:1,account:1};
  function number(v){
    if((typeof v!=='number' && typeof v!=='string') || String(v).trim()==='') return null;
    var n=Number(v);return Number.isFinite(n)?n:null;
  }
  function day(value){
    if(typeof value!=='string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    var n=Date.parse(value+'T00:00:00Z');
    return Number.isFinite(n)&&new Date(n).toISOString().slice(0,10)===value?n:null;
  }
  function monthEnd(value){
    if(typeof value!=='string'||!/^\d{4}-(0[1-9]|1[0-2])$/.test(value))return null;
    return Date.UTC(Number(value.slice(0,4)),Number(value.slice(5,7)),0);
  }
  function freshness(observation,now){
    if(observation.manual) return 1;
    var monthly=observation.frequency==='monthly';
    var stamp=monthly?monthEnd(observation.period):day(observation.date);
    if(stamp===null || stamp>now) return 0;
    var age=(now-stamp)/DAY, full=monthly?45:3, limit=monthly?90:10;
    return age<=full?1:Math.max(0,1-(age-full)/(limit-full));
  }
  function assessGoldTrade(q,now){
    q=q||{};now=now===undefined?Date.now():now;
    var ex=number(q.exports_m_thb),im=number(q.imports_m_thb);
    var available=q.unit==='million_THB' && q.proxy===true && ex!==null && im!==null && ex>=0 && im>=0 && freshness({frequency:'monthly',period:q.period},now)>0;
    var net=available?ex-im:null;
    return {available:available&&Number.isFinite(net),net:net,exports:ex,imports:im,period:q.period};
  }
  function assessMonthly(q,now){
    q=q||{};now=now===undefined?Date.now():now;
    var value=number(q.value_m_usd);
    return {available:value!==null&&q.unit==='million_USD'&&freshness({frequency:'monthly',period:q.period},now)>0,value:value,period:q.period};
  }
  function assessForeign(q,now){
    q=q||{};now=now===undefined?Date.now():now;
    var stock=q.stocks||{},bond=q.bonds||{},s=number(stock.net_m_thb),b=number(bond.net_m_thb);
    var sv=s!==null&&stock.unit==='million_THB'&&freshness(stock,now)>0;
    var bv=b!==null&&bond.unit==='million_THB'&&freshness(bond,now)>0;
    // Never add trading flows from different dates; expose the missing coverage.
    var both=sv&&bv&&stock.date===bond.date;
    var chosen=both?null:sv&&bv?(stock.date>bond.date?'stocks':'bonds'):sv?'stocks':bv?'bonds':null;
    return {available:both||!!chosen,net:both?s+b:chosen==='stocks'?s:chosen==='bonds'?b:null,
      date:both?stock.date:chosen?q[chosen].date:null,coverage:both?1:chosen?0.5:0,
      stocks:sv?s:null,bonds:bv?b:null,stockDate:stock.date,bondDate:bond.date,
      included:both?'both':chosen,reason:sv&&bv&&!both?'ข้อมูลคนละวัน ใช้ตลาดที่ใหม่กว่า':''};
  }
  function composite(observations,horizon,now){
    now=now===undefined?Date.now():now;observations=observations||{};
    var base=BASE[horizon]||BASE.medium;
    var rows=KEYS.map(function(key,i){
      var o=observations[key]||{},v=number(o.value),scale=number(o.scale)||SCALES[key];
      var fresh=freshness(o,now),quality=number(o.quality);
      quality=quality===null?1:Math.max(0,Math.min(1,quality));
      var available=v!==null&&scale>0&&fresh>0&&quality>0;
      var z=available?SIGN[key]*v/scale:0;
      if(!Number.isFinite(z)){available=false;z=0;}
      // Large observed moves increase salience, bounded at 2x. No news/regime prediction.
      var shock=available?1+Math.min(1,Math.max(0,Math.abs(z)-1)*0.5):1;
      return {key:key,label:LABELS[key],base:base[i],raw:base[i]*shock,shock:shock,
        freshness:fresh,quality:quality,available:available,z:z,manual:!!o.manual,
        signal:Math.tanh(z),period:o.period||o.date||'',frequency:o.frequency||'daily'};
    });
    var denominator=rows.reduce(function(a,r){return a+r.raw;},0),coverage=0,score=0;
    rows.forEach(function(r){
      r.weight=100*r.raw/denominator;
      r.effectiveWeight=r.available?r.weight*r.freshness*r.quality:0;
      r.contribution=r.effectiveWeight*r.signal || 0;
      coverage+=r.effectiveWeight;score+=r.contribution;
    });
    var count=rows.filter(function(r){return r.available;}).length;
    var ready=count>=3&&coverage>=50;
    // Missing weight remains in denominator. Missing data never boosts other signals.
    var direction=!ready?'missing':score>=15?'strong':score<=-15?'weak':'mixed';
    return {score:count?score:null,coverage:coverage,count:count,ready:ready,direction:direction,
      scenario:rows.some(function(r){return r.available&&r.manual;}),rows:rows,
      leaders:rows.filter(function(r){return r.available;}).sort(function(a,b){return Math.abs(b.contribution)-Math.abs(a.contribution);}).slice(0,3)};
  }
  return {number:number,day:day,monthEnd:monthEnd,freshness:freshness,assessGoldTrade:assessGoldTrade,
    assessMonthly:assessMonthly,assessForeign:assessForeign,composite:composite};
});
