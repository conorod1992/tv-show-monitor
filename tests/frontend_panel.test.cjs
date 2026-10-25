"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(
  "custom_components/tv_show_monitor/frontend/tv-show-monitor-panel.js", "utf8"
);
let Panel;
class Element {
  attachShadow() {
    this.shadowRoot = { innerHTML: "" };
  }
}
const context = {
  HTMLElement: Element,
  customElements: {
    get: () => undefined,
    define: (_name, ctor) => { Panel = ctor; },
  },
  navigator: { language: "en-IE" },
  Intl,
  Date,
};
vm.runInNewContext(source, context, { filename: "tv-show-monitor-panel.js" });
assert.ok(Panel, "panel registered as custom element");
const panel = new Panel();
panel._hass = { config: { time_zone: "Europe/Dublin" }, locale: { language: "en-IE" } };

function showState(name, stamp, status = "Running") {
  return {
    state: stamp ? stamp.slice(0, 10) : status,
    attributes: {
      tv_show_monitor_entity: true,
      show_name: name,
      show_status: status,
      next_episode_found: Boolean(stamp),
      episode_id: 123,
      air_stamp: stamp,
      air_date: stamp?.slice(0, 10),
    },
  };
}
const future = new Date(Date.now() + 5 * 86400000).toISOString();
const past = new Date(Date.now() - 5 * 86400000).toISOString();
const futureEnded = panel._showFromState("sensor.future", showState("Finale", future, "Ended"));
assert.equal(futureEnded.group, "upcoming", "upcoming finale remains scheduled");
const pastRunning = panel._showFromState("sensor.past", showState("Delayed poll", past));
assert.equal(pastRunning.group, "recent", "elapsed cached episode is recognised");
const ended = panel._showFromState("sensor.ended", showState("Finished", null, "Ended"));
assert.equal(ended.group, "ended", "ended without next episode stays ended");
const first = panel._dateFormatter("key");
assert.equal(first, panel._dateFormatter("key"), "same formatter reused");
panel._hass.config.time_zone = "UTC";
assert.notEqual(first, panel._dateFormatter("key"), "timezone change invalidates formatter key");

const renders = [];
panel._renderContent = () => renders.push("render");
panel._syncAdminControls = () => {};
panel._initialized = true;
const monitored = showState("Tracked", future);
const hass = {
  config: { time_zone: "Europe/Dublin" },
  locale: { language: "en-IE" },
  states: {
    "sensor.tracked": monitored,
    "sensor.unrelated": { state: "off", attributes: {} },
  },
};
panel.hass = hass;
assert.equal(renders.length, 1, "initial render");
panel.hass = {
  ...hass,
  states: { ...hass.states, "sensor.unrelated": { state: "on", attributes: {} } },
};
assert.equal(renders.length, 1, "unrelated state change skips rerender");
panel.hass = {
  ...hass,
  states: { ...hass.states, "sensor.tracked": { ...monitored } },
};
assert.equal(renders.length, 2, "show state changes rerender");
panel.hass = {
  ...hass,
  locale: { language: "fr-FR" },
  states: hass.states,
};
assert.equal(renders.length, 3, "locale change rerenders");
console.log("Frontend behaviour checks passed");


async function checkManageCloseInvalidatesPendingResponses() {
  const managePanel = new Panel();
  let resolveFirst;
  let resolveSecond;
  let calls = 0;
  managePanel._hass = {
    user: { is_admin: true },
    callWS: () => new Promise((resolve) => {
      if (++calls === 1) resolveFirst = resolve;
      else resolveSecond = resolve;
    }),
  };
  managePanel._renderManage = () => {};
  managePanel._renderContent = () => {};
  managePanel.shadowRoot = { querySelector: () => null };
  const first = managePanel._openManage();
  managePanel._closeManage();
  const second = managePanel._openManage();
  resolveSecond({ shows: [{ canonical_name: "New", tvmaze_id: 2 }] });
  await second;
  resolveFirst({ shows: [{ canonical_name: "Old", tvmaze_id: 1 }] });
  await first;
  assert.equal(managePanel._manageData.shows[0].tvmaze_id, 2,
    "closed dialog's pending request cannot overwrite reopened dialog");
  assert.equal(managePanel._manageBusy, false);
}
checkManageCloseInvalidatesPendingResponses()
  .then(() => console.log("Async management lifecycle checks passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
