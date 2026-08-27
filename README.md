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

During setup, every entered title is searched using TVmaze's show-search API.
Exact programme matching is initially based on TVmaze's highest-ranked search
result. Setup is rejected in full if any title cannot be resolved or two titles
resolve to the same show. Routine polling uses the saved TVmaze ID, not the title.

To add, remove, or rename entries later, open the integration's **Configure**
dialog and replace the complete list.

## Sensor states

Each entity is naturally named from the canonical TVmaze title, for example
`sensor.severance_next_episode`.

- A scheduled episode: its local calendar date in ISO format, such as `2026-10-12`.
- A successful check with no scheduled episode: `No next episode found`.
- No successful check yet: unavailable.

TVmaze may not have a date until an episode has been publicly scheduled. The
integration does not infer whether a programme is cancelled, ended, on hiatus, or
awaiting renewal.

Template example:

```jinja2
{{ states('sensor.severance_next_episode') }}
```

## Attributes

Scheduled episodes include the TVmaze show ID, episode ID and name, season,
episode number, `S02E04`-style episode code where possible, type, air date/time,
air stamp, runtime, episode URL, show URL, and refresh timestamps. A valid
no-episode result includes `next_episode_found: false`. Every result reports the
latest attempt and whether it succeeded; a failed attempt also exposes a short,
safe `last_error`.

## Polling and error preservation

The default interval is 24 hours. The options flow accepts 24-hour steps from 24
to 744 hours (for example 24, 48, 72, or 168). Standard Home Assistant entity
updates request a coordinated refresh for all shows.

Shows are fetched independently with a small concurrency limit to avoid request
bursts while preventing one slow request from serialising the entire refresh.
Transient timeouts, rate limits, and common server-side failures are retried once.
A successful response with no future episode replaces any old episode with `No
next episode found`. A failed API request or invalid response retains the last
successful sensor value and its episode attributes, while recording failure
diagnostics. Last-good state is stored by Home Assistant and survives restarts.

## Example automation

Paste this into an automation's **Edit in YAML** screen and replace the notification
service if needed:

```yaml
alias: Severance episode scheduled
description: Notify when TVmaze publishes the next Severance date
triggers:
  - trigger: state
    entity_id: sensor.severance_next_episode
    from: "No next episode found"
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state.state is match('^\\d{4}-\\d{2}-\\d{2}$') }}
actions:
  - action: notify.notify
    data:
      title: Severance episode scheduled
      message: >-
        The next episode is on {{ trigger.to_state.state }}:
        {{ trigger.to_state.attributes.episode_name }}
mode: single
```

## TVmaze attribution

Schedule and programme data is provided by [TVmaze](https://www.tvmaze.com/).
TV Show Monitor is not affiliated with or endorsed by TVmaze.

## Known limitations

- Matching always accepts TVmaze's highest-ranked result; there is no interactive
  result picker yet.
- TVmaze only reports publicly scheduled future episodes.
- Polling intervals use whole 24-hour steps and cannot be shorter than one day.

## Troubleshooting

- If the wrong show is matched, use a more specific title, including the year or
  country when helpful, and review the result on TVmaze.
- If a sensor says `No next episode found`, TVmaze currently has no scheduled next
  episode. This is not an error.
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
