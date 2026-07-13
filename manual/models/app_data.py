"""
App data model for MTGA Manual TUI Tracker.

Contains AppData class that holds the complete application state.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from .rank import ManualRank, RankTier, FormatType
from .session import SessionStats
from .event import EventStats


@dataclass
class AppData:
    """Complete application state."""
    constructed_rank: ManualRank
    limited_rank: ManualRank
    current_format: FormatType
    stats: SessionStats
    show_mythic_progress: bool = True
    collapsed_tiers: List[RankTier] = None
    hidden_tiers: List[RankTier] = None
    auto_collapse_mode: bool = False
    auto_hide_mode: bool = False
    event_stats: EventStats = field(default_factory=EventStats)
    view_mode: str = "ranked"  # "ranked" or "event" - which panels are shown

    def __post_init__(self):
        if self.collapsed_tiers is None:
            self.collapsed_tiers = []
        if self.hidden_tiers is None:
            self.hidden_tiers = []
    
    def get_current_rank(self) -> ManualRank:
        """Get rank for current format."""
        if self.current_format in [FormatType.CONSTRUCTED_BO1, FormatType.CONSTRUCTED_BO3]:
            return self.constructed_rank
        else:
            return self.limited_rank
    
    def set_current_rank(self, rank: ManualRank):
        """Set rank for current format."""
        if self.current_format in [FormatType.CONSTRUCTED_BO1, FormatType.CONSTRUCTED_BO3]:
            self.constructed_rank = rank
        else:
            self.limited_rank = rank
        
        # Update highest rank achieved this season
        self._update_season_highest_rank(rank)
        
        # Clean up hide/collapse states when rank changes
        self._cleanup_tier_states(rank)
    
    def _cleanup_tier_states(self, current_rank: ManualRank):
        """Clean up invalid hide/collapse states and auto-collapse/hide newly completed tiers."""
        tier_order = list(RankTier)[:-1]  # Exclude Mythic
        
        if current_rank.is_mythic():
            # At mythic, all non-mythic tiers are completed
            # If we're in collapse/hide mode, apply to all completed tiers
            if self.collapsed_tiers:
                for tier in tier_order:
                    if tier not in self.collapsed_tiers:
                        self.collapsed_tiers.append(tier)
            if self.hidden_tiers:
                for tier in tier_order:
                    if tier not in self.hidden_tiers:
                        self.hidden_tiers.append(tier)
            return
        
        current_tier_idx = tier_order.index(current_rank.tier)
        completed_tiers = tier_order[:current_tier_idx]  # Tiers below current
        incomplete_tiers = tier_order[current_tier_idx:]  # Current tier and above
        
        # Remove any incomplete tiers from collapsed/hidden lists
        for tier in incomplete_tiers:
            if tier in self.collapsed_tiers:
                self.collapsed_tiers.remove(tier)
            if tier in self.hidden_tiers:
                self.hidden_tiers.remove(tier)
        
        # Auto-collapse/hide newly completed tiers if in auto mode
        if self.auto_collapse_mode:
            for tier in completed_tiers:
                if tier not in self.collapsed_tiers:
                    self.collapsed_tiers.append(tier)
        
        if self.auto_hide_mode:
            for tier in completed_tiers:
                if tier not in self.hidden_tiers:
                    self.hidden_tiers.append(tier)
    
    def _update_season_highest_rank(self, current_rank: ManualRank):
        """Update the highest rank achieved this season."""
        if not self.stats.season_highest_rank:
            # First rank of the season
            self.stats.season_highest_rank = current_rank
            return
        
        highest = self.stats.season_highest_rank
        
        # Compare ranks to see if current is higher
        if self._is_rank_higher(current_rank, highest):
            self.stats.season_highest_rank = current_rank
    
    def _is_rank_higher(self, rank1: ManualRank, rank2: ManualRank) -> bool:
        """Check if rank1 is higher than rank2 (including exact pip progression)."""
        # Handle mythic ranks
        if rank1.is_mythic() and rank2.is_mythic():
            # For mythic, higher percentage or lower rank number is better
            if rank1.mythic_rank and rank2.mythic_rank:
                return rank1.mythic_rank < rank2.mythic_rank  # Lower number = higher rank
            elif rank1.mythic_percentage and rank2.mythic_percentage:
                return rank1.mythic_percentage > rank2.mythic_percentage  # Higher % = higher rank
            elif rank1.mythic_rank and not rank2.mythic_rank:
                return True  # Numbered mythic > percentage mythic
            elif not rank1.mythic_rank and rank2.mythic_rank:
                return False  # Percentage mythic < numbered mythic
            else:
                return False  # Can't determine, keep existing
        
        if rank1.is_mythic() and not rank2.is_mythic():
            return True  # Mythic is always higher than non-mythic
        
        if not rank1.is_mythic() and rank2.is_mythic():
            return False  # Non-mythic is never higher than mythic
        
        # Both are non-mythic - compare tier, division, and pips
        tier_order = [RankTier.BRONZE, RankTier.SILVER, RankTier.GOLD, RankTier.PLATINUM, RankTier.DIAMOND]
        
        rank1_tier_idx = tier_order.index(rank1.tier)
        rank2_tier_idx = tier_order.index(rank2.tier)
        
        if rank1_tier_idx > rank2_tier_idx:
            return True  # Higher tier
        elif rank1_tier_idx < rank2_tier_idx:
            return False  # Lower tier
        else:
            # Same tier - compare division (lower division number = higher rank)
            if rank1.division < rank2.division:
                return True  # Higher division (1 > 2 > 3 > 4)
            elif rank1.division > rank2.division:
                return False  # Lower division
            else:
                # Same division - compare pips (higher pips = higher rank)
                return rank1.pips > rank2.pips