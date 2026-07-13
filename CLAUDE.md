# MTGA Mythic TUI Session Tracker

## Project Overview
A Terminal User Interface (TUI) application for tracking MTG Arena ranked sessions with real-time log parsing and ASCII rank visualization.

## Architecture

### Core Components
- **Models** (`src/models/`): Data structures for ranks, games, sessions, and events
- **Config** (`src/config/`): Settings and configuration management
- **Core** (`src/core/`): Application state management
- **Parsers** (`src/parsers/`): MTGA log file parsing
- **UI** (`src/ui/`): Textual-based TUI framework (coming soon)

### Event Mode (run-based events, e.g. Historic Pauper Challenge)
Ranked ladder tracking (tiers/pips) and event tracking (win/loss-capped runs
with a fixed prize table) are different enough shapes that events get their
own parallel model/manager stack rather than being bolted onto Session/Rank:

- `src/models/event.py` — `EventDefinition` (win/loss caps, entry cost,
  prize table, milestone thresholds), `EventRun` (a single attempt, ends at
  win_cap wins or loss_cap losses), `EventSession` (a sitting containing one
  or more runs), `EventAppState` (crash-recovery, parallel to `AppState`).
- `events.json` (repo root) — hand-edited catalog of event definitions, one
  entry per event by `event_id`. Supports multiple concurrently-running
  events with independent win/loss caps and prize tables. A TUI editor for
  this catalog is a possible future enhancement; for now it's edited by
  hand. Fill in `start_date`/`end_date` once known.
- `src/core/event_state_manager.py` / `src/core/event_data_manager.py` —
  parallel to `StateManager`/`DataManager`: persist the active session,
  and aggregate lifetime stats both per-event (`get_overall_stats`) and as
  a grand total across every event ever played (`get_grand_total`).
- `src/core/serialization.py` — shared datetime (de)serialize helpers used
  by the two event managers.
- Milestones (e.g. "Winning Run" at 3+ wins, "Trophy" at win_cap) are
  configured per-event in `events.json` and computed both ways: a run's
  `highest_milestone()` picks the single highest threshold met, while
  `EventSession.milestone_counts()` tallies cumulatively (a 7-win run
  counts toward "3+ wins", "5+ wins", etc. all at once).
- Net profit (`EventRun.net_profit_gems()`) only nets cleanly when the
  entry fee was paid in gems (gold has no fixed gems conversion rate).
- In the TUI (`main_tui.py`), press **V** to open `EventScreen`, a full
  screen (not a modal) showing the current run's win/loss pips in
  gold/red, session totals, and overall totals side by side. Win/Loss/New
  Run/End Session/Back are wired as both buttons and keybindings — buttons
  are the reliable path, since a focused `Input` widget swallows
  single-letter keys as text before they reach screen bindings.

### Key Features Implemented
✅ **Rank System** - Full MTG Arena rank progression with demotion protection  
✅ **Game Tracking** - Win/loss, play/draw, notes, deck tracking  
✅ **Session Management** - Start/stop/pause sessions with persistence  
✅ **Configuration System** - JSON-based settings with validation  
✅ **State Management** - Crash recovery and resume functionality  
✅ **Log Parser Framework** - Ready for real MTGA log data  

### Features Completed This Session
✅ **Data Persistence Layer** - Session history and file management ✅  
✅ **Real Log Analysis** - Parsed actual MTGA logs, found rank progression ✅  
✅ **Log Viewer TUI** - Terminal-based log browser with filtering ✅  
✅ **Configuration Integration** - Log path auto-detection and manual setup ✅  

### Final Status - ALL FEATURES COMPLETE ✅
✅ **Main TUI Application** - Professional Textual interface with side panels  
✅ **ASCII Rank Visualization** - Full tier progression with pip displays  
✅ **Configuration System** - CLI args + modal settings screen (Ctrl+,)  
✅ **Session Management** - Start/pause/end with keybindings  
✅ **Command Line Interface** - Full argument parsing with help  

### Features Ready for Enhancement
🔄 **Real-time Log Monitoring** - Framework ready, needs file watching  
🔄 **Live Game Integration** - Parser can extract game state from logs  
🔄 **Session Persistence** - Models support save/load, needs file integration  

## Development Commands

### Main Application
```bash
# Run the main TUI (activate venv first!)
source ~/.venv-tui/bin/activate && python3 main_tui.py

# Show command line options
source ~/.venv-tui/bin/activate && python3 main_tui.py --help

# Run with custom settings
source ~/.venv-tui/bin/activate && python3 main_tui.py --log-path ~/Player.log --format Historic
```

### Testing
```bash
# Test core models (rank system, game tracking)
source ~/.venv-tui/bin/activate && python3 test_models.py

# Test configuration system
source ~/.venv-tui/bin/activate && python3 test_config.py

# Test state management and sessions
source ~/.venv-tui/bin/activate && python3 test_state.py

# Test MTGA log parser (mock data)
source ~/.venv-tui/bin/activate && python3 test_parser.py

# Test data persistence layer
source ~/.venv-tui/bin/activate && python3 test_data.py

# Test event mode (EventDefinition/EventRun/EventSession, state/data managers)
source ~/.venv-tui/bin/activate && python3 test_event_models.py

# Or run the whole suite through pytest (used in CI)
source ~/.venv-tui/bin/activate && pip install -r requirements-dev.txt
pytest test_models.py test_config.py test_state.py test_parser.py test_data.py test_event_models.py -v
```

### Linting & Formatting
```bash
# Check formatting (black) and lint (flake8) - same checks as CI
source ~/.venv-tui/bin/activate && pip install -r requirements-dev.txt
black --check .
flake8 .

# Auto-format
black .
```
Config lives in `pyproject.toml` (black) and `.flake8` (flake8). The
`manual/` directory is a separate standalone sub-project and is excluded
from both.

### Continuous Integration
GitHub Actions (`.github/workflows/ci.yml`) runs `black --check`, `flake8`,
and the pytest suite on every push and pull request against `main`.

### Visual Regression (SVG Snapshots)
`test_snapshots.py` uses `pytest-textual-snapshot` to render `main_tui.py`
(both the ranked screen and the event-mode screen) to SVG and compare
against committed "golden" files in `__snapshots__/test_snapshots/`. This
is what would have caught the "did you change the colorization?" question
automatically — any layout, text, or color change fails CI.
```bash
# Run snapshot checks (same as CI)
pytest test_snapshots.py -v

# After an intentional visual change, regenerate and commit the new goldens
pytest test_snapshots.py --snapshot-update
```
On a mismatch, CI uploads `snapshot_report.html` as a downloadable
workflow artifact showing an old/new/diff view.

### Real Log Analysis Tools
```bash
# Enhanced log viewer with parsing statistics
source ~/.venv-tui/bin/activate && python3 textual_log_viewer.py [log_file]

# Configure MTGA log file path
source ~/.venv-tui/bin/activate && python3 configure_log_path.py

# Analyze rank progression in logs
source ~/.venv-tui/bin/activate && python3 analyze_rank_progression.py

# Search for rank events
source ~/.venv-tui/bin/activate && python3 find_rank_events.py
```

### Installation
```bash
# Set up virtual environment (recommended)
python3 -m venv ~/.venv-tui
source ~/.venv-tui/bin/activate
pip install -r requirements.txt

# Or use existing venv
source ~/.venv-tui/bin/activate
```

### Project Structure
```
mythic-tracker-tui/
├── .github/workflows/   # CI (black, flake8, pytest)
├── src/
│   ├── models/          # Data structures (rank, game, session, event)
│   ├── config/          # Configuration management
│   ├── core/            # State management, data persistence (ranked + event)
│   ├── parsers/         # MTGA log parsing
│   └── ui/              # TUI framework components
├── manual/              # Separate standalone manual-entry sub-project (own CLAUDE.md/README)
├── main_tui.py          # ⭐ MAIN APPLICATION - Professional TUI (incl. event mode)
├── events.json           # Hand-edited event catalog (Historic Pauper Challenge, etc.)
├── textual_log_viewer.py # Enhanced log browser with statistics
├── mtga-test-logs/      # Real MTGA log files for testing
├── test_*.py            # Test files for each component
├── configure_log_path.py # MTGA log path configuration
├── analyze_*.py         # Log analysis tools
├── requirements.txt     # Runtime Python dependencies
├── requirements-dev.txt # + pytest, black, flake8
├── pyproject.toml       # black config
├── .flake8              # flake8 config
└── CLAUDE.md            # This documentation
```

## Configuration

### Default Paths
- **Config**: `~/.config/mtga-tracker/config.json`
- **Sessions**: `~/.config/mtga-tracker/sessions/`
- **Logs**: `~/.config/mtga-tracker/logs/`
- **State**: `~/.config/mtga-tracker/state.json`

### Key Settings
- `ui.demotion_threshold`: Losses needed for division demotion (default: 3)
- `mtga.log_file_path`: Path to MTGA log file (auto-detected)
- `tracking.common_decks`: List of common deck archetypes
- `ui.theme`: UI theme name (dark/light/custom)

## MTG Arena Rank System

### Tier Progression
Bronze → Silver → Gold → Platinum → Diamond → Mythic

### Key Mechanics Implemented
- **Tier Floors**: Once you reach a tier, you can't drop below it
- **Demotion Protection**: Need 3+ consecutive losses at 0 pips to drop divisions
- **Pip System**: 6 pips per division, 4 divisions per tier
- **Mythic Percentage**: Percentile-based ranking for Mythic tier

### Rank Model Features
```python
# Promotion logic
new_rank = rank.add_pips(2)

# Demotion with protection
new_rank = rank.remove_pips(1)

# Tier floor protection
gold_rank.remove_pips(100)  # Stays in Gold
```

## Session Management

### Session Lifecycle
1. **Start** - Create new session with format and starting rank
2. **Track** - Add games as they're played
3. **Pause/Resume** - Interrupt and continue sessions
4. **End** - Finalize and save session data

### Crash Recovery
- App state saved automatically to `state.json`
- Resume interrupted sessions on restart
- Live game state preserved across restarts

## Log Parsing

### Real Log Format Discovered
**Actual MTGA log structure analyzed from real game logs:**
- **JSON Lines**: Direct JSON objects (no timestamps in brackets)  
- **GRE Events**: `greToClientEvent` → `greToClientMessages` array
- **Unity Logs**: `[UnityCrossThreadLogger]` format with embedded JSON
- **Rank Events**: `RankGetCombinedRankInfo` and `RankGetSeasonAndRankDetails`

### Rank Data Format (Real)
```json
{
  "constructedClass": "Platinum",     // Tier name
  "constructedLevel": 4,              // Division (1-4) 
  "constructedStep": 5,               // Pips within division
  "constructedMatchesWon": 68,        // Total wins
  "constructedMatchesLost": 53        // Total losses
}
```

### Real Rank Progression Found ✅
**Verified actual rank progression in test logs:**
- Plat 4 (5/6 pips) → Plat 3 
- Record: 68W-53L → 69W-53L (lost game, then won game)
- Confirms: Lost (Plat 3→4), Won (Plat 4→3) - exact user scenario

### Enhanced Log Parsing Insights (Updated)

From analyzing the real logs, we've discovered:

1. **Event Structure**: Most events are JSON lines starting with `{`
2. **GRE Events**: Game Rules Engine events contain `greToClientEvent` with nested messages
3. **Game State**: Life totals, game stages, and match states are in `GREMessageType_GameStateMessage`
4. **Die Rolls**: Play/draw determination is in `GREMessageType_DieRollResultsResp`
5. **Unity Logs**: Secondary format with `[UnityCrossThreadLogger]` prefix
6. **Timestamps**: Unix timestamps in milliseconds in `timestamp` field
7. **Transaction Events**: System events have `transactionId` field
8. **Inventory Updates**: Collection/economy data in `InventoryInfo` structure
9. **Rank Detection**: Keywords like 'rank', 'tier', 'platinum', 'gold', 'mythic' reliably identify rank-related events

### Supported Events (Enhanced for Production)
- **Game State**: `GRE_GREMessageType_GameStateMessage`, `GRE_GREMessageType_DieRollResultsResp`  
- **Rank Updates**: `RankInfo_Constructed`, `RankInfo_Limited`
- **Match Events**: `MatchRoomEvent`, `MatchResult_*`, `GameResult`
- **Game Results**: `GameStage_GameOver`, match completion detection, win/loss parsing
- **Unity Events**: `Unity_*` (rank events, system events)
- **System Events**: `Transaction`, `InventoryUpdate` (gems, gold, wildcards)
- **Collection Data**: `DeckCollection` (173+ decks), `QuestUpdate`, `PeriodicRewards`
- **Progress Tracking**: `ProgressNodes`, `MilestoneProgress`
- **Text Parsing**: `LineResult_Win/Loss`, keyword-based detection
- **Statistics**: Comprehensive parsing stats with event type breakdown

## Data Models

### Core Models
- **Rank**: Tier, division, pips, demotion protection
- **Game**: Result, play/draw, decks, notes, rank changes  
- **Session**: Games collection, statistics, duration
- **AppState**: Current session, live game state, crash recovery

### Validation
All models use Pydantic for type safety and validation.

## Planned UI Layout

```
┌─────────────────── MTGA Mythic TUI Session Tracker ───────────────────┐
│  Session: 2025-08-10 15:30  │  Format: Standard  │  Status: ●          │
│                                                                        │
│ ┌─ Current Game ─────────────┐ ┌─ Game History ──────────────────────┐ │
│ │  Turn: 7                   │ │ [15:29] W Draw Esper vs Mono-Red   │ │
│ │  You: 18 ♥  │  Opp: 12 ♥   │ │  Good curves, stuck them on 2      │ │
│ │  Cards: 3   │  Cards: 5    │ │ ──────────────────────────────────── │ │
│ └────────────────────────────┘ │ [15:25] L Play Esper vs Esper Ctrl │ │
│                                │  Flooded out, 6 lands              │ │
│ ┌─ Rank Progress ────────────┐ │ ──────────────────────────────────── │ │
│ │  Mythic [███][███][   ] 60%│ │ ↑↓ Scroll  [E]dit [N]ote [D]eck     │ │
│ │                            │ └─────────────────────────────────────┘ │
│ │  Diamond [███][███][███].. │                                         │
│ │  Plat    [███][███][   ].. │                                         │
│ └────────────────────────────┘                                         │
│  [Tab] Switch Panels  [S]tart  [E]nd  [Q]uit                          │
└────────────────────────────────────────────────────────────────────────┘
```

## Development Notes

### Testing Strategy
- Each component has dedicated test file
- Mock data for external dependencies (MTGA logs)
- Comprehensive validation testing
- State persistence testing with temp directories

### Code Quality
- Type hints throughout
- Pydantic validation for all data models
- Error handling for file I/O and parsing
- Clear separation of concerns

### Next Steps (Future Development)
1. **Real-time Log Monitoring** - Implement file watching for live game updates
2. **Session Data Persistence** - Connect session models to file storage
3. **Advanced Statistics** - Win rate by deck type, matchup analysis
4. **Theme Customization** - Multiple color schemes and layouts  
5. **Export Features** - Session reports, CSV exports
6. **Integration Testing** - End-to-end testing with real MTGA sessions

## Application Status: 🎯 **PRODUCTION READY**
The core TUI application is fully functional and ready for daily use by MTG Arena players tracking ranked sessions.

## Development Session Tracking

### Vibe Coding Sessions
| Date | Duration | Features Completed | Notes |
|------|----------|-------------------|-------|
| 2025-08-10 | 1h 32min | Core Models, Config System, State Management, Log Parser Framework, Real Log Analysis, Textual Log Viewer TUI | ✅ Architecture + Real MTGA Log Integration Complete |
| 2025-08-10 (cont.) | +45min | Enhanced Log Parser (Match Results), TUI Layout Optimization, Bug Fixes | ✅ Win/Loss Detection, Scrollable Details, Usage Limit Reset |
| 2025-08-10 (final) | +35min | Main TUI Implementation, CLI Args, Configuration Screen, Import Fixes | ✅ **FULL WORKING APPLICATION** with professional interface |
| 2025-08-11 | 15min | Configuration Screen Bug Fix | ✅ Fixed Pydantic object access in ConfigurationScreen - replaced dict.get() with attribute access |
| 2025-08-12 | 1h 30min | Boss Fight Indicators, Goal System, Stats Editing, BO1/BO3 Support, Timer Improvements | ✅ Manual TUI enhancements, format switching, real-time timers, keybinding reorganization |
| 2025-08-13 | 1h 15min | Advanced Timer Systems, Milestone Celebrations, Dual Time Tracking | ✅ Game timer, pause/resume, milestone toasts, dual time tracking, error fixes |
| 2026-07-13 | TBD | Docs Cleanup, Test Suite Hardening (real assertions), Parser Bug Fixes, black/flake8, GitHub Actions CI, Event Mode (Historic Pauper Challenge), Ranked Session Bug Fixes | ✅ Removed stale prompt-logging instructions; converted print-only test scripts into real pytest tests; fixed a real event-type corruption bug in the log parser; added lint tooling and CI; added a parallel event/run tracking system (win/loss-capped runs, prize tables, milestones, profit calc) with its own models, state/data managers, and a new TUI screen, verified end-to-end via Textual's headless pilot harness; fixed main_tui.py's ranked Start/Pause/End Session flow, which never matched the real Session/StateManager/AppState APIs (wrong constructor args, wrong method signatures, `current_session` vs `active_session`, and an `AppState.has_active_session()` misuse that broke pause/resume) |

### Session Metrics
- **Total Development Time**: 5h 52min+
- **Features Completed**: 12/12 major components ✅
- **Test Coverage**: All core components have dedicated test files  
- **Architecture Stability**: ✅ Complete - Production-ready TUI application

### Time Tracking Notes
- Add completed session duration and accomplishments after each coding session
- Track both development time and feature velocity
- Note any architectural decisions or technical debt