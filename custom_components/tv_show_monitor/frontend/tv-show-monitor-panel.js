const DOMAIN = "tv_show_monitor";

class TVShowMonitorPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
  }

  set hass(value) {
    this._hass = value;
    this._render();
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

  _render() {
    if (!this._hass) return;

    const shows = Object.entries(this._hass.states)
      .filter(([, state]) => state.attributes?.tvmaze_show_id !== undefined)
      .map(([entityId, state]) => this._showFromState(entityId, state));

    shows.sort((a, b) => this._sortValue(a) - this._sortValue(b) || a.name.localeCompare(b.name));

    const today = shows.filter((show) => show.group === "today");
    const upcoming = shows.filter((show) => show.group === "upcoming");
    const unscheduled = shows.filter((show) => show.group === "unscheduled");
    const ended = shows.filter((show) => show.group === "ended");

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="page">
        <header>
          <h1>TV Show Monitor</h1>
          <p>See what is coming up, when it airs, and where to watch it.</p>
        </header>
        ${shows.length === 0 ? this._emptyState() : ""}
        ${this._section("Today", today)}
        ${this._section("Coming up", upcoming)}
        ${this._section("No episode scheduled", unscheduled)}
        ${this._section("Ended", ended)}
      </div>
    `;

    this.shadowRoot.querySelectorAll("[data-entity-id]").forEach((element) => {
      element.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            bubbles: true,
            composed: true,
            detail: { entityId: element.dataset.entityId },
          })
        );
      });
    });
  }

  _showFromState(entityId, state) {
    const attr = state.attributes || {};
    const airing = this._airingDate(attr);
    const today = new Date();
    const localDate = airing ? this._dateKey(airing) : attr.air_date || null;
    const todayKey = this._dateKey(today);
    const hasEpisode = attr.next_episode_found === true;
    let group = "unscheduled";
    if (state.state === "Ended" || attr.show_status === "Ended") group = "ended";
    else if (hasEpisode && localDate === todayKey) group = "today";
    else if (hasEpisode) group = "upcoming";

    return {
      entityId,
      state,
      attr,
      airing,
      group,
      name: attr.show_name || state.attributes.friendly_name || entityId,
      hasEpisode,
    };
  }

  _section(title, shows) {
    if (!shows.length) return "";
    return `
      <section>
        <h2>${this._escape(title)}</h2>
        <div class="grid">${shows.map((show) => this._card(show)).join("")}</div>
      </section>
    `;
  }

  _card(show) {
    const { attr, airing, hasEpisode } = show;
    const picture = this._safeUrl(attr.entity_picture);
    const channel = attr.web_channel || attr.network;
    const episodeCode = attr.episode_code || "";
    const episodeName = attr.episode_name || "";
    const titleLine = hasEpisode
      ? [episodeCode, episodeName].filter(Boolean).join(" · ") || "Next episode"
      : this._noEpisodeText(attr.show_status, show.state.state);
    const when = hasEpisode ? this._friendlyAiring(airing, attr) : this._normalSchedule(attr);
    const finalEpisode = show.group === "ended" && attr.final_episode_code
      ? `Final episode: ${attr.final_episode_code}${attr.final_episode_name ? ` · ${attr.final_episode_name}` : ""}`
      : "";

    return `
      <article class="card" data-entity-id="${this._escapeAttr(show.entityId)}" tabindex="0" role="button" aria-label="Open ${this._escapeAttr(show.name)} details">
        <div class="poster-wrap">
          ${picture ? `<img class="poster" src="${this._escapeAttr(picture)}" alt="" loading="lazy">` : `<div class="poster placeholder">TV</div>`}
        </div>
        <div class="content">
          <div class="show-name">${this._escape(show.name)}</div>
          <div class="episode">${this._escape(titleLine)}</div>
          ${when ? `<div class="detail">${this._escape(when)}</div>` : ""}
          ${channel ? `<div class="detail">${this._escape(channel)}</div>` : ""}
          ${finalEpisode ? `<div class="detail muted">${this._escape(finalEpisode)}</div>` : ""}
          ${attr.runtime ? `<div class="detail muted">${this._escape(String(attr.runtime))} min</div>` : ""}
        </div>
      </article>
    `;
  }

  _friendlyAiring(airing, attr) {
    if (airing) {
      const locale = this._hass.locale?.language || navigator.language;
      const date = new Intl.DateTimeFormat(locale, {
        weekday: "short",
        day: "numeric",
        month: "short",
      }).format(airing);
      const time = new Intl.DateTimeFormat(locale, {
        hour: "numeric",
        minute: "2-digit",
      }).format(airing);
      return `${date} · ${time}`;
    }
    return [attr.air_date, attr.air_time].filter(Boolean).join(" · ");
  }

  _normalSchedule(attr) {
    if (!attr.schedule_days?.length && !attr.schedule_time) return "";
    return [attr.schedule_days?.join(", "), attr.schedule_time].filter(Boolean).join(" · ");
  }

  _noEpisodeText(status, state) {
    if (status === "Ended" || state === "Ended") return "No more episodes scheduled";
    if (status === "In Development") return "In development";
    if (status === "To Be Determined") return "Schedule to be confirmed";
    return "No upcoming episode yet";
  }

  _airingDate(attr) {
    if (!attr.air_stamp) return null;
    const value = new Date(attr.air_stamp);
    return Number.isNaN(value.getTime()) ? null : value;
  }

  _dateKey(value) {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  _sortValue(show) {
    if (show.airing) return show.airing.getTime();
    if (show.group === "unscheduled") return Number.MAX_SAFE_INTEGER - 1;
    return Number.MAX_SAFE_INTEGER;
  }

  _emptyState() {
    return `<div class="empty"><strong>No shows yet.</strong><span>Add shows from Settings → Devices & services → TV Show Monitor.</span></div>`;
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
      .page { max-width: 1100px; margin: 0 auto; padding: 24px 20px 48px; box-sizing: border-box; }
      header { margin-bottom: 28px; }
      h1 { margin: 0 0 6px; font-size: 28px; font-weight: 500; }
      header p { margin: 0; color: var(--secondary-text-color); font-size: 15px; }
      section { margin-top: 28px; }
      h2 { font-size: 18px; font-weight: 500; margin: 0 0 12px; }
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
      @media (max-width: 520px) {
        .page { padding: 18px 12px 36px; }
        .grid { grid-template-columns: 1fr; }
        .card { min-height: 135px; }
        .poster-wrap { width: 90px; flex-basis: 90px; }
        .poster { min-height: 135px; }
      }
    `;
  }
}

if (!customElements.get("tv-show-monitor-panel")) {
  customElements.define("tv-show-monitor-panel", TVShowMonitorPanel);
}
