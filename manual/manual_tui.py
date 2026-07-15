#!/usr/bin/env python3
"""
MTGA Mythic TUI Session Tracker (Manual) - Standalone Version
Complete manual rank tracking with no external dependencies.
"""

import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Union, Tuple
from enum import Enum
import asyncio
import os
from dataclasses import dataclass, asdict

from textual.app import App, ComposeResult
from textual.widgets import Static, Input, Button, Label, Footer, Select, TextArea, DataTable
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen, ModalScreen
from textual.reactive import reactive
from textual.binding import Binding
from textual.message import Message

# Import models from our new modules
from models import FormatType, RankTier, ManualRank, CompletedSession, SessionStats, AppData
from models import (
    EventDefinition,
    EventGame,
    EventGameResult,
    EventRun,
    EventRunStatus,
    EventStats,
    default_catalog_path,
    load_event_catalog,
)
from storage import StateManager

# === MODELS === (NOW IMPORTED FROM models/ PACKAGE)
# Previously contained duplicate FormatType, RankTier, ManualRank, SessionStats, AppData classes
# All model classes have been moved to models/ package and imported at top of file

# === STATE PERSISTENCE === (NOW IMPORTED FROM storage/ PACKAGE)
# Previously contained StateManager class - moved to storage/state_manager.py

# === TEXTUAL WIDGETS ===

class EditableText(Static):
    """Custom inline editable text widget."""
    
    def __init__(self, initial_value: str = "", **kwargs):
        super().__init__(**kwargs)
        self.initial_value = initial_value
        self.is_editing = False
    
    def compose(self) -> ComposeResult:
        yield Label(self.initial_value, classes="editable-display")
        yield Input(value=self.initial_value, classes="editable-input hidden")
    
    def on_mount(self) -> None:
        self._label = self.query_one(".editable-display", Label)
        self._input = self.query_one(".editable-input", Input)
    
    def on_click(self) -> None:
        """Handle click to enter edit mode."""
        if not self.is_editing:
            self.enter_edit_mode()
    
    def enter_edit_mode(self):
        """Switch to editing mode."""
        self.is_editing = True
        self._input.value = str(self._label.renderable)
        self._label.add_class("hidden")
        self._input.remove_class("hidden")
        self._input.focus()
    
    def exit_edit_mode(self):
        """Switch back to display mode."""
        self.is_editing = False
        self._label.update(self._input.value)
        self._input.add_class("hidden")
        self._label.remove_class("hidden")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input == self._input and self.is_editing:
            self.exit_edit_mode()
    
    def on_key(self, event) -> None:
        if event.key == "escape" and self.is_editing:
            self._input.value = str(self._label.renderable)  # Reset
            self.exit_edit_mode()
    
    @property
    def value(self) -> str:
        """Get current value."""
        return self._input.value if self.is_editing else str(self._label.renderable)

class TopPanel(Static):
    """Top panel with season info, current status, and session overview
    (ranked), or event/entry/run/milestone info (Event Mode)."""

    def __init__(self, app_data: AppData, event_catalog: Optional[List[EventDefinition]] = None):
        super().__init__()
        self.app_data = app_data
        self.event_catalog = event_catalog or []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="top-panel-layout"):
            # Column 1 - Season countdown (ranked) / Event name (event mode)
            yield Static("🕐 Season: Loading...", classes="top-season")

            # Column 2 - Format (ranked) / Entry cost (event mode)
            yield Static("📊 BO1", classes="top-format")

            # Column 3 - Bars remaining (ranked) / Run record (event mode)
            yield Static("🎯 BARS: --", classes="top-bars")

            # Column 4 - Current rank (ranked) / Milestone (event mode)
            yield Static("📍 Loading...", classes="top-rank")

    def on_mount(self) -> None:
        """Update display when mounted."""
        self.update_display()

    def update_display(self):
        """Update top panel display for whichever view mode is active."""
        if self.app_data.view_mode == "event":
            self._update_event_display()
        else:
            self._update_ranked_display()

    def _update_event_display(self):
        """Update the top panel for Event Mode: event name, entry cost,
        current run record, and highest milestone reached this run."""
        event = _get_event_for_stats(self.app_data.event_stats, self.event_catalog)
        run = self.app_data.event_stats.current_run

        if not event:
            season_content = "🎮 No events configured"
            format_content = "💰 Entry: --"
            bars_content = "🎮 No active run"
            rank_content = "🏅 --"
        else:
            season_content = f"🎮 {event.name} ({event.format})"

            if run and run.entry_currency:
                option = event.get_entry_option(run.entry_currency)
                amount = option.amount if option else "?"
                format_content = f"💰 Entry: {amount} {run.entry_currency}"
            else:
                costs = [f"{opt.amount} {opt.currency}" for opt in event.entry_options]
                format_content = f"💰 Entry: {' / '.join(costs)}" if costs else "💰 Entry: --"

            if run:
                bars_content = f"🎮 Record: {run.wins}W-{run.losses}L"
            else:
                bars_content = "🎮 No active run"

            if run:
                milestone = run.highest_milestone(event)
                rank_content = f"🏅 {milestone.name if milestone else 'None yet'}"
            else:
                rank_content = "🏅 --"

        try:
            self.query_one(".top-season", Static).update(season_content)
            self.query_one(".top-format", Static).update(format_content)
            self.query_one(".top-bars", Static).update(bars_content)
            self.query_one(".top-rank", Static).update(rank_content)
        except Exception:
            pass  # Ignore if widgets not found during startup

    def _update_ranked_display(self):
        """Update the top panel for the ranked ladder (original behavior)."""
        current_rank = self.app_data.get_current_rank()
        format_name = self.app_data.current_format.value.upper()
        stats = self.app_data.stats
        
        # Column 1 - Season countdown with end date
        season_text = "--"
        season_date = ""
        if stats.season_end_date:
            time_left = stats.season_end_date - datetime.now()
            if time_left.total_seconds() > 0:
                days = time_left.days
                hours = time_left.seconds // 3600
                minutes = (time_left.seconds % 3600) // 60
                seconds = time_left.seconds % 60
                if days > 0:
                    season_text = f"{days:02d}d {hours:02d}h {minutes:02d}m {seconds:02d}s"
                else:
                    season_text = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
                # Format the end date 
                season_date = f"[{stats.season_end_date.strftime('%b %d %I:%M%p')}]"
            else:
                season_text = "ENDED"
        
        season_content = f"🕐 Season: {season_text} {season_date}"
        
        # Column 2 - Format
        format_content = f"📊 {format_name}"
        
        # Column 3 - Bars remaining or Mythic trophy
        if current_rank.is_mythic():
            bars_content = f"🏆 [rgb(255,140,0)]MYTHIC[/rgb(255,140,0)]"
        else:
            bars_remaining = current_rank.get_total_bars_remaining_to_mythic()
            bars_content = f"🎯 BARS: {bars_remaining}"
        
        # Column 4 - Current rank
        tier_name = current_rank.tier.value if hasattr(current_rank.tier, 'value') else current_rank.tier
        rank_text = f"{tier_name} {current_rank.division or 1} ({current_rank.pips}/{current_rank.max_pips})"
        if current_rank.is_mythic():
            if current_rank.mythic_rank:
                rank_text = f"[rgb(255,140,0)]Mythic[/rgb(255,140,0)] #{current_rank.mythic_rank}"
            else:
                rank_text = f"[rgb(255,140,0)]Mythic[/rgb(255,140,0)] {current_rank.mythic_percentage:.1f}%" if current_rank.mythic_percentage else "[rgb(255,140,0)]Mythic[/rgb(255,140,0)]"
        
        rank_content = f"📍 {rank_text}"
        
        # Update the four columns
        try:
            season_widget = self.query_one(".top-season", Static)
            season_widget.update(season_content)
            
            format_widget = self.query_one(".top-format", Static)
            format_widget.update(format_content)
            
            bars_widget = self.query_one(".top-bars", Static)
            bars_widget.update(bars_content)
            
            rank_widget = self.query_one(".top-rank", Static)
            rank_widget.update(rank_content)
        except:
            pass  # Ignore if widgets not found during startup

class RankProgressPanel(Static):
    """Left panel showing interactive rank progression."""
    
    def __init__(self, app_data: AppData):
        super().__init__()
        self.app_data = app_data
    
    def compose(self) -> ComposeResult:
        current_rank = self.app_data.get_current_rank()
        format_name = self.app_data.current_format.value
        
        with Vertical():
            yield Static(f"─ [{format_name.upper()}] Rank Progress ─", classes="panel-header")
            
            # Show mythic display if mythic is achieved and enabled
            if current_rank.tier == RankTier.MYTHIC and self.app_data.show_mythic_progress:
                yield Static("")  # Empty line for spacing
                yield self._create_mythic_display(current_rank)
                yield Static("─" * 30, classes="separator")
            else:
                yield Static("─" * 30, classes="separator")
            
            # Always show rank bars
            yield self._create_rank_bars()
            
            yield Static("─" * 30, classes="separator")
    
    def _create_mythic_display(self, rank: ManualRank) -> Static:
        """Create Mythic achievement display."""
        if rank.mythic_rank:
            current_text = f"Current: #{rank.mythic_rank}"
        else:
            current_text = f"Current: {rank.mythic_percentage:.1f}%" if rank.mythic_percentage else "Current: --"
        
        return Static(f"""🏆 [rgb(255,140,0)]MYTHIC ACHIEVED![/rgb(255,140,0)] 🏆

{current_text}""", classes="mythic-display")
    
    def _create_rank_bars(self) -> Static:
        """Create rank progression bars as a single text widget."""
        current_rank = self.app_data.get_current_rank()
        
        # Build text display
        lines = []
        
        # Boss fight indicator
        if current_rank.is_boss_fight():
            next_tier = current_rank.next_tier()
            lines.append(f"🔥 [bold red]BOSS FIGHT![/bold red] Next win → [bold]{next_tier}[/bold]! 🔥")
            lines.append("")  # Empty line for spacing
        
        # Highest achieved rank indicator
        if self.app_data.stats.season_highest_rank:
            highest_rank = self.app_data.stats.season_highest_rank
            
            # Handle case where it might be a dict (backwards compatibility)
            if isinstance(highest_rank, dict):
                try:
                    highest_rank = ManualRank(**highest_rank)
                    self.app_data.stats.season_highest_rank = highest_rank  # Fix it for next time
                except:
                    highest_rank = None  # Skip display if conversion fails
            
            if highest_rank and highest_rank.is_mythic():
                if highest_rank.mythic_rank:
                    highest_text = f"👑 Season High: Mythic #{highest_rank.mythic_rank}"
                else:
                    highest_text = f"👑 Season High: Mythic {highest_rank.mythic_percentage:.1f}%"
            else:
                tier_name = highest_rank.tier.value if hasattr(highest_rank.tier, 'value') else highest_rank.tier
                highest_text = f"⭐ Season High: {tier_name} {highest_rank.division} ({highest_rank.pips}/{highest_rank.max_pips})"
            
            lines.append(f"[bold cyan]{highest_text}[/bold cyan]")
            
            # Season Current right below Season High
            if current_rank.is_mythic():
                if current_rank.mythic_rank:
                    current_text = f"📍 Season Current: Mythic #{current_rank.mythic_rank}"
                else:
                    current_text = f"📍 Season Current: Mythic {current_rank.mythic_percentage:.1f}%"
            else:
                tier_name = current_rank.tier.value if hasattr(current_rank.tier, 'value') else current_rank.tier
                current_text = f"📍 Season Current: {tier_name} {current_rank.division} ({current_rank.pips}/{current_rank.max_pips})"
            
            lines.append(f"[bold white]{current_text}[/bold white]")
            lines.append("")  # Empty line for spacing
        
        # All rank tiers from Mythic down to Bronze
        tier_order = list(RankTier)
        tier_order.reverse()  # Mythic at top
        
        for tier in tier_order:
            # Skip hidden tiers entirely
            if tier in self.app_data.hidden_tiers:
                continue
                
            if tier == RankTier.MYTHIC:
                # Show mythic with just percentage/rank, no bars
                if current_rank.tier == RankTier.MYTHIC:
                    if current_rank.mythic_rank:
                        mythic_display = f"#{current_rank.mythic_rank}"
                    else:
                        mythic_display = f"{current_rank.mythic_percentage:.1f}%" if current_rank.mythic_percentage else "0%"
                    
                    # Highlight mythic if it's current rank
                    tier_color = self._get_tier_color(RankTier.MYTHIC)
                    mythic_text = f"[black on {tier_color}]Mythic   [/black on {tier_color}]"
                    lines.append(f"{mythic_text} {mythic_display}")
                else:
                    lines.append("Mythic    --")
            else:
                # Check if this tier should be collapsed
                if tier in self.app_data.collapsed_tiers:
                    tier_color = self._get_tier_color(tier)
                    lines.append(f"{tier.value:<9}   [{tier_color}][██████████████████████][/{tier_color}]")
                else:
                    # Show all 4 divisions for this tier
                    for div in range(1, 5):
                        bars = self._create_bar_display(tier, div, current_rank)
                        # Only show goal marker if goal not yet achieved
                        goal_marker = ""
                        if self._is_goal_rank(tier, div):
                            current_rank = self.app_data.get_current_rank()
                            stats = self.app_data.stats
                            goal_attained = self._is_goal_attained(current_rank, stats.session_goal_tier, stats.session_goal_division)
                            if not goal_attained:
                                goal_marker = " ←GOAL"
                        
                        
                        # Highlight current position with tier-colored background
                        if tier == current_rank.tier and div == current_rank.division:
                            tier_color = self._get_tier_color(tier)
                            tier_text = f"[black on {tier_color}]{tier.value:<9}[/black on {tier_color}]"
                            div_text = f"[black on {tier_color}]{div}[/black on {tier_color}]"
                            
                            # Add boss fight indicator to current tier line
                            boss_marker = " ⚔️ [bold red]BOSS TIER![/bold red]" if current_rank.is_boss_fight() else ""
                        else:
                            tier_text = f"{tier.value:<9}"
                            div_text = f"{div}"
                            boss_marker = ""
                        
                        lines.append(f"{tier_text} {div_text} {bars}{goal_marker}{boss_marker}")
        
        return Static("\n".join(lines), classes="rank-bars")
    
    def _create_bar_display(self, tier: RankTier, division: int, current_rank: ManualRank) -> str:
        """Create bar display showing current progress vs highest achieved."""
        # Use the app's current format to determine bar count
        max_pips = 6 if self.app_data.current_format in [FormatType.CONSTRUCTED_BO1, FormatType.CONSTRUCTED_BO3] else 4
        bars = []
        
        # Get current progress for this tier/division
        current_pips = 0
        if tier == current_rank.tier and division == current_rank.division:
            current_pips = current_rank.pips
        elif self._is_position_filled(tier, division, current_rank):
            current_pips = max_pips  # Fully completed
        
        # Get highest achieved progress for this tier/division
        highest_pips = 0
        if self.app_data.stats.season_highest_rank:
            highest_rank = self.app_data.stats.season_highest_rank
            
            # Handle case where it might be a dict (backwards compatibility)
            if isinstance(highest_rank, dict):
                try:
                    highest_rank = ManualRank(**highest_rank)
                    self.app_data.stats.season_highest_rank = highest_rank
                except:
                    highest_rank = None
            
            if highest_rank:
                if tier == highest_rank.tier and division == highest_rank.division:
                    highest_pips = highest_rank.pips
                elif self._is_position_filled_for_rank(tier, division, highest_rank):
                    highest_pips = max_pips  # Fully completed by highest rank
        
        # Create visual representation: current [██] vs highest [░░] vs empty [  ]
        tier_color = self._get_tier_color(tier)
        
        for i in range(max_pips):
            if i < current_pips:
                # Current progress - solid bars with tier color
                bars.append(f"[{tier_color}][██][/{tier_color}]")
            elif i < highest_pips:
                # Highest achieved beyond current - light gray bars
                bars.append("[rgb(128,128,128)][░░][/rgb(128,128,128)]")
            else:
                # Not achieved - empty
                bars.append("[  ]")
        
        return "".join(bars)
    
    def _get_tier_color(self, tier: RankTier) -> str:
        """Get the color for a specific tier."""
        tier_colors = {
            RankTier.BRONZE: "rgb(139,69,19)",    # Bronze
            RankTier.SILVER: "rgb(192,192,192)",  # Silver
            RankTier.GOLD: "rgb(255,215,0)",      # Gold
            RankTier.PLATINUM: "rgb(0,206,209)",  # Cyan/Teal
            RankTier.DIAMOND: "rgb(138,43,226)",  # Royal purple
            RankTier.MYTHIC: "rgb(255,140,0)"     # True planeswalker orange
        }
        return tier_colors.get(tier, "white")
    
    def _is_position_filled(self, tier: RankTier, division: int, current_rank: ManualRank) -> bool:
        """Check if a rank position should be displayed as filled."""
        # Don't try to fill mythic bars - mythic doesn't have bars
        if tier == RankTier.MYTHIC:
            return False
            
        # If current rank is mythic, all non-mythic positions are filled
        if current_rank.is_mythic():
            return True
        
        tier_order = list(RankTier)[:-1]  # Exclude Mythic
        current_tier_idx = tier_order.index(current_rank.tier)
        check_tier_idx = tier_order.index(tier)
        
        # Lower tiers are filled
        if check_tier_idx < current_tier_idx:
            return True
        
        # Same tier, lower divisions are filled
        if check_tier_idx == current_tier_idx and division > current_rank.division:
            return True
        
        return False
    
    def _is_position_filled_for_rank(self, tier: RankTier, division: int, rank: ManualRank) -> bool:
        """Check if a rank position should be displayed as filled for a specific rank."""
        # Don't try to fill mythic bars - mythic doesn't have bars
        if tier == RankTier.MYTHIC:
            return False
            
        # If the rank is mythic, all non-mythic positions are filled
        if rank.is_mythic():
            return True
        
        tier_order = list(RankTier)[:-1]  # Exclude Mythic
        rank_tier_idx = tier_order.index(rank.tier)
        check_tier_idx = tier_order.index(tier)
        
        # Lower tiers are filled
        if check_tier_idx < rank_tier_idx:
            return True
        
        # Same tier, lower divisions are filled
        if check_tier_idx == rank_tier_idx and division > rank.division:
            return True
        
        return False
    
    def _is_goal_rank(self, tier: RankTier, division: int) -> bool:
        """Check if this is the session goal rank."""
        stats = self.app_data.stats
        return (stats.session_goal_tier == tier and 
                stats.session_goal_division == division)
    
    def _is_highest_rank(self, tier: RankTier, division: int) -> bool:
        """Check if this is the season highest achieved rank."""
        stats = self.app_data.stats
        if not stats.season_highest_rank:
            return False
        
        highest_rank = stats.season_highest_rank
        
        # Handle case where it might be a dict (backwards compatibility)
        if isinstance(highest_rank, dict):
            try:
                highest_rank = ManualRank(**highest_rank)
                stats.season_highest_rank = highest_rank  # Fix it for next time
            except:
                return False
        
        if not highest_rank:
            return False
            
        return (highest_rank.tier == tier and highest_rank.division == division)
    
    def _is_goal_attained(self, current_rank: ManualRank, goal_tier, goal_division) -> bool:
        """Check if the session goal has been attained."""
        if not goal_tier:
            return False
            
        # Handle mythic goal
        if goal_tier == RankTier.MYTHIC or str(goal_tier) == "Mythic":
            return current_rank.is_mythic()
            
        # Compare tier and division
        current_tier_str = current_rank.tier.value if hasattr(current_rank.tier, 'value') else str(current_rank.tier)
        goal_tier_str = goal_tier.value if hasattr(goal_tier, 'value') else str(goal_tier)
        
        tier_order = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        
        try:
            current_tier_idx = tier_order.index(current_tier_str)
            goal_tier_idx = tier_order.index(goal_tier_str)
            
            # Higher tier achieved
            if current_tier_idx > goal_tier_idx:
                return True
                
            # Same tier, check division (lower division number = higher rank)
            if current_tier_idx == goal_tier_idx:
                return current_rank.division <= goal_division
                
        except ValueError:
            pass
            
        return False

class StatsPanel(Static):
    """Right panel showing session and season statistics."""
    
    def __init__(self, app_data: AppData):
        super().__init__()
        self.app_data = app_data
    
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("─ Session & Season Stats ─", classes="panel-header")
            
            # Session goal
            yield self._create_goal_section()
            yield Static("─" * 30, classes="separator")
            
            # Current session
            yield self._create_session_section()
            yield Static("─" * 30, classes="separator")
            
            # Season totals
            yield self._create_season_section()
            yield Static("─" * 30, classes="separator")
            
            # Session history
            yield self._create_history_section()
            yield Static("─" * 30, classes="separator")
    
    def _create_goal_section(self) -> Static:
        """Create session goal section."""
        stats = self.app_data.stats
        if stats.session_goal_tier:
            tier_name = stats.session_goal_tier.value if hasattr(stats.session_goal_tier, 'value') else stats.session_goal_tier
            
            # Handle mythic goal (no division) 
            if stats.session_goal_tier == RankTier.MYTHIC or str(stats.session_goal_tier) == "Mythic":
                goal_text = "Mythic"
            else:
                goal_text = f"{tier_name} {stats.session_goal_division or 4}"
            
            # Check if goal is attained
            current_rank = self.app_data.get_current_rank()
            goal_attained = self._is_goal_attained(current_rank, stats.session_goal_tier, stats.session_goal_division)
            
            if goal_attained:
                return Static(f"🎯 SESSION GOAL: [{goal_text}] ✅ ACHIEVED!", classes="goal-section")
            else:
                return Static(f"🎯 SESSION GOAL: [{goal_text}] [G] Change", classes="goal-section")
        else:
            return Static("🎯 SESSION GOAL: [None]", classes="goal-section")
    
    def _is_goal_attained(self, current_rank: ManualRank, goal_tier, goal_division) -> bool:
        """Check if the session goal has been attained."""
        if not goal_tier:
            return False
            
        # Handle mythic goal
        if goal_tier == RankTier.MYTHIC or str(goal_tier) == "Mythic":
            return current_rank.is_mythic()
            
        # Compare tier and division
        current_tier_str = current_rank.tier.value if hasattr(current_rank.tier, 'value') else str(current_rank.tier)
        goal_tier_str = goal_tier.value if hasattr(goal_tier, 'value') else str(goal_tier)
        
        tier_order = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        
        try:
            current_tier_idx = tier_order.index(current_tier_str)
            goal_tier_idx = tier_order.index(goal_tier_str)
            
            # Higher tier achieved
            if current_tier_idx > goal_tier_idx:
                return True
                
            # Same tier, check division (lower division number = higher rank)
            if current_tier_idx == goal_tier_idx:
                return current_rank.division <= goal_division
                
        except ValueError:
            pass
            
        return False
    
    def _create_session_section(self) -> Static:
        """Create current session stats."""
        stats = self.app_data.stats
        format_name = self.app_data.current_format.value.upper()
        
        # Session timing (active time only, excluding paused time)
        duration_text = "00m 00s"
        pause_status = ""
        if stats.session_start_time:
            try:
                duration = stats.get_active_session_duration()
                total_seconds = int(duration.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                if hours > 0:
                    duration_text = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
                elif minutes > 0:
                    duration_text = f"{minutes:02d}m {seconds:02d}s"
                else:
                    duration_text = f"00m {seconds:02d}s"
                
                # Add pause indicator
                if stats.session_paused:
                    pause_status = " ⏸️ PAUSED"
                
            except:
                duration_text = "00m 00s"
        
        # Format start time safely
        start_time = "Not set"
        if stats.session_start_time:
            try:
                if isinstance(stats.session_start_time, str):
                    session_start = datetime.fromisoformat(stats.session_start_time)
                else:
                    session_start = stats.session_start_time
                start_time = session_start.strftime("%I:%M %p")
            except:
                start_time = "Invalid time"
        
        # Streak info
        if stats.current_win_streak > 0:
            streak_text = f"W{stats.current_win_streak}"
        elif stats.current_loss_streak > 0:
            streak_text = f"L{stats.current_loss_streak}"
        else:
            streak_text = "None"
        
        current_streak_text = f"{stats.current_win_streak} / L{stats.current_loss_streak}"
        
        # Time since last result - show both real and active time
        last_result_text = "No games yet"
        if stats.last_result_time:
            try:
                real_seconds, active_seconds = stats.get_time_since_last_result()
                
                # Format real time
                real_minutes = real_seconds // 60
                real_secs = real_seconds % 60
                real_text = f"{real_minutes:02d}m {real_secs:02d}s"
                
                # Format active time 
                active_minutes = active_seconds // 60
                active_secs = active_seconds % 60
                active_text = f"{active_minutes:02d}m {active_secs:02d}s"
                
                # Show both if different, otherwise just one
                if real_seconds != active_seconds:
                    last_result_text = f"{real_text} ago ({active_text} active)"
                else:
                    last_result_text = f"{real_text} ago"
                    
            except:
                last_result_text = "Invalid time"
        
        # Game timer info
        game_timer_text = ""
        avg_game_text = ""
        if stats.game_start_time:
            game_seconds = int(stats.get_current_game_duration())
            game_minutes = game_seconds // 60
            game_secs = game_seconds % 60
            game_timer_text = f"  Current: {game_minutes:02d}m {game_secs:02d}s ⏰"
        
        if stats.game_durations:
            avg_seconds = int(stats.get_average_game_duration())
            avg_minutes = avg_seconds // 60
            avg_secs = avg_seconds % 60
            avg_game_text = f"Avg Game: [{avg_minutes:02d}m {avg_secs:02d}s]  "
        
        # Generate L10 display (last 10 games)
        l10_display = ""
        if hasattr(stats, 'session_game_results') and stats.session_game_results:
            # Show last 10 games with emojis
            recent_games = stats.session_game_results[-10:]  # Get last 10
            game_emojis = []
            for result in recent_games:
                if result == 'W':
                    game_emojis.append('🟢')  # Green circle for win
                elif result == 'L':
                    game_emojis.append('🔴')  # Red circle for loss
                else:
                    game_emojis.append('⚪')  # White circle for unknown
            l10_display = f"L10: {''.join(game_emojis)}"
        else:
            l10_display = "L10: No games yet"

        session_content = self._generate_session_content()
        return Static(session_content, classes="session-section", id="session-section")
    
    def _create_season_section(self) -> Static:
        """Create season total stats."""
        stats = self.app_data.stats
        format_name = self.app_data.current_format.value.upper()
        
        start_rank = "Not set"
        if stats.season_start_rank:
            # Handle both string and rank object formats
            if hasattr(stats.season_start_rank, 'tier'):
                # It's a rank object - don't show pips for season start
                tier_name = stats.season_start_rank.tier.value if hasattr(stats.season_start_rank.tier, 'value') else stats.season_start_rank.tier
                start_rank = f"{tier_name} {stats.season_start_rank.division}"
            else:
                # It's just a string
                start_rank = str(stats.season_start_rank)
        
        # Force fresh calculation of win rate and total games
        total_games = stats.season_wins + stats.season_losses
        win_rate = (stats.season_wins / total_games * 100) if total_games > 0 else 0.0
        
        # Format highest rank achieved
        highest_text = "Not set"
        if stats.season_highest_rank:
            highest_rank = stats.season_highest_rank
            
            # Handle case where it might be a dict (backwards compatibility)
            if isinstance(highest_rank, dict):
                try:
                    highest_rank = ManualRank(**highest_rank)
                    stats.season_highest_rank = highest_rank  # Fix it for next time
                except:
                    highest_rank = None  # Skip display if conversion fails
            
            if highest_rank and highest_rank.is_mythic():
                if highest_rank.mythic_rank:
                    highest_text = f"Mythic #{highest_rank.mythic_rank} 👑"
                else:
                    highest_text = f"Mythic {highest_rank.mythic_percentage:.1f}% 👑"
            else:
                tier_name = highest_rank.tier.value if hasattr(highest_rank.tier, 'value') else highest_rank.tier
                # Create visual progress bar for highest rank
                progress_bar = ""
                for i in range(highest_rank.max_pips):
                    if i < highest_rank.pips:
                        progress_bar += "█"  # Full block
                    else:
                        progress_bar += "░"  # Light shade
                highest_text = f"{tier_name} {highest_rank.division} [{progress_bar}] ({highest_rank.pips}/{highest_rank.max_pips})"
        
        season_content = f"""🏆 SEASON TOTAL [{format_name}] ({total_games})
Record:   [{stats.season_wins}W] - [{stats.season_losses}L]  {win_rate:.2f}%"""
        
        return Static(season_content, classes="season-section", id="season-section")
    
    def _create_history_section(self) -> Static:
        """Create recent game notes section."""
        stats = self.app_data.stats
        
        # Dedicated notes section
        notes_lines = ["📝 RECENT NOTES"]
        
        if hasattr(stats, 'game_notes') and stats.game_notes:
            # Show last 6 notes (more space now) - most recent first
            recent_notes = stats.game_notes[-6:] if len(stats.game_notes) > 6 else stats.game_notes
            for note in reversed(recent_notes):
                # Handle timestamp safely with smart date/time display
                if 'timestamp' in note and isinstance(note['timestamp'], datetime):
                    now = datetime.now()
                    note_time = note['timestamp']
                    
                    # If note is from today, show just time. Otherwise show date + time
                    if note_time.date() == now.date():
                        time_str = note_time.strftime("%H:%M")
                    else:
                        time_str = note_time.strftime("%m/%d %H:%M")
                else:
                    time_str = "??:??"
                
                # Create summary line with note text inline
                result_icon = "🏆" if note.get('result') == 'Win' else "💀" if note.get('result') == 'Loss' else "❓"
                summary = f"[{time_str}] {result_icon} {note['play_draw']}"
                if note['opponent_deck']:
                    summary += f" vs {note['opponent_deck'][:15]}"  # More space for deck names
                
                # Add notes preview on same line if available
                if note['notes']:
                    preview = note['notes'][:25] + "..." if len(note['notes']) > 25 else note['notes']
                    summary += f" - {preview}"
                
                notes_lines.append(summary)
        else:
            notes_lines.append("No game notes yet")
            notes_lines.append("")
            notes_lines.append("[N] Add your first note!")
            notes_lines.append("")
            notes_lines.append("Track matchups, strategies, and")
            notes_lines.append("key moments from your games.")
        
        return Static("\n".join(notes_lines), classes="history-section")
    
    def _generate_session_content(self) -> str:
        """Generate session content string - single source of truth for session display."""
        stats = self.app_data.stats
        format_name = self.app_data.current_format.value.upper()
        
        # Session timing (active time only)
        duration_text = "00m 00s"
        pause_status = ""
        if stats.session_start_time:
            duration = stats.get_active_session_duration()
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            if hours > 0:
                duration_text = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
            elif minutes > 0:
                duration_text = f"{minutes:02d}m {seconds:02d}s"
            else:
                duration_text = f"00m {seconds:02d}s"
            
            # Add pause indicator
            if stats.session_paused:
                pause_status = " ⏸️ PAUSED"
        
        # Format start time safely
        start_time = "Not set"
        if stats.session_start_time:
            try:
                if isinstance(stats.session_start_time, str):
                    session_start = datetime.fromisoformat(stats.session_start_time)
                else:
                    session_start = stats.session_start_time
                start_time = session_start.strftime("%I:%M %p")
            except:
                start_time = "Invalid time"
        
        # Current streak info - show only the active streak
        if stats.current_win_streak > 0:
            wins = stats.current_win_streak
            current_streak_text = f"{wins} Win" if wins == 1 else f"{wins} Wins"
        elif stats.current_loss_streak > 0:
            losses = stats.current_loss_streak
            current_streak_text = f"{losses} Loss" if losses == 1 else f"{losses} Losses"
        else:
            current_streak_text = "New session"
        
        # Time since last result - show both real and active time
        last_result_text = "No games yet"
        if stats.last_result_time:
            try:
                real_seconds, active_seconds = stats.get_time_since_last_result()
                
                # Format real time
                real_minutes = real_seconds // 60
                real_secs = real_seconds % 60
                real_text = f"{real_minutes:02d}m {real_secs:02d}s"
                
                # Format active time 
                active_minutes = active_seconds // 60
                active_secs = active_seconds % 60
                active_text = f"{active_minutes:02d}m {active_secs:02d}s"
                
                # Show both if different, otherwise just one
                if real_seconds != active_seconds:
                    last_result_text = f"{real_text} ago ({active_text} active)"
                else:
                    last_result_text = f"{real_text} ago"
                    
            except:
                last_result_text = "Invalid time"
        
        # Game timer info
        game_timer_text = ""
        avg_game_text = ""
        if stats.game_start_time:
            game_seconds = int(stats.get_current_game_duration())
            game_minutes = game_seconds // 60
            game_secs = game_seconds % 60
            game_timer_text = f"  Current: {game_minutes:02d}m {game_secs:02d}s ⏰"
        
        if stats.game_durations:
            avg_seconds = int(stats.get_average_game_duration())
            avg_minutes = avg_seconds // 60
            avg_secs = avg_seconds % 60
            avg_game_text = f"Avg Game: [{avg_minutes:02d}m {avg_secs:02d}s]  "
        
        # Generate L10 display (last 10 games)
        l10_display = ""
        if hasattr(stats, 'session_game_results') and stats.session_game_results:
            # Show last 10 games with emojis
            recent_games = stats.session_game_results[-10:]  # Get last 10
            game_emojis = []
            for result in recent_games:
                if result == 'W':
                    game_emojis.append('🟢')  # Green circle for win
                elif result == 'L':
                    game_emojis.append('🔴')  # Red circle for loss
                else:
                    game_emojis.append('⚪')  # White circle for unknown
            l10_display = f"L10: {''.join(game_emojis)}"
        else:
            l10_display = "L10: No games yet"
        
        # Calculate total session games
        total_session_games = stats.session_wins + stats.session_losses
        
        return f"""📊 CURRENT SESSION [{format_name}] ({total_session_games})
Started:  [{start_time}]  Duration: {duration_text}{pause_status}
Record:   [{stats.session_wins}W] - [{stats.session_losses}L]  {stats.get_session_win_rate():.2f}%
{l10_display}
Streak:   {current_streak_text}
{avg_game_text}Last: {last_result_text}{game_timer_text}"""
    
    def _calculate_session_bar_progress(self, stats: SessionStats, current_rank: ManualRank) -> int:
        """Calculate how many bars gained/lost this session."""
        if not stats.session_start_rank:
            return 0
            
        # Get starting rank for this session
        start_rank = stats.session_start_rank
        if hasattr(start_rank, 'get_total_bars_remaining_to_mythic'):
            start_bars = start_rank.get_total_bars_remaining_to_mythic()
        else:
            start_bars = 0
            
        current_bars = current_rank.get_total_bars_remaining_to_mythic()
        
        # Progress = reduction in bars remaining (higher rank = fewer bars remaining)
        return start_bars - current_bars
    
    def refresh_session_section(self) -> None:
        """Refresh the session section with updated timer data."""
        try:
            session_section = self.query_one("#session-section", Static)
            session_content = self._generate_session_content()
            session_section.update(session_content)
        except:
            pass  # Ignore if section not found


def _get_event_for_stats(
    event_stats: EventStats, event_catalog: List[EventDefinition]
) -> Optional[EventDefinition]:
    """Look up the EventDefinition matching the currently-tracked event."""
    for event in event_catalog:
        if event.event_id == event_stats.event_id:
            return event
    return event_catalog[0] if event_catalog else None


class EventRunPanel(Static):
    """Left panel showing the current event run (Event Mode)."""

    def __init__(self, app_data: AppData, event_catalog: List[EventDefinition]):
        super().__init__()
        self.app_data = app_data
        self.event_catalog = event_catalog

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("─ Event Mode: Current Run ─", classes="panel-header")
            yield Static("─" * 30, classes="separator")
            yield self._create_run_section()
            yield Static("─" * 30, classes="separator")
            yield Static(
                "[U] Start Run  [W] Win  [L] Loss  [R] Restart Session  [V] Back to Ranked",
                classes="help-text",
            )

    def _create_run_section(self) -> Static:
        event = _get_event_for_stats(self.app_data.event_stats, self.event_catalog)
        if not event:
            return Static("No events configured in events.json", classes="session-section")

        run = self.app_data.event_stats.current_run
        lines = [f"🎮 {event.name} ({event.format})", ""]

        if not run:
            lines.append("No active run. Press [U] to start a new run.")
            return Static("\n".join(lines), classes="session-section")

        win_bars = "".join(
            "[rgb(255,215,0)][██][/rgb(255,215,0)]" if i < run.wins else "[  ]"
            for i in range(event.win_cap)
        )
        loss_bars = "".join(
            "[red][▓▓][/red]" if i < run.losses else "[  ]" for i in range(event.loss_cap)
        )

        lines.append(f"Deck: {run.player_deck or 'Unknown'}")
        if run.entry_currency:
            option = event.get_entry_option(run.entry_currency)
            amount = option.amount if option else "?"
            lines.append(f"Entry: {amount} {run.entry_currency}")
        lines.append(f"Wins:   {win_bars}")
        lines.append(f"Losses: {loss_bars}")
        lines.append("")
        lines.append(f"Record: {run.wins}-{run.losses}")

        prize = run.prize(event)
        lines.append(f"Prize so far: {prize.gems} gems, {prize.packs} packs")

        profit = run.net_profit_gems(event)
        if profit is not None:
            sign = "+" if profit >= 0 else ""
            lines.append(f"Net profit: {sign}{profit} gems")

        milestone = run.highest_milestone(event)
        lines.append(f"Milestone: {milestone.name if milestone else 'None yet'}")

        if run.status == EventRunStatus.ENDED:
            lines.append("")
            lines.append("[bold green]Run complete! Press [U] for a new run.[/bold green]")

        return Static("\n".join(lines), classes="session-section")


class EventStatsPanel(Static):
    """Right panel showing event session and all-time stats (Event Mode)."""

    def __init__(self, app_data: AppData, event_catalog: List[EventDefinition]):
        super().__init__()
        self.app_data = app_data
        self.event_catalog = event_catalog

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("─ Event Session & All-Time Stats ─", classes="panel-header")
            yield Static("─" * 30, classes="separator")
            yield self._create_session_section()
            yield Static("─" * 30, classes="separator")
            yield self._create_alltime_section()
            yield Static("─" * 30, classes="separator")

    def _create_session_section(self) -> Static:
        stats = self.app_data.event_stats
        lines = [
            "📊 CURRENT SESSION",
            f"Runs played: {stats.session_runs_played}",
            f"Record: [{stats.session_wins}W] - [{stats.session_losses}L]",
            f"Prize: {stats.session_gems} gems, {stats.session_packs} packs",
        ]
        if stats.session_milestone_counts:
            counts_str = ", ".join(f"{k}: {v}" for k, v in stats.session_milestone_counts.items())
            lines.append(f"Milestones: {counts_str}")
        return Static("\n".join(lines), classes="session-section")

    def _create_alltime_section(self) -> Static:
        stats = self.app_data.event_stats
        lines = [
            "🏆 ALL-TIME TOTAL",
            f"Runs played: {stats.alltime_runs_played}",
            f"Record: [{stats.alltime_wins}W] - [{stats.alltime_losses}L]",
            f"Prize: {stats.alltime_gems} gems, {stats.alltime_packs} packs",
        ]
        if stats.alltime_milestone_counts:
            counts_str = ", ".join(f"{k}: {v}" for k, v in stats.alltime_milestone_counts.items())
            lines.append(f"Milestones: {counts_str}")
        return Static("\n".join(lines), classes="season-section")


class EditStatsModal(ModalScreen):
    """Modal dialog for editing session/season stats."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    CSS = """
    EditStatsModal {
        align: center middle;
    }
    
    #stats-dialog {
        width: 90;
        height: 32;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    .stats-columns {
        height: 1fr;
    }
    
    .stats-column {
        width: 50%;
        padding: 0 1;
    }
    
    .stats-row {
        height: 3;
        margin: 0 0 1 0;
    }
    
    .stats-label {
        width: 16;
        content-align: right middle;
    }
    
    .stats-input {
        width: 1fr;
        margin-left: 1;
    }
    
    .modal-buttons {
        height: 4;
        margin-top: 2;
        content-align: center middle;
    }
    
    .modal-title {
        height: 3;
        text-style: bold;
        background: $primary;
        color: $text;
        content-align: center middle;
        margin-bottom: 1;
    }
    
    .column-header {
        text-style: bold;
        background: $primary;
        color: $text;
        margin-bottom: 1;
        content-align: center middle;
    }
    """
    
    def __init__(self, stats: 'SessionStats', **kwargs):
        super().__init__(**kwargs)
        self.stats = stats
        self.result = None
    
    def compose(self) -> ComposeResult:
        with Container(id="stats-dialog"):
            yield Label("Edit Session & Season Stats", classes="modal-title")
            
            # Two-column layout
            with Horizontal(classes="stats-columns"):
                # Left Column - Session Stats
                with Vertical(classes="stats-column"):
                    yield Label("📊 SESSION STATS", classes="column-header")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Session Start:", classes="stats-label")
                        start_time_str = self.stats.session_start_time.strftime("%H:%M") if self.stats.session_start_time else "14:00"
                        yield Input(value=start_time_str, id="session-start-input", placeholder="HH:MM", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Session Wins:", classes="stats-label")
                        yield Input(value=str(self.stats.session_wins), id="session-wins-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Session Losses:", classes="stats-label")
                        yield Input(value=str(self.stats.session_losses), id="session-losses-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Current Win Streak:", classes="stats-label")
                        yield Input(value=str(self.stats.current_win_streak), id="current-win-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Current Loss Streak:", classes="stats-label")
                        yield Input(value=str(self.stats.current_loss_streak), id="current-loss-input", placeholder="0", classes="stats-input")
                
                # Right Column - Season Stats
                with Vertical(classes="stats-column"):
                    yield Label("🏆 SEASON STATS", classes="column-header")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Season Wins:", classes="stats-label")
                        yield Input(value=str(self.stats.season_wins), id="season-wins-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Season Losses:", classes="stats-label")
                        yield Input(value=str(self.stats.season_losses), id="season-losses-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Best Win Streak:", classes="stats-label")
                        yield Input(value=str(self.stats.best_win_streak), id="best-win-input", placeholder="0", classes="stats-input")
                    
                    with Horizontal(classes="stats-row"):
                        yield Label("Worst Loss Streak:", classes="stats-label")
                        yield Input(value=str(self.stats.worst_loss_streak), id="worst-loss-input", placeholder="0", classes="stats-input")
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="save-btn", variant="success")
                yield Button("Cancel", id="cancel-btn", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_changes()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
    
    def _save_changes(self):
        """Save the edited values."""
        # Debug to file
        with open("debug.log", "a") as f:
            f.write(f"[{datetime.now()}] EditStatsModal _save_changes called\n")
        try:
            # Session start time
            session_start_str = self.query_one("#session-start-input", Input).value
            if session_start_str:
                hour, minute = map(int, session_start_str.split(":"))
                if self.stats.session_start_time:
                    new_start = self.stats.session_start_time.replace(hour=hour, minute=minute)
                else:
                    new_start = datetime.now().replace(hour=hour, minute=minute)
                self.stats.session_start_time = new_start
            
            # Session wins/losses
            session_wins_str = self.query_one("#session-wins-input", Input).value.strip()
            if session_wins_str.isdigit():
                self.stats.session_wins = int(session_wins_str)
            elif session_wins_str == "":
                self.stats.session_wins = 0
                
            session_losses_str = self.query_one("#session-losses-input", Input).value.strip()
            if session_losses_str.isdigit():
                self.stats.session_losses = int(session_losses_str)
            elif session_losses_str == "":
                self.stats.session_losses = 0
            
            # Current streaks
            current_win_str = self.query_one("#current-win-input", Input).value.strip()
            if current_win_str.isdigit():
                self.stats.current_win_streak = int(current_win_str)
            elif current_win_str == "":
                self.stats.current_win_streak = 0
                
            current_loss_str = self.query_one("#current-loss-input", Input).value.strip()
            if current_loss_str.isdigit():
                self.stats.current_loss_streak = int(current_loss_str)
            elif current_loss_str == "":
                self.stats.current_loss_streak = 0
            
            # Season wins/losses
            season_wins_str = self.query_one("#season-wins-input", Input).value.strip()
            if season_wins_str.isdigit():
                self.stats.season_wins = int(season_wins_str)
            elif season_wins_str == "":
                self.stats.season_wins = 0
                
            season_losses_str = self.query_one("#season-losses-input", Input).value.strip()
            if season_losses_str.isdigit():
                self.stats.season_losses = int(season_losses_str)
            elif season_losses_str == "":
                self.stats.season_losses = 0
            
            # Best win streak
            best_win_str = self.query_one("#best-win-input", Input).value.strip()
            if best_win_str.isdigit():
                self.stats.best_win_streak = int(best_win_str)
            elif best_win_str == "":
                self.stats.best_win_streak = 0
            
            # Worst loss streak
            worst_loss_str = self.query_one("#worst-loss-input", Input).value.strip()
            if worst_loss_str.isdigit():
                self.stats.worst_loss_streak = int(worst_loss_str)
            elif worst_loss_str == "":
                self.stats.worst_loss_streak = 0
            
            with open("debug.log", "a") as f:
                f.write(f"[{datetime.now()}] About to dismiss modal with result=saved. Season: {self.stats.season_wins}W-{self.stats.season_losses}L\n")
            self.dismiss("saved")
            
        except Exception as e:
            self.app.notify(f"Error saving stats: {e}", severity="error")
    
    def action_cancel(self) -> None:
        self.dismiss(None)

class SetGoalModal(ModalScreen):
    """Modal dialog for setting session goal with dropdowns."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, current_rank: ManualRank, format_type: FormatType, stats: 'SessionStats', **kwargs):
        super().__init__(**kwargs)
        self.current_rank = current_rank
        self.format_type = format_type
        self.stats = stats
        self.result = None
    
    def compose(self) -> ComposeResult:
        with Container(classes="goal-modal-container"):
            yield Static("Set Session Goal", classes="modal-title")
            yield Static(f"Current Rank: {self.current_rank}", classes="modal-subtitle")
            
            with Vertical(classes="modal-form"):
                # Tier dropdown
                tier_options = [(tier.value, tier.value) for tier in RankTier]
                if self.stats.session_goal_tier:
                    current_goal_tier = self.stats.session_goal_tier.value if hasattr(self.stats.session_goal_tier, 'value') else str(self.stats.session_goal_tier)
                else:
                    current_goal_tier = "Mythic"
                yield Static("Goal Tier:")
                yield Select(tier_options, value=current_goal_tier, id="goal-tier-select")
                
                # Division dropdown (1-4) - always create, hide for Mythic
                division_label = Static("Goal Division:", id="goal-division-label")
                if current_goal_tier == "Mythic":
                    division_label.display = False
                yield division_label
                
                division_options = [(str(i), str(i)) for i in range(4, 0, -1)]  # 4,3,2,1
                current_goal_div = str(self.stats.session_goal_division) if self.stats.session_goal_division else "4"
                division_select = Select(division_options, value=current_goal_div, id="goal-division-select")
                if current_goal_tier == "Mythic":
                    division_select.display = False
                yield division_select
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Set Goal", id="set-goal", variant="success")
                yield Button("Clear Goal", id="clear-goal", variant="warning")
                yield Button("Cancel", id="cancel", variant="error")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "set-goal":
            # Get tier value
            tier_select = self.query_one("#goal-tier-select", Select)
            tier = RankTier(tier_select.value)
            
            if tier == RankTier.MYTHIC:
                self.dismiss((tier, None))
            else:
                # Get division value
                division_select = self.query_one("#goal-division-select", Select)
                division = int(division_select.value)
                self.dismiss((tier, division))
        elif event.button.id == "clear-goal":
            self.dismiss((None, None))
        else:
            self.action_cancel()
    
    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle tier selection changes to show/hide division controls."""
        if event.select.id == "goal-tier-select":
            is_mythic = event.value == "Mythic"
            
            # Show/hide division controls
            self.query_one("#goal-division-label").display = not is_mythic
            self.query_one("#goal-division-select").display = not is_mythic
    
    def action_cancel(self) -> None:
        """Cancel and close modal."""
        self.dismiss(None)

class SetRankModal(ModalScreen):
    """Modal dialog for setting rank with dropdowns."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, current_rank: ManualRank, format_type: FormatType, modal_title: str = "Set Rank", **kwargs):
        super().__init__(**kwargs)
        self.current_rank = current_rank
        self.format_type = format_type
        self.modal_title = modal_title
        self.result = None
    
    def compose(self) -> ComposeResult:
        with Container(classes="rank-modal-container"):
            yield Static(self.modal_title, classes="modal-title")
            yield Static(f"Current: {self.current_rank}", classes="modal-subtitle")
            
            with Vertical(classes="modal-form"):
                # Tier dropdown
                tier_options = [(tier.value, tier.value) for tier in RankTier]
                current_tier = self.current_rank.tier.value if hasattr(self.current_rank.tier, 'value') else self.current_rank.tier
                yield Static("Tier:")
                yield Select(tier_options, value=current_tier, id="tier-select")
                
                # Division dropdown (1-4) - always create, hide for Mythic
                division_label = Static("Division:", id="division-label")
                if current_tier == "Mythic":
                    division_label.display = False
                yield division_label
                
                division_options = [(str(i), str(i)) for i in range(4, 0, -1)]
                current_div = str(self.current_rank.division) if self.current_rank.division else "1"
                division_select = Select(division_options, value=current_div, id="division-select")
                if current_tier == "Mythic":
                    division_select.display = False
                yield division_select
                
                # Pips dropdown - always create, hide for Mythic
                pips_label = Static("Pips:", id="pips-label")
                if current_tier == "Mythic":
                    pips_label.display = False
                yield pips_label
                
                max_pips = 6 if self.format_type in [FormatType.CONSTRUCTED_BO1, FormatType.CONSTRUCTED_BO3] else 4
                pip_options = [(str(i), str(i)) for i in range(max_pips)]
                pips_select = Select(pip_options, value=str(self.current_rank.pips), id="pips-select")
                if current_tier == "Mythic":
                    pips_select.display = False
                yield pips_select
                
                # Mythic options - always create, hide for non-Mythic
                mythic_type_label = Static("Mythic Type:", id="mythic-type-label")
                if current_tier != "Mythic":
                    mythic_type_label.display = False
                yield mythic_type_label
                
                mythic_type_options = [("Percentage", "Percentage"), ("Rank Number", "Rank Number")]
                current_type = "Rank Number" if self.current_rank.mythic_rank else "Percentage"
                mythic_type_select = Select(mythic_type_options, value=current_type, id="mythic-type")
                if current_tier != "Mythic":
                    mythic_type_select.display = False
                yield mythic_type_select
                
                mythic_value_label = Static("Mythic Value:", id="mythic-value-label")
                if current_tier != "Mythic":
                    mythic_value_label.display = False
                yield mythic_value_label
                
                if self.current_rank.mythic_rank:
                    current_value = str(self.current_rank.mythic_rank)
                    placeholder = "1247"
                else:
                    current_value = str(self.current_rank.mythic_percentage) if self.current_rank.mythic_percentage else "95.0"
                    placeholder = "95.0"
                mythic_value_input = Input(value=current_value, placeholder=placeholder, id="mythic-value")
                if current_tier != "Mythic":
                    mythic_value_input.display = False
                yield mythic_value_input
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Set Rank", id="set-rank", variant="success")
                yield Button("Cancel", id="cancel", variant="error")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "set-rank":
            # Get tier value
            tier_select = self.query_one("#tier-select", Select)
            try:
                tier = RankTier(tier_select.value) if tier_select.value != Select.BLANK else RankTier.BRONZE
            except (ValueError, TypeError):
                tier = RankTier.BRONZE  # Default to Bronze
            
            if tier == RankTier.MYTHIC:
                # Handle Mythic rank - check if percentage or rank number
                mythic_type_select = self.query_one("#mythic-type", Select)
                mythic_value_input = self.query_one("#mythic-value", Input)
                
                mythic_type = mythic_type_select.value if mythic_type_select.value != Select.BLANK else "Percentage"
                if mythic_type == "Rank Number":
                    # Mythic rank number (e.g., #1247) - must be >= 1
                    try:
                        mythic_rank = int(mythic_value_input.value) if mythic_value_input.value else 1247
                        mythic_rank = max(1, mythic_rank)  # Ensure rank >= 1
                    except:
                        mythic_rank = 1247
                    
                    new_rank = ManualRank(
                        tier=tier,
                        division=None,
                        pips=0,
                        mythic_rank=mythic_rank,
                        format_type=self.format_type
                    )
                else:
                    # Mythic percentage (e.g., 95.7%) - must be 0-100
                    try:
                        mythic_percentage = float(mythic_value_input.value) if mythic_value_input.value else 95.0
                        mythic_percentage = max(0.0, min(100.0, mythic_percentage))  # Clamp to 0-100
                    except:
                        mythic_percentage = 95.0
                    
                    new_rank = ManualRank(
                        tier=tier,
                        division=None,
                        pips=0,
                        mythic_percentage=mythic_percentage,
                        format_type=self.format_type
                    )
            else:
                # Handle regular ranks
                division_select = self.query_one("#division-select", Select) 
                pips_select = self.query_one("#pips-select", Select)
                
                # Handle NoSelection cases with defaults
                try:
                    division = int(division_select.value) if division_select.value != Select.BLANK else 4
                except (ValueError, TypeError):
                    division = 4  # Default to division 4
                
                try:
                    pips = int(pips_select.value) if pips_select.value != Select.BLANK else 0
                except (ValueError, TypeError):
                    pips = 0  # Default to 0 pips
                
                new_rank = ManualRank(
                    tier=tier,
                    division=division,
                    pips=pips,
                    format_type=self.format_type
                )
            
            self.result = new_rank
            self.dismiss(new_rank)
        else:
            self.action_cancel()
    
    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle tier selection changes to show/hide appropriate widgets."""
        if event.select.id == "tier-select":
            is_mythic = event.value == "Mythic"
            
            # Show/hide division and pips controls
            self.query_one("#division-label").display = not is_mythic
            self.query_one("#division-select").display = not is_mythic
            self.query_one("#pips-label").display = not is_mythic
            self.query_one("#pips-select").display = not is_mythic
            
            # Show/hide mythic controls
            self.query_one("#mythic-type-label").display = is_mythic
            self.query_one("#mythic-type").display = is_mythic
            self.query_one("#mythic-value-label").display = is_mythic
            self.query_one("#mythic-value").display = is_mythic
            
        elif event.select.id == "mythic-type":
            # Handle mythic type changes - reset to appropriate default
            mythic_value_input = self.query_one("#mythic-value", Input)
            
            if event.value == "Rank Number":
                # Switch to rank number - clear field and set placeholder
                mythic_value_input.value = ""
                mythic_value_input.placeholder = "1247"
            else:
                # Switch to percentage - clear field and set placeholder  
                mythic_value_input.value = ""
                mythic_value_input.placeholder = "95.0"

    def action_cancel(self) -> None:
        """Cancel and close modal."""
        self.dismiss(None)

class ConfirmationModal(ModalScreen):
    """Modal dialog for confirmations."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    CSS = """
    ConfirmationModal {
        align: center middle;
    }
    
    .confirmation-modal-container {
        width: 60;
        height: 18;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    .confirmation-modal-message {
        height: 6;
        content-align: center middle;
        margin-bottom: 2;
    }
    
    .confirmation-modal-buttons {
        height: 3;
        content-align: center middle;
        margin-top: 1;
    }
    """
    
    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.result = False
    
    def compose(self) -> ComposeResult:
        with Container(classes="confirmation-modal-container"):
            yield Static(self.message, classes="confirmation-modal-message")
            with Horizontal(classes="confirmation-modal-buttons"):
                yield Button("Yes", id="confirm-yes", variant="success")
                yield Button("No", id="confirm-no", variant="error")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.result = True
        else:
            self.result = False
        self.dismiss(self.result)
    
    def action_cancel(self) -> None:
        """Cancel and close modal."""
        self.dismiss(False)

class NotesManagerModal(ModalScreen):
    """Modal for viewing and editing all game notes."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "edit_selected", "Edit Selected"),
        Binding("delete", "delete_selected", "Delete Selected"),
    ]
    
    CSS = """
    NotesManagerModal {
        align: center middle;
    }
    
    #notes-manager-dialog {
        width: 95;
        height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }
    
    .notes-list {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .manager-buttons {
        height: 3;
        content-align: center middle;
    }
    """
    
    def __init__(self, notes_list, **kwargs):
        super().__init__(**kwargs)
        self.notes_list = notes_list
        self.selected_note_id = None
        self.has_changes = False
    
    def compose(self) -> ComposeResult:
        with Container(id="notes-manager-dialog"):
            yield Label("Game Notes Manager", classes="modal-title")
            yield Label("Use ↑↓ to select, Enter to edit, Delete to remove", classes="help-text")
            
            table = DataTable(id="notes-table", classes="notes-list")
            table.add_columns("Time", "Result", "Play/Draw", "Opponent", "Notes Preview")
            table.cursor_type = "row"
            
            # Populate table
            for note in self.notes_list:
                # Handle timestamp safely with smart date/time display
                if 'timestamp' in note and isinstance(note['timestamp'], datetime):
                    now = datetime.now()
                    note_time = note['timestamp']
                    
                    # If note is from today, show just time. Otherwise show date + time
                    if note_time.date() == now.date():
                        time_str = note_time.strftime("%H:%M")
                    else:
                        time_str = note_time.strftime("%m/%d %H:%M")
                else:
                    time_str = "??:??"
                
                result_icon = "🏆" if note.get('result') == 'Win' else "💀" if note.get('result') == 'Loss' else "❓"
                preview = note['notes'][:25] + "..." if len(note['notes']) > 25 else note['notes']
                
                table.add_row(
                    time_str,
                    f"{result_icon} {note.get('result', 'Unknown')}",
                    note['play_draw'],
                    note['opponent_deck'][:15] if note['opponent_deck'] else "",
                    preview,
                    key=str(note['id'])
                )
            
            yield table
            
            with Horizontal(classes="manager-buttons"):
                yield Button("Add Note", id="add-btn", variant="success")
                yield Button("Edit Selected", id="edit-btn", variant="primary")
                yield Button("Delete Selected", id="delete-btn", variant="error")
                yield Button("Close", id="close-btn", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            self.action_add_note()
        elif event.button.id == "edit-btn":
            self.action_edit_selected()
        elif event.button.id == "delete-btn":
            self.action_delete_selected()
        elif event.button.id == "close-btn":
            self.action_cancel()
    
    def on_data_table_row_selected(self, event) -> None:
        """Track which note is selected."""
        if event.row_key:
            try:
                self.selected_note_id = int(str(event.row_key))
            except (ValueError, TypeError):
                self.selected_note_id = None
        else:
            self.selected_note_id = None
    
    def action_edit_selected(self) -> None:
        """Edit the selected note."""
        # Try to get the currently highlighted row from the table
        table = self.query_one("#notes-table", DataTable)
        
        if table.cursor_row is not None and table.cursor_row < len(self.notes_list):
            # Use the cursor position to find the note
            note_to_edit = self.notes_list[table.cursor_row]
            self.selected_note_id = note_to_edit['id']
        
        if not self.selected_note_id:
            self.app.notify("No note selected! Use arrow keys to select a row.", severity="warning")
            return
        
        # Find the note to edit
        note_to_edit = None
        for note in self.notes_list:
            if note['id'] == self.selected_note_id:
                note_to_edit = note
                break
        
        if note_to_edit:
            # Create edit modal with pre-filled data
            edit_modal = GameNotesModal(existing_note=note_to_edit)
            
            def handle_edit_result(result):
                if result:
                    # Update the note
                    note_to_edit.update({
                        'result': result['result'],
                        'play_draw': result['play_draw'],
                        'opponent_deck': result['opponent_deck'],
                        'notes': result['notes']
                    })
                    # Refresh the table display
                    self._refresh_table()
                    self.app.notify("Note updated successfully!", severity="success")
            
            self.app.push_screen(edit_modal, handle_edit_result)
    
    def action_delete_selected(self) -> None:
        """Delete the selected note."""
        # Try to get the currently highlighted row from the table
        table = self.query_one("#notes-table", DataTable)
        
        if table.cursor_row is not None and table.cursor_row < len(self.notes_list):
            # Use the cursor position to find the note
            note_to_delete = self.notes_list[table.cursor_row]
            self.selected_note_id = note_to_delete['id']
        
        if not self.selected_note_id:
            self.app.notify("No note selected! Use arrow keys to select a row.", severity="warning")
            return
        
        # Find the note to get details for confirmation
        note_to_delete = None
        for note in self.notes_list:
            if note['id'] == self.selected_note_id:
                note_to_delete = note
                break
        
        if note_to_delete:
            # Create confirmation message
            opponent = note_to_delete.get('opponent_deck', 'Unknown opponent')
            result = note_to_delete.get('result', 'Unknown result')
            confirm_msg = f"Delete this note?\n\n{result} vs {opponent}\n\nThis cannot be undone."
            
            # Show confirmation dialog
            confirm_modal = ConfirmationModal(confirm_msg)
            
            def handle_confirmation(confirmed):
                if confirmed:
                    # Remove the note
                    for i, note in enumerate(self.notes_list):
                        if note['id'] == self.selected_note_id:
                            self.notes_list.pop(i)
                            break
                    
                    # Refresh the table display
                    self._refresh_table()
                    self.app.notify("Note deleted successfully!", severity="success")
                    
                    # Signal that notes were modified
                    self.has_changes = True
            
            self.app.push_screen(confirm_modal, handle_confirmation)
    
    def _refresh_table(self) -> None:
        """Refresh the table display after changes."""
        table = self.query_one("#notes-table", DataTable)
        table.clear()
        
        # Re-populate table with current notes
        for note in self.notes_list:
            # Handle timestamp safely with smart date/time display
            if 'timestamp' in note and isinstance(note['timestamp'], datetime):
                now = datetime.now()
                note_time = note['timestamp']
                
                # If note is from today, show just time. Otherwise show date + time
                if note_time.date() == now.date():
                    time_str = note_time.strftime("%H:%M")
                else:
                    time_str = note_time.strftime("%m/%d %H:%M")
            else:
                time_str = "??:??"
            
            result_icon = "🏆" if note.get('result') == 'Win' else "💀" if note.get('result') == 'Loss' else "❓"
            preview = note['notes'][:25] + "..." if len(note['notes']) > 25 else note['notes']
            
            table.add_row(
                time_str,
                f"{result_icon} {note.get('result', 'Unknown')}",
                note['play_draw'],
                note['opponent_deck'][:15] if note['opponent_deck'] else "",
                preview,
                key=str(note['id'])
            )
    
    def action_add_note(self) -> None:
        """Add a new note."""
        notes_modal = GameNotesModal()
        
        def handle_note_result(note_data):
            if note_data:
                # Add the new note to our list
                self.notes_list.append(note_data)
                # Refresh the table display
                self._refresh_table()
                self.app.notify("Note added successfully!", severity="success")
                
                # Signal that notes were modified
                self.has_changes = True
        
        self.app.push_screen(notes_modal, handle_note_result)
    
    def action_cancel(self) -> None:
        """Cancel and close modal."""
        if self.has_changes:
            self.dismiss("deleted")  # Signal that changes were made
        else:
            self.dismiss(None)

class GameNotesModal(ModalScreen):
    """Modal dialog for adding detailed game notes."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    CSS = """
    GameNotesModal {
        align: center middle;
    }
    
    #notes-dialog {
        width: 90;
        height: 35;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    .notes-row {
        height: 3;
        margin: 0 0 1 0;
    }
    
    .notes-label {
        width: 18;
        content-align: right middle;
    }
    
    .notes-input {
        width: 1fr;
        margin-left: 1;
    }
    
    .notes-textarea {
        height: 10;
        margin: 1 0;
        border: solid $primary;
        background: $surface;
        color: $text;
        padding: 1;
    }
    
    .notes-textarea:focus {
        border: thick $accent;
    }
    
    .modal-buttons {
        height: 4;
        margin-top: 2;
        content-align: center middle;
        dock: bottom;
    }
    """
    
    def __init__(self, existing_note=None, **kwargs):
        super().__init__(**kwargs)
        self.result = None
        self.existing_note = existing_note
        self.is_editing = existing_note is not None
    
    def compose(self) -> ComposeResult:
        with Container(id="notes-dialog"):
            title = "Edit Game Notes" if self.is_editing else "Add Game Notes"
            yield Label(title, classes="modal-title")
            
            # Pre-fill values if editing
            result_value = self.existing_note.get('result', 'Unknown') if self.existing_note else 'Unknown'
            play_draw_value = self.existing_note.get('play_draw', 'Unknown') if self.existing_note else 'Unknown'
            deck_value = self.existing_note.get('opponent_deck', '') if self.existing_note else ''
            notes_value = self.existing_note.get('notes', '') if self.existing_note else ''
            
            with Horizontal(classes="notes-row"):
                yield Label("Result:", classes="notes-label")
                yield Select([
                    ("Unknown", "Unknown"),
                    ("Win", "Win"),
                    ("Loss", "Loss")
                ], value=result_value, id="result-select", classes="notes-input")
            
            with Horizontal(classes="notes-row"):
                yield Label("Play/Draw:", classes="notes-label")
                yield Select([
                    ("Unknown", "Unknown"),
                    ("Play", "Play"),
                    ("Draw", "Draw")
                ], value=play_draw_value, id="play-draw-select", classes="notes-input")
            
            with Horizontal(classes="notes-row"):
                yield Label("Opponent Deck:", classes="notes-label")
                yield Input(value=deck_value, placeholder="e.g. Mono Red, Esper Control", id="opp-deck-input", classes="notes-input")
            
            yield Label("Game Notes:")
            yield TextArea(text=notes_value, id="notes-textarea", classes="notes-textarea")
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Save Note", id="save-btn", variant="success")
                yield Button("Cancel", id="cancel-btn", variant="default")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_note()
        elif event.button.id == "cancel-btn":
            self.action_cancel()
    
    def _save_note(self):
        """Save the note only."""
        note_data = self._get_note_data()
        self.result = note_data
        self.dismiss(note_data)
    
    def _get_note_data(self):
        """Extract note data from the form."""
        result_select = self.query_one("#result-select", Select)
        play_draw_select = self.query_one("#play-draw-select", Select)
        opp_deck_input = self.query_one("#opp-deck-input", Input)
        notes_textarea = self.query_one("#notes-textarea", TextArea)
        
        return {
            "result": result_select.value if result_select.value != Select.BLANK else "Unknown",
            "play_draw": play_draw_select.value if play_draw_select.value != Select.BLANK else "Unknown",
            "opponent_deck": opp_deck_input.value.strip(),
            "notes": notes_textarea.text.strip(),
            "timestamp": datetime.now()
        }
    
    def action_cancel(self) -> None:
        """Cancel and close modal."""
        self.dismiss(None)

class AboutModal(ModalScreen):
    """Modal dialog showing project information, licensing, and credits."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("enter", "cancel", "Close"),
        Binding("ctrl+q", "quit", "Quit"),
    ]
    
    CSS = """
    AboutModal {
        align: center middle;
    }
    
    #about-dialog {
        width: 90;
        height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }
    
    .about-content {
        height: 100%;
        scrollbar-gutter: stable;
    }
    
    .about-section {
        margin-bottom: 1;
    }
    
    .about-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    
    .license-text {
        color: $text-muted;
        text-style: italic;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Container(id="about-dialog"):
            yield Label("MTGA Mythic Tracker TUI - About", classes="about-title")
            with Container(classes="about-content"):
                # Project info
                yield Static("Terminal-based MTG Arena session tracker\nManual rank progression with goals and statistics\nSession timers and game tracking", classes="about-section")
                
                # Fan Content Policy
                yield Static("Fan Content Policy", classes="about-title")
                yield Static("MTGA Mythic Tracker TUI is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.", classes="about-section license-text")
                
                # AI Development
                yield Static("Development", classes="about-title") 
                yield Static("This project was developed with AI assistance (Claude/Anthropic) as a collaborative coding tool, with all architectural decisions, requirements, and creative direction provided by human developers.", classes="about-section license-text")
                
                # Dual Licensing
                yield Static("Licensing", classes="about-title")
                yield Static("Dual-licensed under:\n• MIT License - For strict legal certainty\n• Vibe-Coder License (VCL-0.1-Experimental) - For those who serve the vibe", classes="about-section")
                
                # Credits
                yield Static("Credits", classes="about-title")
                yield Static("The Vibe-Coder License (VCL-0.1-Experimental) was vibe-coded by Tyraziel\nwith co-creative help from Byte (ChatGPT AI sidekick).", classes="about-section license-text")
                
                # GitHub links
                yield Static("Project Repository", classes="about-title")
                yield Static("https://github.com/tyraziel/mtga-mythic-tracker-tui", classes="about-section")
                yield Static("VCL License Info: https://github.com/tyraziel/vibe-coder-license", classes="about-section license-text")
                
                yield Static("\n[bold]Press ESC or Enter to close[/bold]", classes="about-section")

    def action_cancel(self) -> None:
        """Close the about dialog."""
        self.dismiss()
    
    def action_quit(self) -> None:
        """Quit the entire application."""
        self.app.exit()

# === MAIN APPLICATION ===

class ManualTUIApp(App):
    """Main TUI application for manual rank tracking."""
    
    TITLE = "MTGA Mythic TUI Session Tracker (Manual)"
    
    CSS = """
    Screen {
        layout: vertical;
    }
    
    .top-panel {
        dock: top;
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }
    
    .top-panel-layout {
        height: 100%;
    }
    
    .top-season {
        width: 40%;
        height: 100%;
        padding: 0 1;
        content-align: left middle;
    }
    
    .top-format {
        width: 20%;
        height: 100%;
        content-align: center middle;
    }
    
    .top-bars {
        width: 20%;
        height: 100%;
        content-align: center middle;
    }
    
    .top-rank {
        width: 20%;
        height: 100%;
        content-align: right middle;
        padding: 0 1;
    }
    
    #main-content {
        layout: horizontal;
        height: 1fr;
        overflow-y: auto;
    }
    
    .left-panel, .right-panel {
        width: 50%;
        height: 100%;
        border: solid $primary;
        margin: 1;
        padding: 1;
        overflow-y: auto;
    }
    
    .footer-controls {
        dock: bottom;
        height: 1;
        background: $surface;
        content-align: center middle;
    }
    
    .panel-header {
        text-style: bold;
        text-align: center;
        color: $accent;
    }
    
    .separator {
        color: $primary;
    }
    
    .help-text, .controls {
        color: $text-muted;
        text-align: center;
        margin: 1 0;
    }
    
    .format-hint {
        color: $text-muted;
        text-align: center;
        margin: 0 1;
        text-style: italic;
    }
    
    .mythic-display {
        text-align: center;
        color: $warning;
        text-style: bold;
    }
    
    .rank-row {
        margin: 0 0 0 1;
    }
    
    .bronze-tier { color: #CD7F32; }
    .silver-tier { color: #C0C0C0; }
    .gold-tier { color: #FFD700; }
    .platinum-tier { color: #E5E4E2; }
    .diamond-tier { color: #B9F2FF; }
    .mythic-row { color: #FF4500; }
    
    .collapsed { color: $text-muted; }
    
    .switch-button {
        width: 100%;
        margin: 0 0 1 0;
    }
    
    .goal-section, .session-section, .season-section, .history-section {
        margin: 1 0;
    }
    
    .modal-container {
        width: 50;
        height: 10;
        border: solid $primary;
        background: $surface;
        padding: 2;
    }
    
    .modal-message {
        text-align: center;
        margin: 0 0 2 0;
    }
    
    .modal-buttons {
        align: center middle;
    }
    
    .editable-display:hover {
        background: $accent 30%;
        text-style: underline;
    }
    
    .hidden {
        display: none;
    }
    
    /* Modal Styling */
    ConfirmationModal {
        align: center middle;
    }
    
    SetRankModal {
        align: center middle;
    }
    
    .confirmation-modal-container {
        width: 50;
        height: 12;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }
    
    .rank-modal-container {
        width: 60;
        height: 35;
        border: solid $primary;
        background: $surface;
        padding: 2;
        overflow-y: auto;
    }
    
    SetGoalModal {
        align: center middle;
    }
    
    .goal-modal-container {
        width: 60;
        height: 25;
        border: solid $primary;
        background: $surface;
        padding: 2;
        overflow-y: auto;
    }
    
    .confirmation-modal-message {
        width: 100%;
        text-align: center;
        margin: 1 0;
    }
    
    .confirmation-modal-buttons {
        width: 100%;
        align: center middle;
    }
    """
    
    BINDINGS = [
        Binding("w", "add_win", "Add Win"),
        Binding("l", "add_loss", "Add Loss"),
        Binding("plus", "add_win", "Add Win (+)"),
        Binding("minus", "add_loss", "Add Loss (-)"),
        Binding("f", "switch_format", "Switch Format"),
        Binding("g", "set_goal", "Set Goal"),
        Binding("m", "toggle_mythic", "Toggle Mythic"),
        Binding("c", "collapse_tiers", "Collapse"),
        Binding("h", "hide_tiers", "Hide"),
        Binding("r", "restart_session", "Restart Session"),
        Binding("p", "pause_resume_session", "Pause/Resume Timer"),
        Binding("shift+s", "start_game", "Start Game Timer"),
        Binding("e", "edit_stats", "Edit Stats"),
        Binding("s", "set_rank", "Set Rank"),
        Binding("t", "set_season_start", "Set Season Start"),
        Binding("n", "add_game_notes", "Add Game Notes"),
        Binding("ctrl+n", "view_all_notes", "View All Notes"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("?", "help", "Help"),
        Binding("i", "about", "About"),
        Binding("v", "toggle_event_mode", "Event Mode"),
        Binding("u", "start_event_run", "Start Run (Event Mode)"),
    ]
    
    def __init__(self, state_manager: StateManager):
        super().__init__()
        self.state_manager = state_manager
        self.app_data = state_manager.load_state()
        self.event_catalog = load_event_catalog(default_catalog_path())

    def compose(self) -> ComposeResult:
        with Container():
            yield TopPanel(self.app_data, self.event_catalog).add_class("top-panel")

            with Container(id="main-content"):
                if self.app_data.view_mode == "event":
                    yield EventRunPanel(self.app_data, self.event_catalog).add_class("left-panel")
                    yield EventStatsPanel(self.app_data, self.event_catalog).add_class(
                        "right-panel"
                    )
                else:
                    yield RankProgressPanel(self.app_data).add_class("left-panel")
                    yield StatsPanel(self.app_data).add_class("right-panel")

            yield Footer()
    
    def on_mount(self) -> None:
        """Initialize the app on mount."""
        # Create timer for status updates after app is mounted
        self.set_interval(1.0, self.update_status)
        self.update_status()
    
    def update_status(self) -> None:
        """Update top panel and status."""
        try:
            top_panel = self.query_one(TopPanel)
            top_panel.update_display()
        except Exception as e:
            # DEBUG: Log top panel update errors
            self.notify(f"Top panel update error: {e}", severity="error")
        
        # Update timer-based elements in stats panel
        try:
            self._update_session_timers()
        except Exception as e:
            # DEBUG: Log timer update errors
            self.notify(f"Timer update error: {e}", severity="error")
        
        # Save state periodically
        try:
            self.state_manager.save_state(self.app_data)
        except Exception as e:
            # DEBUG: Log save errors
            self.notify(f"Save error: {e}", severity="error")
    
    def _update_session_timers(self) -> None:
        """Update session duration and last result timers."""
        if self.app_data.view_mode == "event":
            # StatsPanel isn't mounted in event view mode (EventStatsPanel is).
            return
        try:
            # Find stats panel and tell it to refresh its session section
            stats_panel = self.query_one(StatsPanel)
            stats_panel.refresh_session_section()
            # DEBUG: Confirm timer is running
            # self.notify("Timer tick", timeout=0.5)  # Uncomment to see if timer runs
        except Exception as e:
            # DEBUG: Log specific timer errors
            self.notify(f"Session timer error: {e}", severity="error")
    
    def _is_goal_attained(self, current_rank: ManualRank, goal_tier, goal_division) -> bool:
        """Check if the session goal has been attained."""
        if not goal_tier:
            return False
            
        # Handle mythic goal
        if goal_tier == RankTier.MYTHIC or str(goal_tier) == "Mythic":
            return current_rank.is_mythic()
            
        # Compare tier and division
        current_tier_str = current_rank.tier.value if hasattr(current_rank.tier, 'value') else str(current_rank.tier)
        goal_tier_str = goal_tier.value if hasattr(goal_tier, 'value') else str(goal_tier)
        
        if current_tier_str != goal_tier_str:
            return False
            
        # Same tier - compare division (lower division number = higher rank)
        return current_rank.division <= goal_division
    
    def action_add_win(self) -> None:
        """Add a win to the session (or the current event run, in Event Mode)."""
        if self.app_data.view_mode == "event":
            self._event_record_result(EventGameResult.WIN)
            return

        # Check goal status before the win
        stats = self.app_data.stats
        current_rank = self.app_data.get_current_rank()
        was_goal_achieved = self._is_goal_attained(current_rank, stats.session_goal_tier, stats.session_goal_division)
        
        # Update rank
        new_rank = current_rank.add_win()
        self.app_data.set_current_rank(new_rank)
        
        # End game timer and record duration
        game_duration = self.app_data.stats.end_game_timer()
        
        # Update stats
        self.app_data.stats.add_win()
        
        # Check if goal was just achieved
        if not was_goal_achieved and stats.session_goal_tier:
            is_goal_achieved_now = self._is_goal_attained(new_rank, stats.session_goal_tier, stats.session_goal_division)
            if is_goal_achieved_now:
                # Goal just achieved!
                # Handle both enum and string cases for session_goal_tier
                if stats.session_goal_tier == RankTier.MYTHIC or str(stats.session_goal_tier) == "Mythic":
                    goal_name = "Mythic"
                else:
                    tier_name = stats.session_goal_tier.value if hasattr(stats.session_goal_tier, 'value') else str(stats.session_goal_tier)
                    goal_name = f"{tier_name} {stats.session_goal_division}"
                self.notify(f"🎉 SESSION GOAL ACHIEVED: {goal_name}! 🎉", severity="success")
        
        # Check for milestones after win
        self._check_milestones(new_rank, current_rank)
        
        # Refresh display
        self.refresh_panels()
    
    def action_add_loss(self) -> None:
        """Add a loss to the session (or the current event run, in Event Mode)."""
        if self.app_data.view_mode == "event":
            self._event_record_result(EventGameResult.LOSS)
            return

        # Update rank
        current_rank = self.app_data.get_current_rank()
        new_rank = current_rank.add_loss()
        self.app_data.set_current_rank(new_rank)
        
        # End game timer and record duration
        game_duration = self.app_data.stats.end_game_timer()
        
        # Update stats
        self.app_data.stats.add_loss()
        
        # Refresh display
        self.refresh_panels()
    
    def action_switch_format(self) -> None:
        """Switch between BO1, BO3, and Limited."""
        # Cycle through format types
        if self.app_data.current_format == FormatType.CONSTRUCTED_BO1:
            self.app_data.current_format = FormatType.CONSTRUCTED_BO3
            new_format = "BO3"
        elif self.app_data.current_format == FormatType.CONSTRUCTED_BO3:
            self.app_data.current_format = FormatType.LIMITED
            new_format = "LIMITED"
        else:  # LIMITED
            self.app_data.current_format = FormatType.CONSTRUCTED_BO1
            new_format = "BO1"
        
        # Immediately update just the format column
        try:
            format_widget = self.query_one(".top-format", Static)
            format_widget.update(f"📊 {new_format}")
        except:
            pass
        
        # Force immediate update of everything
        self.refresh_panels()
        
        # Also call update_status to ensure top panel updates
        self.update_status()
    
    def action_set_goal(self) -> None:
        """Set session goal rank via modal."""
        current_rank = self.app_data.get_current_rank()
        
        # Create and push the goal setting modal
        modal = SetGoalModal(current_rank, self.app_data.current_format, self.app_data.stats)
        
        def handle_result(result):
            if result is not None:
                if result == (None, None):
                    # Clear goal
                    self.app_data.stats.session_goal_tier = None
                    self.app_data.stats.session_goal_division = None
                else:
                    # Set new goal
                    self.app_data.stats.session_goal_tier = result[0]
                    self.app_data.stats.session_goal_division = result[1]
                self.refresh_panels()
        
        # Push screen and handle result when dismissed
        self.push_screen(modal, handle_result)
    
    def action_set_season_start(self) -> None:
        """Set season start rank via modal."""
        current_rank = self.app_data.get_current_rank()
        
        # Create and push the season start rank modal
        modal = SetRankModal(current_rank, self.app_data.current_format, modal_title="Set Season Start Rank")
        
        def handle_result(result):
            if result:
                # Update the season start rank
                self.app_data.stats.season_start_rank = result
                self.refresh_panels()
        
        # Push screen and handle result when dismissed
        self.push_screen(modal, handle_result)
    
    def action_add_game_notes(self) -> None:
        """Add detailed game notes with optional result application."""
        modal = GameNotesModal()
        
        def handle_result(result):
            if result:
                # Save the note to session stats
                if not hasattr(self.app_data.stats, 'game_notes') or self.app_data.stats.game_notes is None:
                    self.app_data.stats.game_notes = []
                
                # Add note to the list
                note_entry = {
                    "id": len(self.app_data.stats.game_notes) + 1,
                    "timestamp": result['timestamp'],
                    "result": result['result'],
                    "play_draw": result['play_draw'],
                    "opponent_deck": result['opponent_deck'],
                    "notes": result['notes']
                }
                self.app_data.stats.game_notes.append(note_entry)
                
                # Save state
                self.state_manager.save_state(self.app_data)
                
                # Show summary toast
                note_summary = f"{result['play_draw']}"
                if result['opponent_deck']:
                    note_summary += f" vs {result['opponent_deck']}"
                
                self.notify(f"Note saved: {note_summary}", severity="success")
                self.refresh_panels()
        
        self.push_screen(modal, handle_result)
    
    def action_view_all_notes(self) -> None:
        """View and edit all game notes."""
        # Initialize game_notes if it doesn't exist
        if not hasattr(self.app_data.stats, 'game_notes'):
            self.app_data.stats.game_notes = []
        
        # Always show the notes manager, even if empty
        manager_modal = NotesManagerModal(self.app_data.stats.game_notes)
        
        def handle_manager_result(result):
            if result in ["updated", "deleted"]:
                # Save state and refresh display
                self.state_manager.save_state(self.app_data)
                self.refresh_panels()
                
                action_text = "updated" if result == "updated" else "deleted"
                self.notify(f"Note {action_text} successfully!", severity="success")
        
        self.push_screen(manager_modal, handle_manager_result)
    
    def action_edit_stats(self) -> None:
        """Edit session and season statistics."""
        modal = EditStatsModal(self.app_data.stats)
        
        def handle_result(result):
            with open("debug.log", "a") as f:
                f.write(f"[{datetime.now()}] EditStats modal returned: {result}\n")
            if result == "saved":
                # Force update milestone tracking to ensure UI shows correct values
                stats = self.app_data.stats
                
                # Debug: Log the values before and after to see what's happening
                old_session_rate = stats.last_session_win_rate
                old_season_rate = stats.last_season_win_rate
                
                stats.last_session_win_rate = stats.get_session_win_rate()
                stats.last_season_win_rate = stats.get_season_win_rate()
                
                # Debug log to file
                with open("debug.log", "a") as f:
                    f.write(f"[{datetime.now()}] Season stats updated: {stats.season_wins}W-{stats.season_losses}L = {stats.get_season_win_rate():.2f}%\n")
                    f.write(f"[{datetime.now()}] Session stats updated: {stats.session_wins}W-{stats.session_losses}L = {stats.get_session_win_rate():.2f}%\n")
                
                # Try alternative refresh approach: update specific season section
                try:
                    # Force fresh calculation
                    total_games = stats.season_wins + stats.season_losses
                    win_rate = (stats.season_wins / total_games * 100) if total_games > 0 else 0.0
                    format_name = self.app_data.current_format.value.upper()
                    
                    # Format highest rank achieved (same logic as _create_season_section)
                    highest_text = "Not set"
                    if stats.season_highest_rank:
                        highest_rank = stats.season_highest_rank
                        
                        # Handle case where it might be a dict (backwards compatibility)
                        if isinstance(highest_rank, dict):
                            try:
                                highest_rank = ManualRank(**highest_rank)
                                stats.season_highest_rank = highest_rank  # Fix it for next time
                            except:
                                highest_rank = None  # Skip display if conversion fails
                        
                        if highest_rank and highest_rank.is_mythic():
                            if highest_rank.mythic_rank:
                                highest_text = f"Mythic #{highest_rank.mythic_rank} 👑"
                            else:
                                highest_text = f"Mythic {highest_rank.mythic_percentage:.1f}% 👑"
                        else:
                            tier_name = highest_rank.tier.value if hasattr(highest_rank.tier, 'value') else highest_rank.tier
                            # Create visual progress bar for highest rank
                            progress_bar = ""
                            for i in range(highest_rank.max_pips):
                                if i < highest_rank.pips:
                                    progress_bar += "█"  # Full block
                                else:
                                    progress_bar += "░"  # Light shade
                            highest_text = f"{tier_name} {highest_rank.division} [{progress_bar}] ({highest_rank.pips}/{highest_rank.max_pips})"
                    
                    new_season_content = f"""🏆 SEASON TOTAL [{format_name}] ({total_games})
Record:   [{stats.season_wins}W] - [{stats.season_losses}L]  {win_rate:.2f}%"""
                    
                    # Try to update the season section directly
                    season_widget = self.query_one("#season-section", Static)
                    season_widget.update(new_season_content)
                    
                except Exception as e:
                    with open("debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] Direct update failed: {e}, falling back to full refresh\n")
                    # Fall back to full panel refresh
                    self.refresh_panels()
                
                self.update_status()  # Also update top panel timers
                self.refresh()  # Force full app refresh
                
                # Schedule another refresh after the next render cycle
                self.call_after_refresh(lambda: self.notify(f"Stats updated! Session: {stats.get_session_win_rate():.2f}%, Season: {win_rate:.2f}%", severity="success"))
                
                self.state_manager.save_state(self.app_data)
        
        self.push_screen(modal, handle_result)
    
    def action_toggle_mythic(self) -> None:
        """Toggle mythic progress display."""
        self.app_data.show_mythic_progress = not self.app_data.show_mythic_progress
        self.refresh_panels()
    
    def action_collapse_tiers(self) -> None:
        """Toggle auto-collapse mode for completed tiers."""
        # Toggle auto-collapse mode
        self.app_data.auto_collapse_mode = not self.app_data.auto_collapse_mode
        
        current_rank = self.app_data.get_current_rank()
        tier_order = list(RankTier)[:-1]  # Exclude Mythic
        
        if self.app_data.auto_collapse_mode:
            # Enable auto-collapse: collapse all currently completed tiers
            if current_rank.is_mythic():
                completed_tiers = tier_order
            else:
                current_tier_idx = tier_order.index(current_rank.tier)
                completed_tiers = tier_order[:current_tier_idx]
            
            for tier in completed_tiers:
                if tier not in self.app_data.collapsed_tiers:
                    self.app_data.collapsed_tiers.append(tier)
        else:
            # Disable auto-collapse: uncollapse all tiers
            self.app_data.collapsed_tiers.clear()
        
        self.refresh_panels()
    
    def action_hide_tiers(self) -> None:
        """Toggle auto-hide mode for completed tiers completely."""
        # Toggle auto-hide mode
        self.app_data.auto_hide_mode = not self.app_data.auto_hide_mode
        
        current_rank = self.app_data.get_current_rank()
        tier_order = list(RankTier)[:-1]  # Exclude Mythic
        
        if self.app_data.auto_hide_mode:
            # Enable auto-hide: hide all currently completed tiers
            if current_rank.is_mythic():
                completed_tiers = tier_order
            else:
                current_tier_idx = tier_order.index(current_rank.tier)
                completed_tiers = tier_order[:current_tier_idx]
            
            for tier in completed_tiers:
                if tier not in self.app_data.hidden_tiers:
                    self.app_data.hidden_tiers.append(tier)
        else:
            # Disable auto-hide: unhide all tiers
            self.app_data.hidden_tiers.clear()
        
        self.refresh_panels()
    
    def action_restart_session(self) -> None:
        """Restart current session (same as reset), or the event session in Event Mode."""
        if self.app_data.view_mode == "event":
            self._event_restart_session()
            return

        modal = ConfirmationModal("Restart session? This will reset wins/losses and session timer.")

        def handle_restart_result(result):
            if result:
                current_rank = self.app_data.get_current_rank()
                # Complete current session before resetting
                self.app_data.stats.complete_current_session(current_rank, self.app_data.current_format)
                self.app_data.stats.reset_session(current_rank)
                self.refresh_panels()

        self.push_screen(modal, handle_restart_result)

    def action_toggle_event_mode(self) -> None:
        """Toggle between the ranked view and the event-mode view."""
        self.app_data.view_mode = "event" if self.app_data.view_mode == "ranked" else "ranked"
        self.refresh_panels()
        self.notify(f"Switched to {self.app_data.view_mode.title()} view", severity="information")

    def action_start_event_run(self) -> None:
        """Start a new event run (Event Mode only)."""
        if self.app_data.view_mode != "event":
            self.notify("Press V to switch to Event Mode first", severity="warning")
            return

        stats = self.app_data.event_stats
        if stats.current_run and stats.current_run.status == EventRunStatus.ACTIVE:
            self.notify("Current run hasn't ended yet!", severity="warning")
            return

        event = self._get_current_event_definition()
        if not event:
            self.notify("No events configured in events.json", severity="error")
            return

        run_id = f"run_{stats.alltime_runs_played + 1}"
        run = EventRun(
            run_id=run_id, event_id=event.event_id, entry_currency=self._default_entry_currency(event)
        )
        stats.start_run(run)
        self.refresh_panels()
        self.notify("New run started!", severity="success")

    def _default_entry_currency(self, event: EventDefinition) -> Optional[str]:
        """Pick a default entry currency for a new run: prefer Gems, else
        this event's first configured entry option.

        TODO: there's no UI picker for this yet (e.g. if an event only
        offers Gold or a token entry) - this always defaults silently.
        """
        if not event.entry_options:
            return None
        gems_option = event.get_entry_option("Gems")
        if gems_option:
            return gems_option.currency
        return event.entry_options[0].currency

    def _get_current_event_definition(self) -> Optional[EventDefinition]:
        """The EventDefinition matching the currently-tracked event."""
        return _get_event_for_stats(self.app_data.event_stats, self.event_catalog)

    def _event_record_result(self, result: EventGameResult) -> None:
        """Record a win/loss against the current event run."""
        event = self._get_current_event_definition()
        if not event:
            self.notify("No events configured in events.json", severity="error")
            return

        stats = self.app_data.event_stats
        if not stats.current_run or stats.current_run.status == EventRunStatus.ENDED:
            self.notify("No active run! Press [U] to start one.", severity="warning")
            return

        stats.record_game(EventGame(result=result), event)
        self.refresh_panels()

    def _event_restart_session(self) -> None:
        """Reset event session totals (keeps all-time totals), with confirmation."""
        modal = ConfirmationModal(
            "Restart event session? This clears session totals (all-time totals are kept)."
        )

        def handle_result(result):
            if result:
                self.app_data.event_stats.restart_session()
                self.refresh_panels()

        self.push_screen(modal, handle_result)
    
    def action_pause_resume_session(self) -> None:
        """Pause or resume the session timer."""
        stats = self.app_data.stats
        
        if stats.session_paused:
            # Resume the session
            stats.resume_session()
            self.notify("Session timer resumed", severity="success")
        else:
            # Pause the session
            if stats.session_start_time:
                stats.pause_session()
                self.notify("Session timer paused", severity="info")
            else:
                self.notify("No active session to pause", severity="warning")
        
        self.refresh_panels()
    
    def _check_milestones(self, new_rank: ManualRank, old_rank: ManualRank) -> None:
        """Check for various milestone achievements and show celebratory toasts."""
        stats = self.app_data.stats
        
        # 1. TIER PROMOTION MILESTONES
        self._check_tier_promotions(new_rank, old_rank)
        
        # 2. WIN COUNT MILESTONES (Session)
        self._check_win_milestones(stats.session_wins, "SESSION")
        
        # 3. WIN COUNT MILESTONES (Season) 
        self._check_win_milestones(stats.season_wins, "SEASON")
        
        # 4. WIN RATE MILESTONES
        self._check_winrate_milestones(stats)
        
        # 5. L10 PERFECT GAMES MILESTONE
        self._check_l10_perfect_games(stats)
        
        # Update milestone tracking
        stats.last_session_win_rate = stats.get_session_win_rate()
        stats.last_season_win_rate = stats.get_season_win_rate()
    
    def _check_tier_promotions(self, new_rank: ManualRank, old_rank: ManualRank) -> None:
        """Check for tier promotions and show celebration toasts."""
        tier_order = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
        
        old_tier_name = old_rank.tier.value if hasattr(old_rank.tier, 'value') else str(old_rank.tier)
        new_tier_name = new_rank.tier.value if hasattr(new_rank.tier, 'value') else str(new_rank.tier)
        
        if old_tier_name != new_tier_name:
            try:
                old_tier_idx = tier_order.index(old_tier_name)
                new_tier_idx = tier_order.index(new_tier_name)
                
                if new_tier_idx > old_tier_idx:
                    # Tier promotion!
                    if new_tier_name == "Mythic":
                        self.notify("🏆 MYTHIC ACHIEVED! Welcome to the top tier! 🏆", severity="success")
                    else:
                        self.notify(f"⬆️ TIER PROMOTION: Welcome to {new_tier_name}! ⬆️", severity="success")
            except ValueError:
                pass  # Unknown tier names
    
    def _check_win_milestones(self, win_count: int, scope: str) -> None:
        """Check for win count milestones (10, 25, 50, 100, 200+ wins)."""
        milestones = [10, 25, 50, 100, 200, 300, 500, 750, 1000]
        
        for milestone in milestones:
            if win_count == milestone:
                if milestone >= 500:
                    self.notify(f"🔥 {milestone} {scope} WINS! Absolute legend! 🔥", severity="success")
                elif milestone >= 200:
                    self.notify(f"⚡ {milestone} {scope} WINS! Incredible dedication! ⚡", severity="success")
                elif milestone >= 100:
                    self.notify(f"💪 {milestone} {scope} WINS! Century achieved! 💪", severity="success")
                elif milestone >= 50:
                    self.notify(f"🎯 {milestone} {scope} WINS! Halfway to 100! 🎯", severity="success")
                else:
                    self.notify(f"🎊 {milestone} {scope} WINS! Nice milestone! 🎊", severity="success")
                break
    
    def _check_winrate_milestones(self, stats: SessionStats) -> None:
        """Check for win rate threshold achievements."""
        session_rate = stats.get_session_win_rate()
        season_rate = stats.get_season_win_rate()
        
        # Session win rate milestones - check highest thresholds first
        if stats.session_wins + stats.session_losses >= 10:  # Only after meaningful sample
            for threshold in [80.0, 75.0, 70.0, 65.0, 60.0, 55.0, 50.0]:
                if session_rate >= threshold and stats.last_session_win_rate < threshold:
                    if threshold >= 75.0:
                        self.notify(f"🔥 SESSION {threshold:.0f}%+ WIN RATE! Dominating! 🔥", severity="success")
                    elif threshold >= 65.0:
                        self.notify(f"⭐ SESSION {threshold:.0f}%+ WIN RATE! Excellent! ⭐", severity="success")
                    else:
                        self.notify(f"📈 SESSION {threshold:.0f}%+ WIN RATE! On fire! 📈", severity="success")
                    break
        
        # Season win rate milestones - check highest thresholds first  
        if stats.season_wins + stats.season_losses >= 50:  # Only after meaningful sample
            for threshold in [75.0, 70.0, 65.0, 60.0, 55.0, 50.0]:
                if season_rate >= threshold and stats.last_season_win_rate < threshold:
                    if threshold >= 70.0:
                        self.notify(f"👑 SEASON {threshold:.0f}%+ WIN RATE! Elite performance! 👑", severity="success")
                    elif threshold >= 60.0:
                        self.notify(f"🌟 SEASON {threshold:.0f}%+ WIN RATE! Strong climbing! 🌟", severity="success")
                    else:
                        self.notify(f"📊 SEASON {threshold:.0f}%+ WIN RATE! Positive record! 📊", severity="success")
                    break
    
    def _check_l10_perfect_games(self, stats: SessionStats) -> None:
        """Check for L10 perfect games (10 wins in a row) milestone."""
        if hasattr(stats, 'session_game_results') and stats.session_game_results:
            # Check if we have at least 10 games and the last 10 are all wins
            if len(stats.session_game_results) >= 10:
                last_10 = stats.session_game_results[-10:]
                if all(result == 'W' for result in last_10):
                    # Check if this is a new achievement (weren't perfect before this win)
                    if len(stats.session_game_results) > 10:
                        # Look at the 11th-to-last game to see if this is newly perfect
                        previous_11th = stats.session_game_results[-11]
                        if previous_11th == 'L':
                            # This is a new perfect 10! Celebrate!
                            self.notify("🌟 PERFECT L10! TEN WINS IN A ROW! UNSTOPPABLE! 🌟", severity="success")
                    else:
                        # Exactly 10 games and all wins - first time perfect!
                        self.notify("🌟 PERFECT L10! TEN WINS IN A ROW! UNSTOPPABLE! 🌟", severity="success")
    
    def action_start_game(self) -> None:
        """Start a new game timer."""
        stats = self.app_data.stats
        
        if stats.game_start_time:
            # Game already in progress, ask to restart
            modal = ConfirmationModal("Game timer already running. Restart timer?")
            
            def handle_restart_game(result):
                if result:
                    stats.start_game_timer()
                    self.notify("Game timer restarted", severity="info")
                    self.refresh_panels()
            
            self.push_screen(modal, handle_restart_game)
        else:
            # Start new game timer
            stats.start_game_timer()
            self.notify("Game timer started", severity="success")
            self.refresh_panels()
    
    def action_help(self) -> None:
        """Show help information."""
        help_text = """MTGA Manual Tracker Help

Keyboard Shortcuts:
W/+ - Add win       L/- - Add loss
F - Switch format (BO1/BO3/Limited)  
G - Set session goal    T - Set season start rank
E - Edit stats (streaks, session start)
N - Add game notes    Ctrl+N - View all notes
M - Toggle mythic progress
C - Collapse tiers      H - Hide tiers
R - Restart session     P - Pause/Resume timer
Shift+S - Start game    S - Set rank manually   
Ctrl+Q - Quit           I - About/Info

Manual Editing:
Click any [bracketed] value to edit inline
Click rank bars to set exact position
ESC to cancel editing

Press any key to close this help."""
        
        self.push_screen(ConfirmationModal(help_text))
    
    def action_about(self) -> None:
        """Show about dialog with project info and licensing."""
        self.push_screen(AboutModal())

    def action_set_rank(self) -> None:
        """Set rank manually via modal with dropdowns."""
        current_rank = self.app_data.get_current_rank()
        
        # Create and push the modal
        modal = SetRankModal(current_rank, self.app_data.current_format)
        
        def handle_result(result):
            if result:
                # Check goal status before the change
                stats = self.app_data.stats
                current_rank = self.app_data.get_current_rank()
                was_goal_achieved = self._is_goal_attained(current_rank, stats.session_goal_tier, stats.session_goal_division)
                
                # Update the rank and refresh
                self.app_data.set_current_rank(result)
                
                # Check if goal was just achieved through manual rank setting
                if not was_goal_achieved and stats.session_goal_tier:
                    is_goal_achieved_now = self._is_goal_attained(result, stats.session_goal_tier, stats.session_goal_division)
                    if is_goal_achieved_now:
                        # Goal just achieved!
                        # Handle both enum and string cases for session_goal_tier
                        if stats.session_goal_tier == RankTier.MYTHIC or str(stats.session_goal_tier) == "Mythic":
                            goal_name = "Mythic"
                        else:
                            tier_name = stats.session_goal_tier.value if hasattr(stats.session_goal_tier, 'value') else str(stats.session_goal_tier)
                            goal_name = f"{tier_name} {stats.session_goal_division}"
                        self.notify(f"🎉 SESSION GOAL ACHIEVED: {goal_name}! 🎉", severity="success")
                
                self.refresh_panels()
        
        # Push screen and handle result when dismissed
        self.push_screen(modal, handle_result)
    
    def refresh_panels(self) -> None:
        """Refresh all panels with current data."""
        # Update the top panel
        self.update_status()

        # Force refresh of rank progress panel by removing and re-adding
        try:
            main_content = self.query_one("#main-content")
            # Remove existing panels
            left_panel = self.query_one(".left-panel")
            right_panel = self.query_one(".right-panel")
            left_panel.remove()
            right_panel.remove()

            # Add new panels with updated data, matching the current view mode
            if self.app_data.view_mode == "event":
                main_content.mount(
                    EventRunPanel(self.app_data, self.event_catalog).add_class("left-panel")
                )
                main_content.mount(
                    EventStatsPanel(self.app_data, self.event_catalog).add_class("right-panel")
                )
            else:
                main_content.mount(RankProgressPanel(self.app_data).add_class("left-panel"))
                main_content.mount(StatsPanel(self.app_data).add_class("right-panel"))
        except Exception as e:
            # Log the error but continue
            self.notify(f"Panel refresh error: {e}", severity="warning")
    
    def on_exit(self) -> None:
        """Save state before exit."""
        self.state_manager.save_state(self.app_data)

def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="MTGA Mythic TUI Session Tracker (Manual)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                           # Run with default settings
  %(prog)s --data-dir ~/my-data/     # Use custom data directory
  %(prog)s --no-save                 # Don't save state (fresh each run)
  %(prog)s --format Limited          # Start in Limited format
"""
    )
    
    parser.add_argument(
        "--data-dir", 
        type=Path,
        help="Directory for saving application data (default: ~/.local/share/mtga-manual-tracker/)"
    )
    
    parser.add_argument(
        "--no-save",
        action="store_true", 
        help="Don't save/load application state"
    )
    
    parser.add_argument(
        "--format",
        choices=["Constructed", "Limited"],
        default="Constructed",
        help="Starting format (default: Constructed)"
    )
    
    args = parser.parse_args()
    
    # Create state manager
    state_manager = StateManager(
        data_dir=args.data_dir,
        save_enabled=not args.no_save
    )
    
    # Create and run app
    app = ManualTUIApp(state_manager)
    
    # Set initial format if specified
    if args.format == "Limited":
        app.app_data.current_format = FormatType.LIMITED
    
    try:
        app.run()
    finally:
        # Ensure state is saved on exit
        if not args.no_save:
            state_manager.save_state(app.app_data)

if __name__ == "__main__":
    main()