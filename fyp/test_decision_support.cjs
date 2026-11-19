const assert = require('node:assert/strict');
const { compareQuotes } = require('../app/decision-support.js');

const bids = { goal: 'sell', currentOffer: '400', tradeCredit: '650', repairCost: '150', repairedOffer: '750' };
assert.equal(compareQuotes(bids).next, 'Repair then sell');
assert.equal(compareQuotes({ ...bids, useCredit: true }).next, 'Trade in (usable credit)');
assert.equal(compareQuotes({ ...bids, repairCost: '350' }).next, 'Compare the tied options');
assert.equal(compareQuotes({ ...bids, repairCost: '360' }).next, 'Sell as-is');
assert.equal(compareQuotes({ goal: 'sell', currentOffer: '100' }).next, 'Get comparable quotes');
assert.equal(compareQuotes({ goal: 'keep' }).next, 'Keep using if it meets your needs');
assert.throws(() => compareQuotes({ goal: 'sell', currentOffer: '-1' }));
console.log('Quote decision unit checks passed.');
