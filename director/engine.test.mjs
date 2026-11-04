import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ACTIONS,replay,start,step,validateLevel} from './engine.mjs';

const sample={title:'Process test',brief:'A bounded example.',turns:Array.from({length:12},(_,i)=>({
  voice:2,private:1,bulk:1,pip:i===2||i===3?0:2,boba:i===8?0:i===2||i===3?3:2,event:'Synthetic test',
}))};

test('a fork from the same state is deterministic and immutable',()=>{
  const early=replay(sample,['guard','guard']);
  const snapshot=JSON.stringify(early);
  assert.deepEqual(step(sample,early,'boost'),step(sample,early,'boost'));
  assert.notDeepEqual(step(sample,early,'boost'),step(sample,early,'auto'));
  assert.equal(JSON.stringify(early),snapshot);
});

test('autopilot leaks in the outage and safe moves never dispatch sealed packets to backup',()=>{
  const early=replay(sample,['guard','guard']);
  assert.equal(step(sample,early,'auto').leaks,1);
  for(const id of ['rescue','guard','boost']) assert.equal(step(sample,early,id).leaks,0);
});

test('charge cannot go below zero and all offered packets end accounted for',()=>{
  const state=replay(sample,Array(12).fill('boost'));
  assert.equal(state.charge,0);
  assert.equal(state.done,true);
  assert.equal(state.delivered+state.missed,48);
  assert.equal(state.leaks,0);
  assert.equal(step(sample,state,'guard'),state);
});

test('invalid tape and actions fail closed',()=>{
  assert.throws(()=>validateLevel({...sample,turns:sample.turns.slice(1)}));
  assert.throws(()=>validateLevel({...sample,turns:sample.turns.map(row=>({...row,voice:500}))}));
  assert.throws(()=>step(sample,start(sample),'invented'));
});

test('published tape is playable and each route conserves arrivals',()=>{
  const tape=JSON.parse(readFileSync(new URL('./level.json',import.meta.url))).level;
  for(const key of Object.keys(ACTIONS)){
    const outcome=replay(tape,Array(12).fill(key));
    const offered=tape.turns.reduce((sum,row)=>sum+row.voice+row.private+row.bulk,0);
    assert.equal(outcome.delivered+outcome.missed,offered);
  }
});
