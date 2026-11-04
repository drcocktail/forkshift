import {readFileSync} from 'node:fs';
import {ACTIONS, replay} from './engine.mjs';

const {level, actions} = JSON.parse(readFileSync(0, 'utf8'));
if (!Array.isArray(actions) || actions.length > level.turns.length ||
    actions.some(action => !Object.hasOwn(ACTIONS, action)) ||
    actions.filter(action => action === 'boost').length > 3) {
  throw new Error('Invalid swarm route.');
}
const state = replay(level, actions);
const score = {delivered: state.delivered, leaks: state.leaks, dropped: state.missed,
  queued: state.queue.length, points: state.score, charge: state.charge};
const history = state.history.map(row => ({turn: row.tick, action: row.action, event: row.event,
  delivered: row.delivered, leaks: row.leaks, dropped: row.missed, queued: row.queued,
  charge: row.charge, leakedPackets: row.moves.filter(packet => packet.leaked).map(packet => packet.id),
  expiredPackets: row.expired.map(packet => packet.id)}));
const queue = state.queue.map(({id, kind, deadline}) => ({id, kind, expiresAfterTurn: deadline + 1}));
console.log(JSON.stringify({score, history, queue}));
