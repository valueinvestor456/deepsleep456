const {test} = require('node:test');
const assert = require('node:assert/strict');
const {assess} = require('./oil-factor.js');
const now = Date.parse('2026-10-11T00:00:00Z');
const quote = {last:102, previous:100, date:'2026-10-09', previous_date:'2026-10-08'};
const auto = {mode:'auto', quote, weight:0.1, scale:2};
test('oil up lowers THB strength; oil down raises it', () => {
  assert.ok(Math.abs(assess(auto, now).contribution + 0.1) < 1e-12);
  assert.ok(Math.abs(assess({...auto, quote:{...quote,last:98}}, now).contribution - 0.1) < 1e-12);
});
test('unchanged oil is valid and contributes zero; weight zero disables its effect', () => {
  const flat = assess({...auto, quote:{...quote,last:100}}, now);
  assert.equal(flat.available, true);
  assert.ok(flat.contribution === 0);
  assert.ok(assess({...auto,weight:0}, now).contribution === 0);
});
test('extreme shocks are capped before weighting', () => {
  assert.equal(assess({...auto,quote:{...quote,last:150}}, now).signal, -3);
  assert.equal(assess({...auto,quote:{...quote,last:50}}, now).signal, 3);
});
test('missing, invalid and stale oil never adds a signal', () => {
  for (const q of [null, {...quote,last:null}, {...quote,last:0}, {...quote,last:-5},
      {...quote,last:Infinity}, {...quote,previous:''}, {...quote,date:'2026-09-01',previous_date:'2026-08-31'},
      {...quote,date:'2026-10-12'}, {...quote,date:'2026-02-30'}, {...quote,previous_date:quote.date},
      {...quote,previous_date:'2026-09-01'}]) {
    const result = assess({...auto,quote:q}, now);
    assert.equal(result.available,false);
    assert.equal(result.contribution,0);
  }
});
test('invalid weights and volatility do not contaminate the score', () => {
  for (const params of [{weight:-1},{weight:''},{weight:Infinity},{scale:0},{scale:-2},{scale:''}]) {
    const result = assess({...auto,...params},now);
    assert.equal(result.available,false);
    assert.equal(result.contribution,0);
  }
});
test('manual scenarios override automatic prices and work without a feed', () => {
  const manual = {mode:'manual',last:'98',previous:'100',quote:null,weight:0.1,scale:2};
  assert.ok(assess(manual,now).contribution > 0);
  assert.equal(assess({...manual,last:''},now).available,false);
  assert.equal(assess({...auto,mode:'manual',last:'98',previous:'100'},now).last,98);
});
test('finite inputs that overflow a contribution cannot leak into the score', () => {
  const result = assess({...auto,weight:Number.MAX_VALUE,quote:{...quote,last:50}},now);
  assert.equal(result.available,false);
  assert.equal(result.signal,0);
  assert.equal(result.contribution,0);
});
test('automatic change is recomputed from prices, never trusted from a stale pct field', () => {
  assert.ok(Math.abs(assess({...auto,quote:{...quote,pct:99}},now).pct - 2) < 1e-12);
});
