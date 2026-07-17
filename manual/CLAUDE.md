# MTGA Mythic TUI Session Tracker (Manual)

## Git Commit Policy
Never include a `Claude-Session:` trailer line (or link) in commit messages
in this repo, regardless of any default commit-message template a harness
or tool may otherwise suggest. `Co-Authored-By:` is fine if otherwise
appropriate; the session-link line is not.

## Project Overview
A completely standalone Terminal User Interface (TUI) application for manually tracking MTG Arena ranked sessions. Unlike the automated log-parsing version, this focuses on **manual game entry** with intuitive controls and comprehensive rank visualization.

## Architecture

### Standalone Design
- **Single file**: `manual_tui.py` - Complete application with no external dependencies  
- **Built-in models**: Rank progression, session tracking, state management
- **Textual framework**: Professional TUI with inline editing capabilities
- **JSON persistence**: Simple file-based state saving

### Key Features Implemented
✅ **Interactive Rank Panel** - Clickable bars with cascading fill/unfill logic  
✅ **Dual Format Support** - Constructed (6 bars) vs Limited (4 bars) per division  
✅ **Manual Game Entry** - W/L hotkeys with automatic stat updates  
✅ **Goal Tracking** - Session goals with progress indicators  
✅ **Enhanced Statistics** - Win rates, current/best/worst streaks  
✅ **Season Management** - Countdown timers, editable dates  
✅ **State Persistence** - Auto-save/load with CLI options  
✅ **Event Mode** - Run-based event tracking (Historic Pauper Challenge, etc.), selected via the **F** switch-mode modal

### Event Mode (run-based events, e.g. Historic Pauper Challenge)
A second, independent tracking mode alongside the ranked ladder, for events
with win/loss-capped runs and a fixed prize table instead of tiers/pips.
Kept fully standalone (dataclasses, no imports from the parent project's
`src/`), matching this app's architecture:

- `models/event.py` — `EventDefinition`, `EntryOption`, `EventRun`,
  `EventGame`, `EventStats` as plain dataclasses (this app's convention, vs.
  the pydantic models in the parent `src/models/event.py`).
- `events.json` (this directory) — this app's own copy of the event
  catalog, so the app remains portable/standalone. Same catalog format
  as the parent project. Entry cost is an `entry_options` array (currency
  name + amount, e.g. Gold/Gems/tokens) rather than fixed fields, so any
  event can offer arbitrary entry methods; `EventRun.net_profit_gems()`
  resolves a gems-equivalent value per option (explicit override, own
  amount if Gems, else the event's own Gems option) for profit calc.
- `EventStats` mirrors `SessionStats`'s session-vs-season split:
  `session_*` counters reset when you restart the event session (**R**
  in Event Mode), `alltime_*` counters never reset except via an explicit
  **Ctrl+R** wipe (confirmation-gated, also clears the current run and
  session totals — this cannot be undone). Session/all-time counters are
  folded from each completed run automatically (`EventStats.record_game`).
- `storage/state_manager.py` — `AppData.event_stats` is persisted in the
  same single `tracker_state.json` blob as everything else, following
  this app's "one big JSON file" convention rather than the parent
  project's per-file managers.
- UI: **F** opens `SwitchModeModal`, a 2x2 button grid for picking
  Constructed BO1/BO3, Limited, or Event (pressing **F** or **Esc** while
  it's open dismisses it without changing anything); choosing Event swaps
  the two main panels for `EventRunPanel` / `EventStatsPanel` (gold `[██]`
  win pips, red `[▓▓]` loss pips). **W**/**L** are context-sensitive — they
  drive the ranked rank or the event run depending on which view is
  active. **U** starts a new run (immediately prompting for the deck being
  run — blank/Cancel is a valid "Unknown"), **R** restarts the event
  session (confirmation modal, same as ranked).
- Per-game tracking: **D** edits the current run's deck at any time. **N**
  opens `EventGameNotesModal` to set the *upcoming* game's opponent deck
  (free text), play/draw (Play/Draw/Unknown, displayed as "On the
  Play"/"On the Draw" via `_format_play_draw()`), and free-text notes,
  stashed until the next W/L consumes it. If W/L is pressed with nothing
  stashed, the same modal reopens in `forced=True` mode (no Cancel button,
  since the win/loss is already decided) so the game still gets recorded —
  Unknown/blank is a one-keypress-away valid answer for both fields
  either way.
- History has two views, both built on the same `EventGamesViewerModal`:
  **Ctrl+G** shows every game flat (current run, then recent completed
  runs); **Ctrl+R** opens `EventRunsViewerModal` (deck/record/prize/status
  per run) and its "View Games" button drills into one run's games via
  `EventGamesViewerModal(runs=[that_run])` — the same modal, just scoped.
  Either way, "Edit Selected" reopens `EventGameNotesModal` (with
  `include_result=True`) pre-filled for that game — result, opponent
  deck, play/draw, and notes are all editable. Editing an active run's
  game is a plain mutation (wins/losses are computed live from
  `run.games`, nothing's been folded into totals yet); editing a
  *completed* run's result goes through `EventGamesViewerModal._apply_edit
  ()`, which diffs the run's old vs. new prize/wins/losses/milestones and
  applies just the delta to `session_*`/`alltime_*` so those counters stay
  correct without re-deriving the whole history. There's still no delete,
  since removing a game entirely has no clean "old" run state to diff
  against. The flat table also shows each row's "Your Deck"
  (`run.player_deck`) alongside the opponent's, since every game in a run
  shares one deck.
- **G** is context-sensitive: ranked mode keeps the existing rank-tier
  goal, while Event Mode opens `SetEventGoalModal` to set/clear a *per-run*
  win-count goal (`EventStats.run_goal_wins`) - e.g. "reach 5 wins this
  run," shown right in `EventRunPanel` next to the win/loss pips (not
  tucked in the stats panel, where it's easy to miss). The target itself
  persists across new runs — like ranked's `session_goal_tier`, which
  isn't cleared by a session reset either — and is only cleared by
  `wipe_alltime()`; each new run's progress naturally starts back at 0
  since `EventRun.wins` is computed live from that run's own games.
  Achievement is detected the same way ranked does it in
  `action_add_win()` - compare `run.wins >= goal` before and after
  recording a game, and celebrate only on the false→true transition -
  rather than a separately-tracked "achieved" flag that would need its
  own reset handling.
- `EventStatsPanel` has a "Trends (Last 10 Games)" section built from
  `_all_event_games_chronological()` (recent_runs, oldest-first since
  that's how they're appended, then the current run's games tacked on
  the end) sliced to `[-10:]` and then reversed, so the most recent game
  is leftmost and it "falls off" to the right as it ages: a W/L glyph
  string (gold/red, matching the win/loss pip colors) and a Play/Draw
  glyph string (cyan "P" / magenta "D" / dim "?" for unrecorded), plus an
  overall "On the Play %" computed across *all* games with a known
  play/draw (not just the last 10), since that's a running total rather
  than a windowed one.
- Panel headers ("─ Event Mode: Current Run ─", "─ Event Session &
  All-Time Stats ─") were removed from `EventRunPanel`/`EventStatsPanel`
  as redundant screen real estate — the top bar already names the event,
  and the run panel's own duplicate "🎮 {event.name} ({event.format})"
  line was replaced with a plain "🎮 CURRENT RUN" label. `_win_pct()` adds
  a "(55.6%)" suffix to the session/all-time Record lines, blank if no
  games have been completed yet (division by zero guard).
- The header removal above was NOT enough to stop Trends from getting
  clipped in a real (smaller) terminal - my own pilot-test screenshots
  were rendered at 100x40, far roomier than a typical terminal. The
  actual culprit turned out to be CSS: `.session-section`/`.season-section`
  (shared with ranked mode's own panels) carry `margin: 1 0`, and
  `EventStatsPanel` renders three separate `Static` widgets (session/
  all-time/trends) each paying that top+bottom margin tax - 6 extra rows
  of pure whitespace - on top of 3 now-removed `"─" * 30` separator
  `Static`s between them. Fix: event-mode-only sections got their own
  `.event-stat-section` class (`margin: 0 0 1 0` - bottom only) instead of
  reusing the ranked classes, and the separators were dropped entirely
  (the emoji headers already visually separate the sections). Verified
  via a headless pilot at a real 80x24 - Session, All-Time, and Trends all
  now render with no scrolling needed, down from needing 100x40+ before.
- Session/All-Time Record, Prize, "Runs played", and Play/Draw % all
  include the current in-progress run's live contribution, not just
  completed runs - `EventStatsPanel._live_run_contribution()` computes
  it fresh on every render (`run.wins`/`run.losses`/`run.prize(event)`/
  `run.plays`/`run.draws`) and adds it on top of the stored
  `session_*`/`alltime_*` fields *for display only*; it never mutates
  those fields, so there's no double-counting once the run actually
  completes and `_complete_run()` folds it in for real. "Runs played"
  gets a "(+1 in progress)" suffix whenever there's an active run,
  driven by a separate `has_active_run` flag rather than "wins or
  losses > 0" - a just-started 0-0 run is still in progress. Milestone
  counts are deliberately NOT given the same live treatment - they read
  as "confirmed achievements from completed runs," not a fluctuating
  number.
- Play/draw is tracked at two levels: `EventRun.plays`/`.draws` (computed
  live from that run's own games, same pattern as `.wins`/`.losses`) for
  "this run"; `EventStats.session_plays`/`.session_draws` and
  `.alltime_plays`/`.alltime_draws` for session/all-time - see below,
  both are computed rather than stored.
- **`recent_runs` was originally capped to the last 5 completed runs -
  removed.** That cap was never a requirement; it was added unprompted
  when event mode was first built, and it actively caused bugs: it forced
  `alltime_wins`/`alltime_losses`/`alltime_gems`/`alltime_packs` to be
  separately-maintained counters (since the run list itself couldn't
  answer "all-time" once older runs fell off the cap), which then needed
  its own `alltime_plays`/`alltime_draws` counters added later for the
  same reason, which THEN needed a legacy-save-migration workaround
  because existing saves predated those fields. `recent_runs` now holds
  every completed run for good (renaming it was considered and rejected -
  see the data-loss incident above - so the name is a bit stale but the
  field is unchanged, avoiding any migration risk).
- With the cap gone, all-time totals are **computed properties/methods on
  `EventStats`**, not stored fields: `alltime_runs_played`
  (`len(recent_runs)`), `alltime_wins`/`.alltime_losses`/`.alltime_plays`/
  `.alltime_draws` (properties, sum over `recent_runs`), and
  `alltime_prize(event)`/`alltime_milestone_counts(event)` (methods,
  since prize tiers and milestone thresholds need the `EventDefinition`
  to resolve - mirrors `EventRun.prize(event)`, which already needed the
  same argument). One source of truth (the run list itself) instead of
  parallel counters that have to be kept in sync by hand - `_apply_edit()`
  in `EventGamesViewerModal` used to have to un-fold/re-fold `alltime_*`
  by hand when a completed run's game was edited; now editing `run` in
  place (a member of `recent_runs`) is reflected automatically.
- **Session totals went through the same treatment shortly after, for the
  same reason.** They were left as stored counters in the first pass
  (`session_wins`/`session_losses`/etc., incremented in `_complete_run()`)
  since `recent_runs` isn't session-scoped and there was no obvious way to
  derive "this session's" totals from it. That reasoning missed a real
  bug: a user reported the session's "On the Play %" being wrong even
  though the current session was the *only* session they'd ever played -
  in that case session and all-time totals should be identical by
  definition, but `session_plays`/`session_draws` had been added as
  separately-tracked counters, so they only reflected runs completed
  *after* those specific fields started being tracked, while
  `alltime_plays`/`alltime_draws` (already computed from the full
  history) correctly included everything. Fix: `EventStats` now has
  `session_start_run_count: int` - the index into `recent_runs` marking
  where the current session began (`len(recent_runs)` at the time
  `restart_session()` is called, `0` by default). `session_runs_played`/
  `session_wins`/`.session_losses`/`.session_plays`/`.session_draws` are
  properties summing `recent_runs[session_start_run_count:]`, and
  `session_prize(event)`/`session_milestone_counts(event)` are the
  methods-needing-`event` equivalent, exactly mirroring the `alltime_*`
  shape. `_complete_run()` is now just `self.recent_runs.append(run)` -
  no separate session or all-time bookkeeping at all. This closes the bug
  by construction: with `session_start_run_count == 0` (the only-ever-
  session case), `_session_runs()` returns the same list `alltime_*` sums
  over, so the two can never again disagree. `wipe_alltime()` resets
  `session_start_run_count` to 0 along with clearing `recent_runs`. The
  Trends section shows only the last-10-games glyph sequences
  (`_all_event_games_chronological()` sliced to `[-10:]`) - no "On the
  Play %" summary line there anymore. That stat lives in the Session and
  All-Time sections instead (each using its own `session_plays`/
  `session_draws` or `alltime_plays`/`alltime_draws` + the live run's
  contribution) since "on the play %" is a session/all-time-scoped stat,
  not something that belongs alongside a windowed "last 10 games" trend.
  `_on_the_play_line()` is the shared formatter for all "On the Play: N%
  (X/Y known)" lines. Trade-off: this adds a line back to both Session
  and All-Time (removed earlier this session to fix Trends clipping) and
  removes one from Trends, a net +1 row - full Trends (including the
  Play/Draw glyph line) now needs an ~26-row terminal instead of 24.
- The top bar's `.top-format` column (event entry cost) truncated when an
  event has multiple entry options and no run is active yet - e.g.
  "💰 Entry: 5000 Gold / 1000 Gems" got chopped off mid-text, since the
  column was only `width: 20%` of the top bar. First fix attempt bumped
  `.top-panel` from `height: 3` to `4` so the text could wrap onto a
  second line - this technically avoided truncation but visibly made the
  whole top bar look "too tall," since the other three columns (which
  only ever need one line) now had a full blank row of vertical padding
  under `content-align: middle`. Reverted the height back to `3` and
  instead reallocated the four columns' widths based on each one's actual
  worst-case content length across both ranked and event mode -
  `.top-season` 38% (was 40%, still enough for the longest ranked
  countdown string), `.top-format` 28% (was 20% - the actual fix, gives
  enough room for a 2-option entry-cost line), `.top-bars` 16% (was 20%,
  never needs more than ~17 chars), `.top-rank` 18% (was 20%, comfortably
  fits the longest rank string, e.g. "📍 Platinum 2 (3/6)"). Verified via
  a headless pilot at the actual reported terminal size (121x30), reading
  each column's real Static content against its rendered size, for both
  ranked mode's longest strings (season countdown, "Platinum 2 (3/6)")
  and event mode's longest strings (event name, 2-option entry cost) -
  all fit on one line with margin to spare, single-row top bar restored.
- `.left-panel, .right-panel` had `margin: 1` (all four sides) - dropped
  to `margin: 0 1` (horizontal only) once the top bar shrank back to
  `height: 3`, reclaiming 2 rows of usable panel height that vertical
  margin was eating for no visual purpose (`#main-content` already has
  its own `overflow-y: auto` and the top-bar border provides the visual
  separation). `.left-panel` additionally gets `padding: 1 1 1 0` (left
  padding dropped to 0, other sides unchanged) - a user-requested tweak,
  the run panel's text was sitting further from its left border than the
  stats panel's text was from its own.
- Event Mode had no visible session timer (ranked mode has one via
  `SessionStats.session_start_time`/`get_active_session_duration()`).
  Added the same concept to `EventStats`: `session_start_time: datetime`
  (`field(default_factory=datetime.now)`, so a brand-new EventStats - or
  one reconstructed from a save that predates this field - just works
  without a separate default-state code path) and `session_duration()`
  (plain wall-clock `datetime.now() - session_start_time`, no pause/
  resume - event runs are discrete win/loss-capped attempts, not a
  continuous game clock like ranked's). Reset in both `restart_session()`
  and `wipe_alltime()`, same as `session_start_run_count`. Displayed as a
  "Started: 1:32 AM  Duration: 2m 15s" line at the top of the Session
  section (`_format_duration()` is the shared H/M/S formatter, dropping
  leading zero units). Ticks live: `EventStatsPanel._generate_session_content()`
  was split out from `_create_session_section()` (mirrors ranked's
  `_generate_session_content()`/`refresh_session_section()` split) so the
  app's existing 1-second `set_interval` timer tick can re-render just
  that one `Static` (`id="event-session-section"`) without rebuilding the
  whole stats panel - `ManualTUIApp._update_session_timers()` used to
  return immediately for event mode entirely (StatsPanel isn't mounted
  there); it now calls `EventStatsPanel.refresh_session_section()`
  instead of returning early.
- Six ranked-only actions (`toggle_mythic`, `set_season_start`,
  `edit_stats`, `hide_tiers`, `set_rank`, and `view_all_notes` — bound to
  M/T/E/H/S and Ctrl+N respectively) have no Event Mode behavior at all,
  so `ManualTUIApp` overrides `check_action()` to return `False` for them
  while `view_mode == "event"`, which disables *and hides* them from the
  Textual `Footer` widget (vs. `None`, which would just grey them out).
  `set_goal` (G) and `collapse_tiers` (C) are deliberately excluded from
  that list since they're context-sensitive rather than ranked-only. Event
  Mode's history/wipe actions deliberately live on their own combos
  (Ctrl+G/Ctrl+R/Ctrl+W) rather than reusing ranked's Ctrl+N, so both
  modes' conventions stay independent.
- **C** is context-sensitive like G: ranked mode keeps its existing
  auto-collapse-tiers toggle, while Event Mode repurposes it to concede
  the current run early via `EventStats.concede_run()` (confirmation-
  gated, since it's irreversible) - previously a run could *only* end by
  naturally reaching `win_cap`/`loss_cap`, with no way to voluntarily
  drop out partway through. `concede_run()` calls `run.end_run()` then
  reuses `_complete_run()` to fold the partial record into session/
  all-time totals exactly like a natural completion would.
- **Ctrl+E**/**Ctrl+O** export/import the *entire* app state (ranked +
  event, everything) to/from a standalone JSON file — global, not
  Event-Mode-specific. `StateManager.export_state()` writes a timestamped
  copy under `data_dir/exports/` (or an explicit path) without touching
  the live `tracker_state.json`; `import_state()` loads an arbitrary file
  through the same reconstruction path as `load_state()` and raises on
  failure instead of silently falling back to defaults, since an
  explicit user-initiated import needs to surface a bad file, not treat
  it as if no data existed. `ImportDataModal` collects the path
  (pre-filled with the most recent export, if any) and a
  `ConfirmationModal` gates the actual replacement, since import
  overwrites all current data. Added directly in response to a real
  incident (see below) where a silent data-loss bug had no recovery
  path at all.
- `load_state()`/`save_state()` are thin wrappers around
  `_reconstruct_app_data()`/`_serialize_app_data()`, shared with
  `import_state()`/`export_state()` respectively, so both paths use
  identical (de)serialization logic rather than parallel
  implementations that could drift.
- **Incident**: renaming `EventStats.session_goal_wins` to
  `run_goal_wins` broke loading for anyone who'd already saved with the
  old name — `EventStats(**stats_dict)` raised `TypeError` on the
  unexpected kwarg, and `load_state()`'s broad `except` caught it by
  silently discarding the *entire* save file (ranks, sessions, event
  history) in favor of a blank default. Fixed two ways: `_known_fields()`
  strips any dict keys that aren't real dataclass fields before
  construction (applied at every reconstruction site), so a
  renamed/removed field now just resets to its default instead of
  crashing the whole load; and `_backup_unreadable_state()` copies a
  file that still fails to load aside as
  `tracker_state.corrupted-<timestamp>.json` before falling back to
  defaults, so a future bug can't silently overwrite real data via the
  next autosave. A related bug found during the same investigation:
  `_deserialize_datetimes()`'s recursive walk only descended into dicts,
  not lists, so `EventGame.timestamp` and `EventRun.start_time`/
  `end_time` (nested inside `current_run.games`/`recent_runs`) came back
  as plain ISO strings instead of `datetime` objects after every reload
  - fixed by recursing into lists too.
- Tests: `test_event_models.py` (pytest), covering prize/milestone
  lookup, run completion, session/all-time aggregation, a StateManager
  save/load round-trip, the renamed-field and nested-datetime regression
  cases above, and an export/import round trip.

## TUI Layout

### Complete Interface Design:
```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           MTGA Mythic TUI Session Tracker (Manual)                     │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 🕐 Season: 23d 14h 32m [Dec 31 11:59PM]  📊 CONSTRUCTED  🎯 BARS: 28  📍 Plat 1 (2/6) │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Rank Progress [CONSTRUCTED]─────────────┐ ┌─ Session & Season Stats ──────────────────┐ │
│ │ [F] Switch to Limited                    │ │ 🎯 SESSION GOAL: [Plat 3] 4 bars away!   │ │  
│ │ ──────────────────────────────────────── │ │ ────────────────────────────────────────── │ │
│ │ Mythic    [  ][  ][  ] [87.3%]           │ │ 📊 CURRENT SESSION [CONSTRUCTED]          │ │
│ │ Diamond 1 [  ][  ][  ][  ][  ][  ]       │ │ Started:  [2:15 PM]  Duration: 2h 34m    │ │
│ │ Diamond 2 [  ][  ][  ][  ][  ][  ]       │ │ Record:   [15W] - [8L]  65.2%             │ │
│ │ Diamond 3 [  ][  ][  ][  ][  ][  ]       │ │ Streaks:  W7 / L2 (current)              │ │
│ │ Diamond 4 [  ][  ][  ][  ][  ][  ]       │ │ ────────────────────────────────────────── │ │
│ │ Plat 1    [██][██][  ][  ][  ][  ] ←YOU  │ │ 🏆 SEASON TOTAL [CONSTRUCTED]             │ │
│ │ Plat 2    [██][██][██][██][██][██]       │ │ Record:   [245W] - [198L]  55.3%          │ │
│ │ Plat 3    [██][██][██][██][██][██] ←GOAL │ │ Best:     [W12]  Worst: [L5]              │ │
│ │ Plat 4    [██][██][██][██][██][██]       │ │ Started:  [Gold 2 (3/6)]                 │ │
│ │ ──────────────────────────────────────── │ │ ────────────────────────────────────────── │ │
│ │ Gold 1-4  [████████████████████] FULL   │ │ 📈 SESSION HISTORY                        │ │
│ │ Silver    [████████████████████] FULL   │ │ Today:     15W-8L (65.2%) +7 bars        │ │
│ │ Bronze    [████████████████████] FULL   │ │ Yesterday: 12W-5L (70.6%) +4 bars        │ │
│ │ ──────────────────────────────────────── │ │ This Week: 89W-42L (67.9%) +15 bars      │ │
│ │ [Click any bar to set rank position]     │ │ Last Week: 67W-38L (63.8%) +8 bars       │ │
│ │ [C] Collapse [H] Hide completed tiers    │ │ Best Day:  18W-3L (85.7%) +12 bars       │ │
│ │                                          │ │ ────────────────────────────────────────── │ │
│ │                                          │ │ [W] +Win  [L] +Loss  [R] Reset Session   │ │
│ │                                          │ │ [F] Format [G] Goal  [M] Toggle Mythic   │ │
│ └──────────────────────────────────────────┘ └───────────────────────────────────────────┘ │
│ [Tab] Switch Panels  [S]tart Session  [E]nd Session  [Q]uit  [?] Help                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## MTG Arena Rank System

### Tier Progression & Pip System
- **Bronze/Silver**: 2 pips per win, 0 pips lost (can't derank)
- **Gold**: 2 pips per win, 1 pip lost per loss  
- **Platinum**: 1 pip per win, 1 pip lost per loss ⚠️ **The Platinum Wall**
- **Diamond**: 1 pip per win, 1 pip lost per loss ⚠️ **The Diamond Grind**

### Format Differences
- **Constructed**: 6 bars per division (Bronze 4 → Mythic)
- **Limited**: 4 bars per division (Bronze 4 → Mythic)

### Mythic Handling
When Diamond 1 is complete:
```
┌─ Rank Progress ────────────────┐
│ 🏆 MYTHIC ACHIEVED! 🏆          │
│                                │  
│ Current: [87.3%] ←click to edit │
│ Best:    [92.1%] ←click to edit │  
│                                │
│ Or enter rank: [#1247] ←edit   │
│                                │
│ [H] Show Full Rank History     │
└────────────────────────────────┘
```

## Manual Interaction Features

### Clickable Elements (Inline Editing)
All bracketed items `[value]` are click-to-edit:
- **Rank Progress**: Click any bar to set rank with cascading logic
- **Session Stats**: Win/loss records, streaks, start times
- **Season Stats**: Total records, best streaks, season start rank
- **Mythic Values**: Percentage or rank number (#1234)
- **Timing**: Session start time, season end date/time

### Keyboard Controls
- **W/L**: Quick game entry with auto-calculations
- **F**: Format switching (updates bar counts and pip logic)
- **G**: Goal setting with progress tracking
- **C/H**: Rank panel management (collapse/hide completed)
- **M**: Toggle mythic progress display (hideable for sanity!)
- **R**: Session reset with confirmation

### Goal System
- **Session Goals**: "Reach Plat 3 this session" 
- **Progress Tracking**: "4 bars away!" or "2 wins needed!"
- **Visual Indicators**: Goal rank highlighted in progression panel
- **Motivation**: Clear, achievable targets per session

## State Management

### Data Persistence
```json
{
  "current_format": "CONSTRUCTED",
  "constructed_rank": {
    "tier": "Platinum", 
    "division": 1,
    "pips": 2
  },
  "limited_rank": {
    "tier": "Gold",
    "division": 3,
    "pips": 2
  },
  "session": {
    "wins": 15,
    "losses": 8,
    "start_time": "2025-01-15T14:15:00",
    "goal_rank": "Plat 3"
  },
  "season": {
    "wins": 245,
    "losses": 198,
    "end_date": "2025-12-31T23:59:59",
    "best_win_streak": 12,
    "worst_loss_streak": 5
  }
}
```

### CLI Options
```bash
# Default behavior: ~/.local/share/mtga-manual-tracker/
python3 manual_tui.py

# Custom data directory
python3 manual_tui.py --data-dir ~/my-mtga-data/

# No persistence (fresh each run)
python3 manual_tui.py --no-save

# Help and options
python3 manual_tui.py --help
```

## Development Commands

### Running the Application
```bash
# Set up environment
cd manual/
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run manual tracker
python3 manual_tui.py

# Run with options
python3 manual_tui.py --data-dir ~/Desktop/mtga-data/ --format Limited
```

### Development Notes
- **Single-file architecture**: All models, UI, and logic in `manual_tui.py`
- **No external dependencies**: Only uses textual framework + Python stdlib
- **Standalone operation**: No imports from parent project's `src/` directory
- **Clean separation**: Models → Widgets → App → CLI argument handling

## Implementation Status

### Design Phase: ✅ **COMPLETE**
✅ **TUI Layout**: Complete mockup with all panels and interactions  
✅ **Feature Requirements**: All manual editing and hotkey functions defined  
✅ **Rank System Logic**: MTG Arena progression rules documented  
✅ **State Persistence**: Data structure and file management planned  

### Implementation Phase: ✅ **COMPLETE**
✅ **Core Models**: Rank, Session, Statistics with manual update logic  
✅ **Textual Widgets**: Interactive panels, top panel layout, confirmation popups  
✅ **Application Logic**: Hotkey handling, format switching, goal tracking  
✅ **CLI Interface**: Argument parsing, data directory options  
✅ **State Management**: JSON save/load with automatic persistence  
✅ **Bug Fixes**: Timer API, widget initialization, panel composition  

### Current Status: 🎯 **PRODUCTION READY APPLICATION**
✅ **manual_tui.py**: Complete 1400+ line standalone application  
✅ **All Core Features**: Win/loss tracking, rank progression, format switching  
✅ **Professional UI**: 4-column top panel, colored rank visualization, stats panels  
✅ **State Persistence**: Automatic save/load with CLI options  
✅ **Error Handling**: Fixed Textual API compatibility and AttributeError issues  
✅ **Manual Rank Setting**: Complete modal interface with dropdowns and validation  
✅ **Tier Floor Protection**: Proper MTG Arena rank system implementation  
✅ **Visual Polish**: Tier-colored bars, mythic highlighting, current position highlighting  

### Latest Session Work (2025-08-12 - Evening)
✅ **Rank Setting Modal (S key)**: Dropdown interface for tier/division/pips with mythic support  
✅ **Mythic Validation**: Percentage (0-100%) and rank number (≥1) validation  
✅ **Tier Floor Protection**: Can't drop from Plat 4→Gold, Diamond 4→Plat, etc.  
✅ **Tier-Colored Bars**: Bronze/Silver/Gold/Platinum(cyan)/Diamond(purple)/Mythic(orange)  
✅ **Current Position Highlighting**: Tier name/division with colored background  
✅ **Mythic Display Integration**: Achievement display above rank bars with proper spacing  
✅ **Auto Collapse/Hide Modes**: Sticky C/H behavior - applies to newly completed tiers  
✅ **Top Panel Mythic Integration**: Shows "🏆 MYTHIC" instead of bars remaining  
✅ **Modal Height & Widget Visibility**: Fixed pips dropdown and modal sizing issues  
✅ **UI Cleanup**: Removed redundant control buttons from right panel - keyboard shortcuts preferred  

### Fully Working Features  
- **W/L Hotkeys**: Add wins/losses with automatic rank progression and tier promotion
- **S Key**: Manual rank setting via modal with tier/division/pips dropdowns
- **F Key**: Switch between Constructed (6 bars) and Limited (4 bars) formats  
- **G Key**: Set session goals with progress tracking
- **M Key**: Toggle mythic achievement display on/off
- **C Key**: Auto-collapse mode for completed tiers (shows colored full bars)
- **H Key**: Auto-hide mode for completed tiers (removes them entirely)
- **R Key**: Reset session with confirmation dialog
- **E Key**: Restart session (same functionality as reset with different confirmation message)
- **State Persistence**: Automatic save to `~/.local/share/mtga-manual-tracker/`
- **CLI Arguments**: `--data-dir`, `--no-save`, `--format` options
- **Visual Highlighting**: Current position highlighted with tier-colored backgrounds
- **Mythic Support**: Percentage and rank number modes with proper validation

### All Tasks Complete ✅
✅ **Manual Rank Setting**: Complete dropdown modal interface with validation  
✅ **Tier-Colored Visualization**: All rank bars show in appropriate tier colors  
✅ **Current Position Highlighting**: Clear visual indication of current rank position  
✅ **Mythic Integration**: Full mythic support with achievement display and orange styling  
✅ **Auto Collapse/Hide**: Intelligent sticky modes for completed tier management  

### Development Notes
- **Single File**: All code in `manual_tui.py` - no external dependencies from main project
- **Textual Version**: Compatible with textual>=0.41.0
- **Error Recovery**: Application handles startup errors gracefully
- **Cross Platform**: Works on Linux/Mac/Windows with proper data directory detection

### Data Storage & Testing
- **Linux/Mac**: `~/.local/share/mtga-manual-tracker/`
- **Windows**: `~/AppData/Roaming/mtga-manual-tracker/`
- **Testing**: Remove data directory to reset state for fresh testing
- **State Includes**: Ranks, session stats, collapsed/hidden tiers, auto-modes

## Project Goals

This manual tracker provides MTG Arena players with:
1. **Complete control** over rank tracking without log file dependencies
2. **Intuitive interaction** through click-to-edit and keyboard shortcuts  
3. **Professional UI/UX** rivaling desktop applications in a terminal
4. **Motivational tools** like goal setting and progress visualization
5. **Standalone operation** - works anywhere Python + Textual are available

Perfect for players who want precise session tracking, goal-oriented climbing, or situations where log parsing isn't available/desired.

## Time Tracking Notes
- **Requirements Phase**: Completed - comprehensive TUI design with all features mapped  
- **Implementation Phase**: Completed - functional standalone application with all core features  
- **Bug Fix Phase**: Completed - resolved Textual API compatibility and widget composition issues  
- **UI Polish Phase**: Completed - improved top panel layout and information organization  
- **Architecture**: Single-file approach achieved for maximum portability and simplicity  

### Latest Session Summary (2025-08-19)  
**Total Implementation Time**: 6h 52min across 7 sessions  
**Lines of Code**: 2,400+ in `manual_tui.py` (now modularized)  
**Features Completed**: Legal compliance framework + About modal + modularization  
**Status**: Production-ready with complete licensing and transparency  

**Key Accomplishments This Session (1h)**:
1. **Complete Licensing Framework** - Added VCL-0.1-Experimental + MIT dual licensing
2. **Legal Compliance** - Wizards Fan Content Policy + AI development transparency  
3. **Professional About Modal** - I key with project info, licensing, GitHub links
4. **Architecture Modularization** - Extracted models/ and storage/ packages
5. **UI Polish** - Season Current display, cleaned modal layout, Ctrl+Q fix
6. **Documentation** - AI_DEVELOPMENT.md + comprehensive attribution standards

**Previous Session Summary (2025-08-13)**:
**Features Completed**: Advanced timer systems + milestone celebrations  
**Key Accomplishments**:
1. **Game Timer System** - Dedicated game timing with Shift+S start, auto-stop on W/L
2. **Session Pause/Resume** - P key pauses both session and game timers with visual indicators
3. **Milestone Toast System** - Celebrations for tier promotions, win milestones, win rate achievements
4. **Dual Time Tracking** - Real time vs active time for comprehensive session analytics
5. **Goal Achievement Toasts** - Celebratory notifications when session goals are reached
6. **Error Resolution** - Fixed datetime serialization, type hints, and variable scope issues

**Next Session Goals**:
- Create automated version based on manual TUI foundation
- Complete UI component extraction to ui/ package
- Implement per-format tracking (separate Limited/Constructed stats)
- Add daily/weekly stats tracking with midnight rollover detection

### Development Context for Future Sessions
The manual tracker is a **complete, functional application** that can be picked up and enhanced in future sessions. The core architecture is solid and all fundamental features work correctly. Future work should focus on UI/UX improvements and enhanced interactivity rather than core functionality.