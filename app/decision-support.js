/* Compare explicit quotes in MYR. No listing estimate becomes a merchant offer. */
(function () {
  function moneyInput(value) {
    if (value === '' || value == null) return null;
    if (!/^\d+(?:\.\d{1,2})?$/.test(String(value).trim())) {
      throw new Error('Enter non-negative MYR amounts with at most two decimal places.');
    }
    const sen = Math.round(Number(value) * 100);
    if (!Number.isSafeInteger(sen)) throw new Error('Enter a valid MYR amount.');
    return sen;
  }

  function compareQuotes({ goal, currentOffer, tradeCredit, useCredit, repairCost, repairedOffer }) {
    if (goal === 'keep') {
      return {
        options: [], next: 'Keep using if it meets your needs',
        reason: 'Check functional issues separately. If exterior damage affects use, get an inspection and a repair quote before deciding.'
      };
    }
    const sale = moneyInput(currentOffer);
    const credit = moneyInput(tradeCredit);
    const repair = moneyInput(repairCost);
    const repaired = moneyInput(repairedOffer);
    const options = [];
    if (sale !== null) options.push({ label: 'Sell as-is', sen: sale });
    if (credit !== null && useCredit) options.push({ label: 'Trade in (usable credit)', sen: credit });
    if (repair !== null && repaired !== null) {
      options.push({ label: 'Repair then sell', sen: repaired - repair });
    }
    options.sort((a, b) => b.sen - a.sen);
    if (options.length < 2) return {
      options, next: 'Get comparable quotes',
      reason: 'Compare at least two complete options. Repair needs both a cost and a post-repair offer. Trade-in credit counts only if you plan to use it.'
    };
    const highest = options[0];
    if (highest.sen <= 0) return {
      options, next: 'Keep or get another quote',
      reason: 'None of the entered options returns a positive amount after the stated costs.'
    };
    if (highest.sen === options[1].sen) return {
      options, next: 'Compare the tied options',
      reason: 'Choose based on effort, timing, repair risk and whether trade-in credit is useful to you.'
    };
    return {
      options, next: highest.label,
      reason: 'This option has the highest net amount among the quotes you entered. Confirm the terms and get the phone inspected before accepting.'
    };
  }

  if (typeof module !== 'undefined') module.exports = { compareQuotes };
  else window.ReValueDecisionSupport = { compareQuotes };
}());
