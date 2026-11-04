/** Deterministic Arcade engine. Every branch sees exactly the same world tape. */
export const ACTIONS = Object.freeze({
  auto: {label:'Autopilot', description:'Fill Pip, then Boba in arrival order. Fast, but Boba may get sealed packets.'},
  rescue: {label:'Save the chorus', description:'Give both workers live audio first. Boba receives only public packets.'},
  guard: {label:'Guard the secrets', description:'Pip takes sealed packets first. Boba handles only public traffic.'},
  boost: {label:'Spark jump', description:'Spend one charge for two extra Pip slots. Prioritize sealed packets.'},
});
const kinds = ['voice', 'private', 'bulk'];
const ttl = {voice:1, private:2, bulk:3};
const worth = {voice:4, private:6, bulk:1};
const ranges = ['voice','private','bulk','pip','boba'];

export function validateLevel(level){
  if(!level || typeof level.title!=='string' || !level.title.trim() || level.title.length>70 ||
      typeof level.brief!=='string' || !level.brief.trim() || level.brief.length>240 ||
      !Array.isArray(level.turns) || level.turns.length!==12){
    throw new Error('A level needs a title, brief, and exactly twelve turns.');
  }
  for(const row of level.turns){
    if(!row || ranges.some(key=>!Number.isInteger(row[key]) || row[key]<0 || row[key]>4) ||
       typeof row.event!=='string' || !row.event.trim() || row.event.length>100){
      throw new Error('Each turn needs bounded packet counts, worker capacities, and an event caption.');
    }
  }
  return level;
}

export function start(level){
  validateLevel(level);
  return {tick:0,queue:[],delivered:0,missed:0,leaks:0,charge:3,score:0,done:false,history:[],
          served:{voice:0,private:0,bulk:0}};
}

export function step(level,state,action){
  if(state.done) return state;
  if(!Object.hasOwn(ACTIONS,action)) throw new Error('Unknown rescue move.');
  const tick=state.tick;
  const turn=level.turns[tick];
  const queue=[...state.queue];
  for(const kind of kinds){
    for(let i=0;i<turn[kind];i++) queue.push({id:`${tick+1}-${kind}-${i+1}`,kind,deadline:tick+ttl[kind]});
  }
  const usingSpark=action==='boost' && state.charge>0;
  const priority=action==='rescue' ? {voice:0,private:1,bulk:2} : {private:0,voice:1,bulk:2};
  const moves=[];
  function process(pool,capacity){
    const eligible=queue.filter(packet=>pool==='pip' || action==='auto' || packet.kind!=='private');
    if(action!=='auto'){
      eligible.sort((a,b)=>priority[a.kind]-priority[b.kind] || a.deadline-b.deadline);
    }
    for(const packet of eligible.slice(0,capacity)){
      queue.splice(queue.indexOf(packet),1);
      moves.push({...packet,pool,leaked:pool==='boba' && packet.kind==='private'});
    }
  }
  process('pip',turn.pip+(usingSpark?2:0));
  process('boba',turn.boba);
  const done=tick+1===level.turns.length;
  const expired=queue.filter(packet=>done || packet.deadline<=tick);
  const pending=queue.filter(packet=>!done && packet.deadline>tick);
  const leaks=moves.filter(move=>move.leaked).length;
  const served={...state.served};
  for(const move of moves) served[move.kind]++;
  const score=state.score+moves.reduce((sum,move)=>sum+worth[move.kind],0)-2*expired.length-20*leaks;
  const row={tick:tick+1,action,event:turn.event,delivered:moves.length,missed:expired.length,leaks,
    queued:pending.length,score,charge:state.charge-Number(usingSpark),moves,expired};
  return {
    tick:tick+1,queue:pending,delivered:state.delivered+row.delivered,missed:state.missed+row.missed,
    leaks:state.leaks+row.leaks,charge:row.charge,score,done,served,history:[...state.history,row],
  };
}

export function replay(level,actions){
  return actions.reduce((state,action)=>step(level,state,action),start(level));
}
