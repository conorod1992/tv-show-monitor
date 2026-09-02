# TV Show Monitor

TV Show Monitor is a UI-configured Home Assistant custom integration that checks
[TVmaze](https://www.tvmaze.com/) for the next scheduled episode of each show you
follow. It creates one sensor and one Home Assistant device per TV show.

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
interval changes are handled separately and never rematch shows. The final followed
show may be removed; when the list is empty, Configure only offers actions that are
valid for an empty monitor.

## TV Show Monitor viewer

TV Show Monitor includes a simple viewer so you do not need to open Developer Tools
just to check episode details.

The viewer groups followed shows into:

- **Today**;
- **Coming up**;
- **Recent**, for episodes that aired today or yesterday;
- **No episode scheduled**;
- **Ended**.

Each show card can display the poster, episode code and name, your local airing date
and time, network or streaming service, runtime, and final-episode details where
available. Click a card, or focus it and press **Enter** or **Space**, to open Home
Assistant's normal entity details.

Home Assistant administrators also see a **Manage shows** button in the viewer. It
opens a dedicated dialog that lists the current followed shows, lets you remove a
show with confirmation, and searches TVmaze for shows to add. Search results show
useful disambiguation details such as premiere year, country, network and status,
and already-followed results are clearly disabled. Add/remove changes are written to
the integration's normal config-entry options and applied through the same reload
path used by the Configure flow, so entity/device cleanup and normal lifecycle
handling remain consistent. Non-administrator users keep read-only access to the
viewer and do not see the management control.

The management dialog is kept separate from the programme-card rendering. Normal
Home Assistant state updates can therefore refresh episode cards without closing an
in-progress search or removal confirmation.

The viewer is available as a Home Assistant panel, but it is **hidden from the
sidebar by default** to avoid adding clutter. Users who want quick access can choose
to show it in their sidebar.

## Sensor states

Each entity is naturally named from the canonical TVmaze title, for example
`sensor.severance_next_episode`.

- A scheduled episode: its TVmaze air date in ISO format, such as `2026-10-12`.
- A `Running` show with no scheduled episode: `No next episode scheduled`.
- An `Ended` show with no scheduled episode: `Ended`.
- An `In Development` show with no scheduled episode: `In Development`.
- A `To Be Determined` show with no scheduled episode: `To Be Determined`.
- A successful check with no episode and no recognised lifecycle status: `No next episode found`.
- No successful check yet: unavailable.

The sensor state intentionally remains simple and stable whenever an actual next
episode exists. Richer programme and schedule information is exposed as attributes.
When TVmaze provides show artwork, the sensor also uses the show's poster as its Home
Assistant entity picture. The smaller TVmaze image is preferred to keep dashboard
image loads lightweight, with the original image used only as a fallback.

Template example:

```jinja2
{{ states('sensor.severance_next_episode') }}
```

## Attributes

When available, each sensor exposes:

- TVmaze show ID, show name and current show status;
- ended date for ended shows;
- current network and/or web channel;
- TVmaze's normal schedule days and time;
- next episode ID/name, season, episode number and `S02E04`-style code;
- next air date/time, ISO air stamp, `next_airing`, runtime and episode URL;
- `days_until`, calculated from Home Assistant's current local date;
- previous episode ID/name, season, episode number/code and air date/time;
- show URL and refresh diagnostics.

For an ended show with no next episode, the previous episode is also exposed through
`final_episode_*` attributes so dashboards and automations can identify the final
known episode directly.

A valid no-episode result includes `next_episode_found: false`. Every result reports
the latest attempt and whether it succeeded; a failed attempt also exposes a short,
safe `last_error`. Last-good lifecycle metadata, artwork, previous episode and next
episode data are preserved through transient refresh failures and Home Assistant
restarts.

## Home Assistant events

### Episode today

`tv_show_monitor_episode_today` fires once when a monitored episode's airing date is
today in Home Assistant's local time. If a new episode is first discovered during
the day, the event can still fire on that refresh rather than waiting for another
midnight.

### Episode airing

`tv_show_monitor_episode_airing` fires at the known airing time. The integration
schedules this locally from TVmaze's absolute air timestamp, so it does not depend on
the normal 24-hour polling interval happening at exactly the right moment.

Both episode events include:

- `tvmaze_show_id` and `show_name`;
- episode ID, name, season, number and episode code;
- air date, air time and air stamp;
- runtime;
- network and web channel when known.

Delivery markers are persisted so normal refreshes and Home Assistant restarts do
not repeat an event that has already fired for the same scheduled episode.

### Status changed

`tv_show_monitor_status_changed` fires when TVmaze changes a known show status, for
example from `Running` to `Ended`. Event data includes `tvmaze_show_id`, `show_name`,
`old_status`, and `new_status`.

### Schedule changed

After the integration has established a successful baseline, meaningful changes to
the next-episode schedule fire a `tv_show_monitor_schedule_changed` Home Assistant
event. Initial setup does not emit an event simply because a show already has an
upcoming episode.

`change_type` is one of:

- `scheduled` — a show with no known next episode gains one;
- `schedule_cleared` — a future scheduled next episode disappears;
- `next_episode_changed` — TVmaze replaces the future next episode with a different one;
- `rescheduled` — the same episode ID has a different air date or air stamp.

Normal episode progression after an episode has aired is not treated as a schedule
correction just because TVmaze now reports the following episode as next.

Schedule-change event data includes `tvmaze_show_id`, `show_name`, old/new episode
IDs, old/new air dates and old/new air stamps.

Example event trigger:

```yaml
triggers:
  - trigger: event
    event_type: tv_show_monitor_episode_today
conditions: []
actions:
  - action: notify.notify
    data:
      title: New episode today
      message: >-
        {{ trigger.event.data.show_name }} —
        {{ trigger.event.data.episode_code }}
        {{ trigger.event.data.episode_name }}
mode: single
```

## Polling and error preservation

The default interval is 24 hours. The options flow accepts 24-hour steps from 24
to 744 hours (for example 24, 48, 72, or 168). Standard Home Assistant entity
updates request a coordinated refresh.

Shows are fetched independently with a small concurrency limit to avoid request
bursts while preventing one slow request from serialising the entire refresh.
Each show's single TVmaze request includes its main programme information plus the
previous and next episode links when TVmaze has them. Transient timeouts, rate
limits, connection failures, and common server-side failures are retried once.

Shows reported by TVmaze as `Ended` with no future episode are normally skipped once
a successful ended-state result has been stored. They are rechecked every 30 days so
a later TVmaze correction or revival can still be detected automatically. An ended
show that still has a future episode continues to use the normal configured polling
cadence.

A successful response with no future episode replaces any old next episode with the
appropriate lifecycle-aware state. A failed API request or invalid response retains
the last successful sensor value and its episode attributes, while recording failure
diagnostics. Last-good state is stored by Home Assistant and survives restarts.

## TVmaze attribution

Schedule, programme data and artwork are provided by [TVmaze](https://www.tvmaze.com/).
TV Show Monitor is not affiliated with or endorsed by TVmaze.

## Known limitations

- TVmaze only reports publicly scheduled future episodes.
- TVmaze uses `Ended` for shows that have finished; the integration does not infer a
  separate cancelled state when TVmaze does not provide one.
- Show artwork is only available when TVmaze supplies an image for that show.
- `days_until` is based on TVmaze's published air date rather than the viewer's
  personal streaming availability.
- Polling intervals use whole 24-hour steps and cannot be shorter than one day.

## Troubleshooting

- If the wrong show is matched, open **Configure → Change TVmaze match** and choose
  the correct search result.
- If a running sensor says `No next episode scheduled`, TVmaze currently has no
  scheduled next episode for it.
- If `last_attempt_successful` is false, check Home Assistant logs and wait for the
  next poll; the previous good value remains in place.
- If a new sensor is unavailable, its first fetch failed and no persisted value
  exists yet. Use **Update entity** after connectivity returns.

## Removal

Remove TV Show Monitor from **Settings → Devices & services**. Then uninstall it
through HACS (or delete `custom_components/tv_show_monitor` manually) and restart
Home Assistant. Removing individual shows from either the viewer or Configure also
removes their obsolete entity, device, repair issue and persisted cache entry during
the integration reload.

## Releasing

Repository releases are created from **Actions → Release → Run workflow**. Enter the
new `X.Y.Z` version once. The workflow verifies that the committed version still
matches the latest published release, synchronises the Home Assistant manifest,
`const.VERSION`, and `pyproject.toml`, commits that version bump to `main`, then
creates the matching `vX.Y.Z` GitHub release with generated notes. Normal development
should not pre-bump those version files; CI checks that all three remain aligned.

## Licence

[MIT](LICENSE)
