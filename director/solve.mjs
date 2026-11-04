/** Find the best clean timeline for the published tape and compare with Autopilot. */
import {readFileSync} from 'node:fs';
import {ACTIONS, replay, start, step} from './engine.mjs';

const tape=JSON.parse(readFileSync(new URL('./level.json',import.meta.url)));
const level=tape.level;
const seen=new Map();
function best(state){
  if(state.done) return {score:0,actions:[]};
  const key=JSON.stringify([state.tick,state.charge,state.queue.map(packet=>packet.id)]);
  if(seen.has(key)) return seen.get(key);
  let pick=null;
  for(const id of ['rescue','guard','boost']){
    if(id==='boost' && !state.charge) continue;
    const next=step(level,state,id);
    const tail=best(next);
    const score=next.score-state.score+tail.score;
    if(!pick || score>pick.score) pick={score,actions:[id,...tail.actions]};
  }
  seen.set(key,pick);
  return pick;
}
const plan=best(start(level));
const auto=replay(level,level.turns.map(()=> 'auto'));
const clean=replay(level,plan.actions);
function summarize(state){
  return {actions:state.history.map(row=>row.action), delivered:state.delivered, missed:state.missed,
    leaks:state.leaks, charge:state.charge, score:state.score,
    events:state.history.map(({tick,action,delivered,missed,leaks,queued,event})=>({tick,action,delivered,missed,leaks,queued,event}))};
}
console.log(JSON.stringify({
  level:level.title,origin:tape.origin,model:tape.metadata.model,
  actions:Object.keys(ACTIONS), explored_states:seen.size,
  autopilot:summarize(auto), best_clean:summarize(clean),
},null,2));
