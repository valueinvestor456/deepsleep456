const {test} = require('node:test');
const assert = require('node:assert/strict');
const {pressure,fundNet,assessYield} = require('./signal-board.js');
test('USD pressure direction differs between cost/yield factors and Thai inflows',()=>{
  for(const factor of ['dxy','us2','oil','gold']){assert.equal(pressure(factor,1),'up');assert.equal(pressure(factor,-1),'down');}
  for(const factor of ['foreign','account']){assert.equal(pressure(factor,1),'down');assert.equal(pressure(factor,-1),'up');}
});
test('missing data is not flat or a directional signal',()=>{
  for(const value of ['',null,undefined,NaN,Infinity,false,[]]) assert.equal(pressure('oil',value),'missing');
  assert.equal(pressure('oil',0),'flat');
});
test('fund-flow net requires both markets; zero is an explicit usable value',()=>{
  assert.equal(fundNet(-500,''),null);
  assert.equal(fundNet(-500,0),-500);
  assert.equal(fundNet(-500,800),300);
});
test('yield comparison uses basis points and validates date freshness',()=>{
  const now=Date.parse('2026-10-11T00:00:00Z');
  const quote={last:4.8,previous:4.75,date:'2026-10-09',previous_date:'2026-10-08'};
  const good=assessYield('auto',quote,'','',now);
  assert.equal(good.available,true); assert.ok(Math.abs(good.bps-5)<1e-10);
  for(const edit of [{date:'2026-09-01'},{date:'2026-10-12'},{previous_date:'2026-10-09'},{last:null}]) assert.equal(assessYield('auto',{...quote,...edit},'','',now).available,false);
  assert.equal(assessYield('manual',null,'4.7','4.8',now).available,true);
  assert.equal(assessYield('manual',null,'','4.8',now).available,false);
});
