# TV Show Monitor

TV Show Monitor is a UI-configured Home Assistant custom integration that checks
[TVmaze](https://www.tvmaze.com/) for the next scheduled episode of each show you
follow. It creates one sensor and one Home Assistant device per TV show.

## Screenshots

> Screenshots will be added after the first release.

- Configuration flow — placeholder
- Show sensor and attributes — placeholder
- Options flow — placeholder

## Installation

### HACS

1. Open HACS, select **Integrations**, then open the three-dot menu.
2. Choose **Custom repositories**.
3. Add `https://github.com/conorod1992/tv-show-monitor` as an **Integration**.
4. Search for **TV Show Monitor**, install it, and restart Home Assistant.

### Manual

Copy `custom_components/tv_show_monitor` into the `custom_components` directory
inside your Home Assistant configuration directory, then restart Home Assistant.

## Setup and title matching

Go to **Settings → Devices & services → Add integration**, search for **TV Show
Monitor**, and enter one show per line. Whitespace and blank lines are ignored;
exact duplicate entries are removed case-insensitively. Up to 50 shows are allowed.

During setup, every entered title is searched using TVmaze's show-search API. A
single result, or one clear exact-title result among differently named results, is
selected automatically. If TVmaze returns multiple plausible same-title matches,
TV Show Monitor asks you to choose and shows useful metadata such as premiere year,
country, network or web channel, and status. Setup is rejected in full if any title
cannot be resolved or two titles resolve to the same show. Routine polling uses the
saved TVmaze ID, not the title.

Open the integration's **Configure** dialog to manage shows through dedicated
**Add show**, **Remove show**, and **Change TVmaze match** flows. Adding a show only
searches the new title; removing a show performs no title lookup. Changing a match
lets you search again and explicitly select the correct TVmaze result. Polling
interval changes are handled separately and never rematch shows.

## Sensor states

Each entity is naturally named from the canonical TVmaze title, for example
`sensor.severance_next_episode`.

- A scheduled episode: its local calendar date in ISO format, such as `2026-10-12`.
- A successful check with no scheduled episode: `No next episode found`.
- No successful check yet: unavailable.

The sensor state intentionally remains simple and stable. Richer programme and
schedule information is exposed as attributes so existing automations do not need
to change. When TVmaze provides show artwork, the sensor also uses the show's poster
as its Home Assistant entity picture. The smaller TVmaze image is preferred to keep
dashboard image loads lightweight, with the original image used only as a fallback.

Template example:

```jinja2
{{ states('sensor.severance_next_episode') }}
```

## Attributes

When available, each sensor now exposes:

- TVmaze show ID and current show status;
- next episode ID/name, season, episode number and `S02E04`-style code;
- next air date/time, ISO air stamp, `next_airing`, runtime and episode URL;
- `days_until`, calculated from Home Assistant's current local date;
- previous episode ID/name, season, episode number/code and air date/time;
- show URL and refresh diagnostics.

A valid no-episode result includes `next_episode_found: false`. Every result reports
the latest attempt and whether it succeeded; a failed attempt also exposes a short,
safe `last_error`. Last-good show status, artwork, previous episode and next episode
data are preserved through transient refresh failures and Home Assistant restarts.

## Schedule change events

After the integration has established a successful baseline, meaningful changes to
the next-episode schedule fire a `tv_show_monitor_schedule_changed` Home Assistant
event. Initial setup does not emit an event simply because a show already has an
upcoming episode.

`change_type` is one of:

- `scheduled` — a show with no known next episode gains one;
- `schedule_cleared` — a previously scheduled next episode disappears;
- `next_episode_changed` — TVmaze now identifies a different episode as next;
- `rescheduled` — the same episode ID has a different air date or air stamp.

Event data includes `tvmaze_show_id`, `show_name`, old/new episode IDs, old/new air
dates and old/new air stamps. This makes schedule-driven automations reliable
without having to infer the kind of change from sensor state transitions.

Example event trigger:

```yaml
triggers:
  - trigger: event
    event_type: tv_show_monitor_schedule_changed
    event_data:
      tvmaze_show_id: 216
conditions: []
actions:
  - action: notify.notify
    data:
      title: TV schedule changed
      message: >-
        {{ trigger.event.data.show_name }}:
        {{ trigger.event.data.change_type }}
mode: single
```

## Polling and error preservation

The default interval is 24 hours. The options flow accepts 24-hour steps from 24
to 744 hours (for example 24, 48, 72, or 168). Standard Home Assistant entity
updates request a coordinated refresh for all shows.

Shows are fetched independently with a small concurrency limit to avoid request
bursts while preventing one slow request from serialising the entire refresh.
Each show's single TVmaze request includes its main programme information plus the
previous and next episode links when TVmaze has them. Transient timeouts, rate
limits, and common server-side failures are retried once.

A successful response with no future episode replaces any old episode with `No
next episode found`. A failed API request or invalid response retains the last
successful sensor value and its episode attributes, while recording failure
diagnostics. Last-good state is stored by Home Assistant and survives restarts.

## TVmaze attribution

Schedule, programme data and artwork are provided by [TVmaze](https://www.tvmaze.com/).
TV Show Monitor is not affiliated with or endorsed by TVmaze.

## Known limitations

- TVmaze only reports publicly scheduled future episodes.
- Show artwork is only available when TVmaze supplies an image for that show.
- `days_until` is based on TVmaze's published air date rather than the viewer's
  personal streaming availability.
- Polling intervals use whole 24-hour steps and cannot be shorter than one day.

## Troubleshooting

- If the wrong show is matched, open **Configure → Change TVmaze match** and choose
  the correct search result.
- If a sensor says `No next episode found`, TVmaze currently has no scheduled next
  episode. This is not an error; `show_status` may provide additional context.
- If `last_attempt_successful` is false, check Home Assistant logs and wait for the
  next poll; the previous good value remains in place.
- If a new sensor is unavailable, its first fetch failed and no persisted value
  exists yet. Use **Update entity** after connectivity returns.

## Removal

Remove TV Show Monitor from **Settings → Devices & services**. Then uninstall it
through HACS (or delete `custom_components/tv_show_monitor` manually) and restart
Home Assistant. Removing individual shows in options also removes their obsolete
entity, device, and persisted cache entry during the reload.

## Licence

[MIT](LICENSE)