(function(root, factory){
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.UsdOil = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function(){
  "use strict";
  var MAX_AGE_DAYS = 10;
  function numeric(value){
    if (value === null || value === undefined || typeof value === "boolean" ||
        (typeof value !== "number" && typeof value !== "string") ||
        String(value).trim() === "") return null;
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  function dateMs(value){
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    var n = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(n) && new Date(n).toISOString().slice(0,10) === value ? n : null;
  }
  function assess(input, now){
    now = now === undefined ? Date.now() : now;
    var manual = input.mode === "manual";
    var quote = input.quote || {};
    var last = numeric(manual ? input.last : quote.last);
    var previous = numeric(manual ? input.previous : quote.previous);
    var weight = numeric(input.weight), scale = numeric(input.scale);
    var result = {last:last, previous:previous, pct:null, signal:0, contribution:0,
      available:false, reason:"", manual:manual, date:quote.date, previousDate:quote.previous_date};
    function fail(reason){ result.reason = reason; result.signal = 0; result.contribution = 0; return result; }
    if (last === null || previous === null) return fail(manual ? "missing_manual" : "missing_auto");
    if (last <= 0 || previous <= 0) return fail("invalid_price");
    if (weight === null || weight < 0 || scale === null || scale <= 0) return fail("invalid_parameters");
    if (!manual){
      var currentDate = dateMs(quote.date), previousDate = dateMs(quote.previous_date);
      if (currentDate === null || previousDate === null || previousDate >= currentDate || currentDate > now)
        return fail("invalid_date");
      result.ageDays = (now - currentDate) / 86400000;
      if (result.ageDays > MAX_AGE_DAYS) return fail("stale");
      if (currentDate - previousDate > 7 * 86400000) return fail("date_gap");
    }
    result.pct = (last / previous - 1) * 100;
    if (!Number.isFinite(result.pct)) return fail("invalid_price");
    // Import-cost scenario: higher oil subtracts from THB strength.
    // This is a configurable assumption, not an estimated predictive beta.
    result.signal = Math.max(-3, Math.min(3, -result.pct / scale));
    result.contribution = weight * result.signal;
    if (!Number.isFinite(result.contribution)) return fail("invalid_parameters");
    result.available = true;
    return result;
  }
  return {assess:assess, maxAgeDays:MAX_AGE_DAYS};
});
