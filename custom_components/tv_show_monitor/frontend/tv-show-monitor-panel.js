const DOMAIN = "tv_show_monitor";

class TVShowMonitorPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._initialized = false;
    this._manageOpen = false;
    this._manageData = null;
    this._manageBusy = false;
    this._manageError = "";
    this._manageWarning = "";
    this._searchQuery = "";
    this._searchResults = null;
    this._pendingRemoveId = null;
  }

  set hass(value) {
    this._hass = value;
    if (!this._initialized) this._renderShell();
    this._renderContent();
    this._syncAdminControls();
  }

  get hass() {
    return this._hass;
  }

  set panel(value) {
    this._panel = value;
  }

  set narrow(value) {
    this._narrow = value;
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="page">
        <header>
          <div class="header-copy">
            <h1>TV Show Monitor</h1>
            <p>See what is coming up, when it airs, and where to watch it.</p>
          </div>
          <button id="manage-shows" class="manage-button" type="button" hidden>Manage shows</button>
        </header>
        <div id="content"></div>
      </div>
      <div id="dialog-host"></div>
    `;
    this.shadowRoot.querySelector("#manage-shows").addEventListener("click", () => this._openManage());
    this._initialized = true;
  }

  _renderContent() {
    if (!this._hass || !this._initialized) return;

    const shows = Object.entries(this._hass.states)
      .filter(([, state]) => state.attributes?.tv_show_monitor_entity === true)
      .map(([entityId, state]) => this._showFromState(entityId, state));

    shows.sort((a, b) => this._sortValue(a) - this._sortValue(b) || a.name.localeCompare(b.name));

    const today = shows.filter((show) => show.group === "today");
    const upcoming = shows.filter((show) => show.group === "upcoming");
    const recent = shows
      .map((show) => this._recentFromShow(show))
      .filter((show) => show !== null)
      .sort((a, b) => b.airing.getTime() - a.airing.getTime() || a.name.localeCompare(b.name));
    const unscheduled = shows.filter((show) => show.group === "unscheduled");
    const ended = shows.filter((show) => show.group === "ended");

    const content = this.shadowRoot.querySelector("#content");
    content.innerHTML = `
      ${shows.length === 0 ? this._emptyState() : ""}
      ${this._section("Today", today)}
      ${this._section("Coming up", upcoming)}
      ${this._section("Recent", recent)}
      ${this._section("No episode scheduled", unscheduled)}
      ${this._section("Ended", ended)}
    `;

    content.querySelectorAll("[data-entity-id]").forEach((element) => {
      const openDetails = () => {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            bubbles: true,
            composed: true,
            detail: { entityId: element.dataset.entityId },
          })
        );
      };

      element.addEventListener("click", openDetails);
      element.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        openDetails();
      });
    });
  }

  _syncAdminControls() {
    if (!this._initialized) return;
    const isAdmin = this._hass?.user?.is_admin === true;
    this.shadowRoot.querySelector("#manage-shows").hidden = !isAdmin;
    if (!isAdmin && this._manageOpen) this._closeManage();
  }

  async _openManage() {
    if (this._hass?.user?.is_admin !== true) return;
    this._manageOpen = true;
    this._manageData = null;
    this._manageBusy = true;
    this._manageError = "";
    this._manageWarning = "";
    this._searchQuery = "";
    this._searchResults = null;
    this._pendingRemoveId = null;
    this._renderManage();

    try {
      this._manageData = await this._hass.callWS({ type: `${DOMAIN}/config` });
    } catch (error) {
      this._manageError = this._errorText(error);
    } finally {
      this._manageBusy = false;
      if (this._manageOpen) this._renderManage();
    }
  }

  _closeManage() {
    this._manageOpen = false;
    this._manageData = null;
    this._manageBusy = false;
    this._manageError = "";
    this._manageWarning = "";
    this._searchResults = null;
    this._pendingRemoveId = null;
    const host = this.shadowRoot.querySelector("#dialog-host");
    if (host) host.innerHTML = "";
  }

  _renderManage() {
    const host = this.shadowRoot.querySelector("#dialog-host");
    if (!host || !this._manageOpen) return;

    host.innerHTML = `
      <div class="dialog-backdrop" id="manage-backdrop">
        <div class="manage-dialog" role="dialog" aria-modal="true" aria-labelledby="manage-title">
          <div class="dialog-header">
            <div>
              <h2 id="manage-title">Manage shows</h2>
              <p>Add or remove followed shows without leaving the viewer.</p>
            </div>
            <button id="close-manage" class="icon-button" type="button" aria-label="Close">×</button>
          </div>
          <div class="dialog-body">
            ${this._manageError ? `<div class="notice error">${this._escape(this._manageError)}</div>` : ""}
            ${this._manageWarning ? `<div class="notice warning">${this._escape(this._manageWarning)}</div>` : ""}
            ${this._manageData ? this._manageBody() : `<div class="loading">${this._manageBusy ? "Loading followed shows…" : "Unable to load followed shows."}</div>`}
          </div>
        </div>
      </div>
    `;

    const backdrop = host.querySelector("#manage-backdrop");
    host.querySelector("#close-manage").addEventListener("click", () => this._closeManage());
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this._closeManage();
    });
    backdrop.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this._closeManage();
    });

    const searchForm = host.querySelector("#show-search-form");
    if (searchForm) searchForm.addEventListener("submit", (event) => this._searchShows(event));

    host.querySelectorAll("[data-remove-id]").forEach((button) => {
      button.addEventListener("click", () => {
        this._pendingRemoveId = Number(button.dataset.removeId);
        this._manageError = "";
        this._renderManage();
      });
    });
    host.querySelectorAll("[data-cancel-remove]").forEach((button) => {
      button.addEventListener("click", () => {
        this._pendingRemoveId = null;
        this._renderManage();
      });
    });
    host.querySelectorAll("[data-confirm-remove]").forEach((button) => {
      button.addEventListener("click", () => this._removeShow(Number(button.dataset.confirmRemove)));
    });
    host.querySelectorAll("[data-add-id]").forEach((button) => {
      button.addEventListener("click", () => this._addShow(Number(button.dataset.addId)));
    });
  }

  _manageBody() {
    const data = this._manageData;
    const shows = data.shows || [];
    const atLimit = shows.length >= data.max_shows;
    return `
      <section class="manage-section">
        <div class="manage-section-heading">
          <h3>Followed shows</h3>
          <span>${shows.length} / ${data.max_shows}</span>
        </div>
        ${shows.length ? `<div class="manage-list">${shows.map((show) => this._manageShowRow(show)).join("")}</div>` : `<div class="inline-empty">No shows are currently being monitored.</div>`}
      </section>
      <section class="manage-section">
        <h3>Add a show</h3>
        <form id="show-search-form" class="search-form">
          <input id="show-search" type="search" maxlength="100" autocomplete="off" placeholder="Search TVmaze by show title" value="${this._escapeAttr(this._searchQuery)}" ${this._manageBusy || atLimit ? "disabled" : ""}>
          <button class="primary-button" type="submit" ${this._manageBusy || atLimit ? "disabled" : ""}>${this._manageBusy ? "Working…" : "Search"}</button>
        </form>
        ${atLimit ? `<div class="helper">You have reached the ${data.max_shows}-show limit.</div>` : ""}
        ${this._searchResults === null ? "" : this._searchResultsMarkup()}
      </section>
    `;
  }

  _manageShowRow(show) {
    const confirming = this._pendingRemoveId === Number(show.tvmaze_id);
    const entered = show.entered_name && show.entered_name !== show.canonical_name
      ? `<span class="row-meta">Matched from “${this._escape(show.entered_name)}”</span>`
      : "";
    if (confirming) {
      return `
        <div class="manage-row confirm-row">
          <div class="row-copy">
            <strong>Remove ${this._escape(show.canonical_name)}?</strong>
            <span class="row-meta">Its TV Show Monitor sensor and device will be removed on reload.</span>
          </div>
          <div class="row-actions">
            <button class="secondary-button" type="button" data-cancel-remove ${this._manageBusy ? "disabled" : ""}>Cancel</button>
            <button class="danger-button" type="button" data-confirm-remove="${this._escapeAttr(show.tvmaze_id)}" ${this._manageBusy ? "disabled" : ""}>Remove</button>
          </div>
        </div>
      `;
    }
    return `
      <div class="manage-row">
        <div class="row-copy">
          <strong>${this._escape(show.canonical_name)}</strong>
          ${entered}
        </div>
        <button class="text-button danger-text" type="button" data-remove-id="${this._escapeAttr(show.tvmaze_id)}" ${this._manageBusy ? "disabled" : ""}>Remove</button>
      </div>
    `;
  }

  _searchResultsMarkup() {
    if (!this._searchResults.length) {
      return `<div class="inline-empty search-empty">No matching TVmaze shows found.</div>`;
    }
    return `<div class="search-results">${this._searchResults.map((candidate) => this._candidateRow(candidate)).join("")}</div>`;
  }

  _candidateRow(candidate) {
    const details = [
      candidate.premiered ? String(candidate.premiered).slice(0, 4) : null,
      candidate.country,
      candidate.network,
      candidate.status,
    ].filter(Boolean).join(" · ");
    const alreadyAdded = candidate.already_added === true;
    return `
      <div class="candidate-row">
        <div class="row-copy">
          <strong>${this._escape(candidate.name)}</strong>
          ${details ? `<span class="row-meta">${this._escape(details)}</span>` : ""}
        </div>
        <button class="${alreadyAdded ? "secondary-button" : "primary-button"}" type="button" data-add-id="${this._escapeAttr(candidate.tvmaze_id)}" ${alreadyAdded || this._manageBusy ? "disabled" : ""}>${alreadyAdded ? "Added" : "Add"}</button>
      </div>
    `;
  }

  async _searchShows(event) {
    event.preventDefault();
    const input = this.shadowRoot.querySelector("#show-search");
    const query = input?.value?.trim() || "";
    if (!query || this._manageBusy) return;

    this._searchQuery = query;
    this._manageBusy = true;
    this._manageError = "";
    this._manageWarning = "";
    this._searchResults = null;
    this._renderManage();
    try {
      const result = await this._hass.callWS({ type: `${DOMAIN}/search`, query });
      this._searchQuery = result.query;
      this._searchResults = result.candidates || [];
    } catch (error) {
      this._manageError = this._errorText(error);
      this._searchResults = [];
    } finally {
      this._manageBusy = false;
      if (this._manageOpen) this._renderManage();
    }
  }

  async _addShow(tvmazeId) {
    if (this._manageBusy || !this._searchQuery) return;
    this._manageBusy = true;
    this._manageError = "";
    this._manageWarning = "";
    this._renderManage();
    try {
      const result = await this._hass.callWS({
        type: `${DOMAIN}/add`,
        query: this._searchQuery,
        tvmaze_id: tvmazeId,
      });
      this._manageData = result;
      this._searchQuery = "";
      this._searchResults = null;
      this._pendingRemoveId = null;
      if (result.reloaded === false) {
        this._manageWarning = "The show was saved, but Home Assistant could not reload TV Show Monitor. Reload the integration manually to apply the change.";
      }
    } catch (error) {
      this._manageError = this._errorText(error);
    } finally {
      this._manageBusy = false;
      if (this._manageOpen) this._renderManage();
    }
  }

  async _removeShow(tvmazeId) {
    if (this._manageBusy) return;
    this._manageBusy = true;
    this._manageError = "";
    this._manageWarning = "";
    this._renderManage();
    try {
      const result = await this._hass.callWS({ type: `${DOMAIN}/remove`, tvmaze_id: tvmazeId });
      this._manageData = result;
      this._pendingRemoveId = null;
      this._searchResults = null;
      if (result.reloaded === false) {
        this._manageWarning = "The removal was saved, but Home Assistant could not reload TV Show Monitor. Reload the integration manually to apply the change.";
      }
    } catch (error) {
      this._manageError = this._errorText(error);
    } finally {
      this._manageBusy = false;
      if (this._manageOpen) this._renderManage();
    }
  }

  _errorText(error) {
    if (typeof error?.message === "string" && error.message) return error.message;
    if (typeof error?.code === "string" && error.code) return error.code.replaceAll("_", " ");
    return "Something went wrong while updating TV Show Monitor.";
  }

  _showFromState(entityId, state) {
    const attr = state.attributes || {};
    const airing = this._airingDate(attr);
    const now = new Date();
    const localDate = airing ? this._dateKey(airing) : attr.air_date || null;
    const todayKey = this._dateKey(now);
    const hasEpisode = attr.next_episode_found === true;
    let group = "unscheduled";

    if (state.state === "Ended" || attr.show_status === "Ended") {
      group = "ended";
    } else if (hasEpisode && localDate === todayKey) {
      group = "today";
    } else if (hasEpisode && airing && airing < now) {
      group = "recent";
    } else if (hasEpisode && localDate && localDate < todayKey) {
      group = "recent";
    } else if (hasEpisode) {
      group = "upcoming";
    }

    return {
      entityId,
      state,
      attr,
      airing,
      group,
      name: attr.show_name || state.attributes.friendly_name || entityId,
      hasEpisode,
      recentEpisode: false,
    };
  }

  _recentFromShow(show) {
    const { attr } = show;
    if (attr.previous_episode_id === undefined || !attr.previous_air_stamp) return null;

    const airing = this._dateFromStamp(attr.previous_air_stamp);
    if (!airing) return null;

    const dayDifference = this._dayDifference(this._dateKey(new Date()), this._dateKey(airing));
    if (dayDifference !== 0 && dayDifference !== -1) return null;

    return {
      ...show,
      airing,
      group: "recent",
      hasEpisode: true,
      recentEpisode: true,
    };
  }

  _section(title, shows) {
    if (!shows.length) return "";
    return `
      <section class="viewer-section">
        <h2>${this._escape(title)}</h2>
        <div class="grid">${shows.map((show) => this._card(show)).join("")}</div>
      </section>
    `;
  }

  _card(show) {
    const { attr, airing, hasEpisode, recentEpisode } = show;
    const picture = this._safeUrl(attr.entity_picture);
    const channel = attr.web_channel || attr.network;
    const episodeCode = recentEpisode ? attr.previous_episode_code || "" : attr.episode_code || "";
    const episodeName = recentEpisode ? attr.previous_episode_name || "" : attr.episode_name || "";
    const titleLine = hasEpisode
      ? [episodeCode, episodeName].filter(Boolean).join(" · ") || (recentEpisode ? "Previous episode" : "Next episode")
      : this._noEpisodeText(attr.show_status, show.state.state);
    const whenAttr = recentEpisode
      ? { air_date: attr.previous_air_date, air_time: attr.previous_air_time }
      : attr;
    const when = hasEpisode ? this._friendlyAiring(airing, whenAttr) : "";
    const finalEpisode = show.group === "ended" && attr.final_episode_code
      ? `Final episode: ${attr.final_episode_code}${attr.final_episode_name ? ` · ${attr.final_episode_name}` : ""}`
      : "";
    const runtime = recentEpisode ? null : attr.runtime;

    return `
      <article class="card" data-entity-id="${this._escapeAttr(show.entityId)}" tabindex="0" role="button" aria-label="Open ${this._escapeAttr(show.name)} details">
        <div class="poster-wrap">
          ${picture ? `<img class="poster" src="${this._escapeAttr(picture)}" alt="" loading="lazy">` : `<div class="poster placeholder">TV</div>`}
        </div>
        <div class="content">
          <div class="show-name">${this._escape(show.name)}</div>
          <div class="episode">${this._escape(titleLine)}</div>
          ${when ? `<div class="detail">${when}</div>` : ""}
          ${channel ? `<div class="detail">${this._escape(channel)}</div>` : ""}
          ${finalEpisode ? `<div class="detail muted">${this._escape(finalEpisode)}</div>` : ""}
          ${runtime ? `<div class="detail muted">${this._escape(String(runtime))} min</div>` : ""}
        </div>
      </article>
    `;
  }

  _friendlyAiring(airing, attr) {
    if (!airing) {
      return this._escape([attr.air_date, attr.air_time].filter(Boolean).join(" · "));
    }

    const locale = this._hass.locale?.language || navigator.language;
    const options = this._timeZone() ? { timeZone: this._timeZone() } : {};
    const time = new Intl.DateTimeFormat(locale, {
      ...options,
      hour: "numeric",
      minute: "2-digit",
    }).format(airing);
    const todayKey = this._dateKey(new Date());
    const airingKey = this._dateKey(airing);
    const dayDifference = this._dayDifference(todayKey, airingKey);

    if (dayDifference === 0) {
      const suffix = airing <= new Date() ? `Aired at ${this._escape(time)}` : this._escape(time);
      return `<strong>Today</strong> · ${suffix}`;
    }
    if (dayDifference === 1) {
      return `<strong>Tomorrow</strong> · ${this._escape(time)}`;
    }
    if (dayDifference === -1) {
      return `<strong>Yesterday</strong> · ${this._escape(time)}`;
    }
    if (dayDifference < -1) {
      return `Aired ${Math.abs(dayDifference)} days ago · ${this._escape(time)}`;
    }

    const date = new Intl.DateTimeFormat(locale, {
      ...options,
      weekday: "short",
      day: "numeric",
      month: "short",
    }).format(airing);
    return `${this._escape(date)} · ${this._escape(time)}`;
  }

  _timeZone() {
    return this._hass?.config?.time_zone || undefined;
  }

  _dateKey(value) {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      ...(this._timeZone() ? { timeZone: this._timeZone() } : {}),
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    const parts = Object.fromEntries(
      formatter.formatToParts(value).map((part) => [part.type, part.value])
    );
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  _dayDifference(fromKey, toKey) {
    const [fromYear, fromMonth, fromDay] = fromKey.split("-").map(Number);
    const [toYear, toMonth, toDay] = toKey.split("-").map(Number);
    const fromDate = Date.UTC(fromYear, fromMonth - 1, fromDay);
    const toDate = Date.UTC(toYear, toMonth - 1, toDay);
    return Math.round((toDate - fromDate) / 86400000);
  }

  _noEpisodeText(status, state) {
    if (status === "Ended" || state === "Ended") return "No more episodes scheduled";
    if (status === "In Development") return "In development";
    if (status === "To Be Determined") return "Schedule to be confirmed";
    return "No upcoming episode yet";
  }

  _dateFromStamp(stamp) {
    if (!stamp) return null;
    const value = new Date(stamp);
    return Number.isNaN(value.getTime()) ? null : value;
  }

  _airingDate(attr) {
    return this._dateFromStamp(attr.air_stamp);
  }

  _sortValue(show) {
    if (show.airing) return show.airing.getTime();
    if (show.group === "unscheduled") return Number.MAX_SAFE_INTEGER - 1;
    return Number.MAX_SAFE_INTEGER;
  }

  _emptyState() {
    const guidance = this._hass?.user?.is_admin === true
      ? "Use Manage shows to add one."
      : "Ask a Home Assistant administrator to add a show.";
    return `<div class="empty"><strong>No shows yet.</strong><span>${this._escape(guidance)}</span></div>`;
  }

  _safeUrl(value) {
    if (!value) return null;
    try {
      const url = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_err) {
      return null;
    }
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _escapeAttr(value) {
    return this._escape(value);
  }

  _styles() {
    return `
      :host { display: block; min-height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); }
      * { box-sizing: border-box; }
      button, input { font: inherit; }
      button { color: inherit; }
      .page { max-width: 1100px; margin: 0 auto; padding: 24px 20px 48px; }
      header { margin-bottom: 28px; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
      .header-copy { min-width: 0; }
      h1 { margin: 0 0 6px; font-size: 28px; font-weight: 500; }
      header p { margin: 0; color: var(--secondary-text-color); font-size: 15px; }
      .manage-button, .primary-button, .secondary-button, .danger-button, .text-button, .icon-button { border: 0; cursor: pointer; }
      .manage-button { flex: 0 0 auto; padding: 9px 14px; border-radius: 10px; background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 600; }
      .manage-button[hidden] { display: none; }
      .viewer-section { margin-top: 28px; }
      .viewer-section h2 { font-size: 18px; font-weight: 500; margin: 0 0 12px; }
      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
      .card { display: flex; min-height: 150px; overflow: hidden; border-radius: 14px; background: var(--card-background-color); box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12)); cursor: pointer; outline: none; }
      .card:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
      .poster-wrap { width: 100px; flex: 0 0 100px; background: var(--secondary-background-color); }
      .poster { width: 100%; height: 100%; min-height: 150px; object-fit: cover; display: block; }
      .placeholder { display: grid; place-items: center; color: var(--secondary-text-color); font-size: 20px; }
      .content { padding: 14px 16px; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
      .show-name { font-size: 18px; font-weight: 600; line-height: 1.25; }
      .episode { font-size: 14px; line-height: 1.35; margin-bottom: 3px; }
      .detail { font-size: 14px; color: var(--primary-text-color); line-height: 1.35; }
      .muted { color: var(--secondary-text-color); }
      .empty { display: flex; flex-direction: column; gap: 4px; padding: 20px; border-radius: 12px; background: var(--card-background-color); }
      .empty span { color: var(--secondary-text-color); }
      .dialog-backdrop { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 20px; background: rgba(0, 0, 0, .48); }
      .manage-dialog { width: min(680px, 100%); max-height: min(760px, calc(100vh - 40px)); display: flex; flex-direction: column; overflow: hidden; border-radius: 16px; background: var(--card-background-color); box-shadow: 0 18px 60px rgba(0,0,0,.28); }
      .dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 20px 22px 16px; border-bottom: 1px solid var(--divider-color); }
      .dialog-header h2 { margin: 0 0 4px; font-size: 22px; font-weight: 600; }
      .dialog-header p { margin: 0; color: var(--secondary-text-color); font-size: 14px; }
      .icon-button { width: 36px; height: 36px; border-radius: 50%; background: transparent; font-size: 26px; line-height: 1; }
      .icon-button:hover { background: var(--secondary-background-color); }
      .dialog-body { min-height: 120px; padding: 20px 22px 24px; overflow-y: auto; }
      .loading, .inline-empty, .helper { color: var(--secondary-text-color); font-size: 14px; }
      .manage-section + .manage-section { margin-top: 24px; padding-top: 22px; border-top: 1px solid var(--divider-color); }
      .manage-section h3 { margin: 0 0 12px; font-size: 16px; font-weight: 600; }
      .manage-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
      .manage-section-heading span { color: var(--secondary-text-color); font-size: 13px; }
      .manage-list, .search-results { display: flex; flex-direction: column; gap: 8px; }
      .manage-row, .candidate-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 54px; padding: 10px 12px; border: 1px solid var(--divider-color); border-radius: 11px; }
      .confirm-row { align-items: flex-start; background: var(--secondary-background-color); }
      .row-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
      .row-copy strong { font-size: 14px; line-height: 1.3; }
      .row-meta { color: var(--secondary-text-color); font-size: 13px; line-height: 1.35; }
      .row-actions { display: flex; gap: 8px; flex: 0 0 auto; }
      .search-form { display: flex; gap: 8px; }
      .search-form input { min-width: 0; flex: 1 1 auto; height: 40px; padding: 0 11px; border: 1px solid var(--divider-color); border-radius: 9px; background: var(--primary-background-color); color: var(--primary-text-color); outline: none; }
      .search-form input:focus { border-color: var(--primary-color); box-shadow: 0 0 0 1px var(--primary-color); }
      .primary-button, .secondary-button, .danger-button { flex: 0 0 auto; min-height: 38px; padding: 8px 13px; border-radius: 9px; font-weight: 600; }
      .primary-button { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .secondary-button { background: var(--secondary-background-color); }
      .danger-button { background: var(--error-color); color: #fff; }
      .text-button { padding: 7px 4px; background: transparent; font-weight: 600; }
      .danger-text { color: var(--error-color); }
      button:disabled, input:disabled { opacity: .55; cursor: default; }
      .search-results, .search-empty, .helper { margin-top: 12px; }
      .notice { margin-bottom: 16px; padding: 10px 12px; border-radius: 9px; font-size: 14px; line-height: 1.4; background: var(--secondary-background-color); }
      .error { color: var(--error-color); }
      .warning { color: var(--warning-color, var(--primary-text-color)); }
      @media (max-width: 520px) {
        .page { padding: 18px 12px 36px; }
        header { align-items: stretch; flex-direction: column; gap: 14px; }
        .manage-button { align-self: flex-start; }
        .grid { grid-template-columns: 1fr; }
        .card { min-height: 135px; }
        .poster-wrap { width: 90px; flex-basis: 90px; }
        .poster { min-height: 135px; }
        .dialog-backdrop { padding: 0; place-items: end center; }
        .manage-dialog { width: 100%; max-height: 92vh; border-radius: 16px 16px 0 0; }
        .dialog-header, .dialog-body { padding-left: 16px; padding-right: 16px; }
        .manage-row, .candidate-row { align-items: flex-start; }
        .confirm-row { flex-direction: column; }
        .search-form { flex-direction: column; }
        .search-form .primary-button { align-self: flex-end; }
      }
    `;
  }
}

if (!customElements.get("tv-show-monitor-panel")) {
  customElements.define("tv-show-monitor-panel", TVShowMonitorPanel);
}
