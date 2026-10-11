const {test}=require('node:test');
const assert=require('node:assert/strict');
const S=require('./signal-score.js');
const now=Date.parse('2026-10-11T00:00:00Z');
const daily=value=>({value,date:'2026-10-09'});
const monthly=value=>({value,period:'2026-08',frequency:'monthly'});
const complete={dxy:daily(-.35),us2:daily(-5),oil:daily(-2),gold:monthly(25000),foreign:daily(5000),account:monthly(2000)};
test('all strengthening factors yield positive THB score, opposite factors negative',()=>{
  const a=S.composite(complete,'medium',now);
  assert.equal(a.direction,'strong');assert.equal(a.coverage,100);
  const b=S.composite(Object.fromEntries(Object.entries(complete).map(([k,v])=>[k,{...v,value:-v.value}])),'medium',now);
  assert.equal(b.direction,'weak');assert.ok(Math.abs(a.score+b.score)<1e-10);
  assert.ok(Math.abs(a.score-a.rows.reduce((s,r)=>s+r.contribution,0))<1e-10);
});
test('missing and stale data cannot create a confident neutral verdict or inflate score',()=>{
  assert.equal(S.composite({},'short',now).score,null);
  assert.equal(S.composite({dxy:daily(-.35)},'short',now).direction,'missing');
  const all=S.composite(complete,'medium',now);
  const missing=S.composite({...complete,us2:{}},'medium',now);
  assert.ok(missing.coverage<all.coverage);assert.ok(missing.score<all.score);
  assert.equal(S.composite({dxy:{value:1,date:'2026-09-01'}},'medium',now).count,0);
  assert.equal(S.composite({dxy:{value:1,date:'2026-10-12'}},'medium',now).count,0);
});
test('horizon and observed shocks change weight; old data fades',()=>{
  const short=S.composite(complete,'short',now),long=S.composite(complete,'long',now);
  assert.ok(short.rows[0].weight>long.rows[0].weight);
  assert.ok(long.rows[5].weight>short.rows[5].weight);
  const shocked=S.composite({...complete,oil:daily(-6)},'medium',now);
  assert.equal(shocked.rows[2].shock,2);assert.ok(shocked.rows[2].weight>20);
  const old=S.composite({...complete,oil:{value:-2,date:'2026-10-05'}},'medium',now);
  assert.ok(old.rows[2].effectiveWeight<20);
});
test('monthly gold validates units, period, completion and recomputes net',()=>{
  const q={exports_m_thb:79000,imports_m_thb:61000,period:'2026-08',unit:'million_THB',proxy:true,net_exports_m_thb:9999};
  assert.equal(S.assessGoldTrade(q,now).net,18000);
  for(const edit of [{period:'2026-10'},{period:'2026-13'},{period:'2026-02'},{unit:'USD'},{imports_m_thb:null},{proxy:false}])assert.equal(S.assessGoldTrade({...q,...edit},now).available,false);
});
test('foreign flow combines only matching dates and marks partial coverage',()=>{
  const q={stocks:{net_m_thb:-500,date:'2026-10-09',unit:'million_THB'},bonds:{net_m_thb:200,date:'2026-10-09',unit:'million_THB'}};
  assert.equal(S.assessForeign(q,now).net,-300);
  const partial=S.assessForeign({...q,bonds:{...q.bonds,date:'2026-10-08'}},now);
  assert.equal(partial.net,-500);assert.equal(partial.coverage,.5);
  assert.equal(S.assessForeign({bonds:q.bonds},now).included,'bonds');
  assert.equal(S.assessForeign({stocks:{...q.stocks,net_m_thb:null}},now).available,false);
});
test('manual scenarios are labelled, bounded and zero remains usable',()=>{
  const o={...complete,dxy:{value:0,manual:true}};
  const a=S.composite(o,'medium',now);assert.equal(a.scenario,true);assert.equal(a.count,6);
  assert.equal(a.rows[0].contribution,0);assert.ok(a.score<=100&&a.score>=-100);
});
