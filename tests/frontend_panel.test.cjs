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
assert.equal(panel._recentNextFromShow(pastRunning), null,
  "stale cached episodes outside today/yesterday stay out of Recent");
const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);
const dateOnly = showState("No absolute time", yesterday.toISOString());
dateOnly.attributes.air_stamp = null;
dateOnly.attributes.air_date = panel._dateKey(yesterday);
const recentDateOnly = panel._showFromState("sensor.date_only", dateOnly);
assert.equal(panel._recentNextFromShow(recentDateOnly), recentDateOnly,
  "yesterday's cached episode without a timestamp appears in Recent");
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
async function checkSuccessfulAddClearsSearch() {
  const managePanel = new Panel();
  const listeners = {};
  const search = {
    value: "Doctor Who",
    addEventListener: (type, listener) => { listeners[type] = listener; },
  };
  const element = { scrollTop: 0, addEventListener: () => {} };
  const host = {
    innerHTML: "",
    querySelector: (selector) => selector === "#show-search" ? search : element,
    querySelectorAll: () => [],
  };
  managePanel.shadowRoot = { querySelector: () => host };
  managePanel._manageOpen = true;
  managePanel._manageData = { shows: [], max_shows: 50 };
  managePanel._searchQuery = search.value;
  managePanel._renderContent = () => {};
  managePanel._hass = {
    callWS: async () => ({ shows: [{ canonical_name: "Doctor Who", tvmaze_id: 2 }], max_shows: 50, reloaded: true }),
  };
  managePanel._renderManage();
  search.value = "Doctor";
  listeners.input();
  managePanel._renderManage();
  assert.equal(managePanel._searchQuery, "Doctor", "unsubmitted edits survive a dialog rebuild");
  await managePanel._addShow(2);
  assert.equal(managePanel._searchQuery, "", "successful add clears the submitted query");
  assert.match(host.innerHTML, /placeholder="Search TVmaze by show title" value=""/);
}


function checkViewerFiltersAndStaleness() {
  const viewer = new Panel();
  viewer._hass = { config: { time_zone: "Europe/Dublin" }, locale: { language: "en-IE" } };
  const upcoming = viewer._showFromState(
    "sensor.test", showState("Severance", new Date(Date.now() + 2 * 86400000).toISOString())
  );
  const unscheduled = viewer._showFromState("sensor.none", showState("Other", null));
  viewer._viewerFilter = "next7";
  assert.equal(viewer._viewerIncludes(upcoming), true, "next seven days includes upcoming releases");
  assert.equal(viewer._viewerIncludes(unscheduled), false, "next seven days excludes undated shows");
  viewer._viewerFilter = "unscheduled";
  assert.equal(viewer._viewerIncludes(unscheduled), true, "unscheduled filter includes unscheduled shows");
  assert.equal(viewer._viewerIncludes(upcoming), false);
  viewer._viewerFilter = "all";
  viewer._viewerQuery = "SEVER";
  assert.equal(viewer._viewerIncludes(upcoming), true, "text search is case insensitive");
  assert.equal(viewer._viewerIncludes(unscheduled), false);

  upcoming.attr.poll_interval_hours = 24;
  upcoming.attr.last_successful_update = new Date(Date.now() - 72 * 3600000).toISOString();
  upcoming.attr.last_attempt_successful = true;
  assert.match(viewer._freshnessWarning(upcoming), /outdated/i);
  upcoming.attr.last_successful_update = new Date().toISOString();
  assert.equal(viewer._freshnessWarning(upcoming), "", "recent data has no warning");
  upcoming.attr.last_attempt_successful = false;
  assert.match(viewer._freshnessWarning(upcoming), /update failed/i);
  unscheduled.attr.poll_interval_hours = 24;
  unscheduled.attr.show_status = "Ended";
  unscheduled.attr.last_successful_update = new Date(Date.now() - 90 * 86400000).toISOString();
  unscheduled.attr.last_attempt_successful = true;
  assert.equal(viewer._freshnessWarning(unscheduled), "",
    "ended shows are not flagged for intentionally infrequent checks");
}

async function checkViewerRematch() {
  const editor = new Panel();
  editor._manageOpen = true;
  editor._manageData = { shows: [{ canonical_name: "Old", tvmaze_id: 216 }], max_shows: 50 };
  editor._changeMatchId = 216;
  editor._searchQuery = "New";
  editor._renderManage = () => {};
  editor._renderContent = () => {};
  const requests = [];
  editor._hass = { callWS: async (payload) => {
    requests.push(payload);
    return { shows: [{ canonical_name: "New", tvmaze_id: 4 }], max_shows: 50, reloaded: true };
  } };
  assert.match(editor._manageShowRow(editor._manageData.shows[0]), /data-change-match-id="216"/);
  editor._searchResults = [{ tvmaze_id: 4, name: "New", already_added: false }];
  assert.match(editor._candidateRow(editor._searchResults[0]), /Use match/);
  assert.match(editor._candidateRow({ tvmaze_id: 216, name: "Old", already_added: true }), /Current/);
  await editor._changeShowMatch(4);
  assert.equal(requests[0].type, "tv_show_monitor/change_match");
  assert.equal(requests[0].old_tvmaze_id, 216);
  assert.equal(requests[0].tvmaze_id, 4);
  assert.equal(editor._manageData.shows[0].tvmaze_id, 4);
  assert.equal(editor._changeMatchId, null);
  assert.equal(editor._searchQuery, "");
  assert.equal(editor._manageBusy, false);
}

checkViewerFiltersAndStaleness();
Promise.resolve()
  .then(checkViewerRematch)
  .then(checkManageCloseInvalidatesPendingResponses)
  .then(checkSuccessfulAddClearsSearch)
  .then(() => console.log("Async management lifecycle checks passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
