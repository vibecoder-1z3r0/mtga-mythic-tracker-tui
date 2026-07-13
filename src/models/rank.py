"""
MTG Arena ranking system models.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, validator


class RankTier(str, Enum):
    """MTG Arena rank tiers."""

    BRONZE = "Bronze"
    SILVER = "Silver"
    GOLD = "Gold"
    PLATINUM = "Platinum"
    DIAMOND = "Diamond"
    MYTHIC = "Mythic"


class FormatType(str, Enum):
    """MTG Arena format types."""

    CONSTRUCTED = "Constructed"
    LIMITED = "Limited"


class Rank(BaseModel):
    """Represents a player's rank in MTG Arena."""

    tier: RankTier
    division: Optional[int] = Field(None, ge=1, le=4)  # 1-4 for non-Mythic
    pips: int = Field(0, ge=0)  # Current pips in division
    max_pips: int = Field(6, ge=1)  # Max pips per division (usually 6)
    mythic_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)  # For Mythic only
    losses_at_zero: int = Field(0, ge=0)  # Consecutive losses at 0 pips (for demotion protection)

    @validator("division")
    def validate_division(cls, v, values):
        """Validate division based on tier."""
        tier = values.get("tier")
        if tier == RankTier.MYTHIC:
            if v is not None:
                raise ValueError("Mythic tier should not have division")
        else:
            if v is None or not (1 <= v <= 4):
                raise ValueError("Non-Mythic tiers must have division 1-4")
        return v

    @validator("mythic_percentage")
    def validate_mythic_percentage(cls, v, values):
        """Validate mythic percentage only exists for Mythic tier."""
        tier = values.get("tier")
        if tier == RankTier.MYTHIC:
            if v is None:
                raise ValueError("Mythic tier must have percentage")
        else:
            if v is not None:
                raise ValueError("Non-Mythic tiers should not have percentage")
        return v

    def can_derank_tier(self) -> bool:
        """Check if this rank can drop to a lower tier (tier floors)."""
        # Once you reach a tier, you can't drop below it
        return False

    def can_derank_division(self) -> bool:
        """Check if this rank can lose pips within the same tier."""
        # Can lose pips and divisions within Gold+ tiers
        return self.tier not in [RankTier.BRONZE, RankTier.SILVER]

    def is_complete_division(self) -> bool:
        """Check if current division is complete (all pips filled)."""
        if self.tier == RankTier.MYTHIC:
            return True  # Mythic doesn't have pips
        return self.pips >= self.max_pips

    def add_pips(self, count: int) -> "Rank":
        """Add pips to rank, handling promotion logic."""
        if self.tier == RankTier.MYTHIC:
            # Mythic uses percentage, not pips
            return self

        new_pips = self.pips + count
        new_division = self.division
        new_tier = self.tier
        new_losses_at_zero = 0  # Reset losses counter on any gain

        # Handle promotion within tier
        while new_pips >= self.max_pips and new_division > 1:
            new_pips -= self.max_pips
            new_division -= 1

        # Handle tier promotion
        if new_pips >= self.max_pips and new_division == 1:
            tier_order = list(RankTier)
            current_index = tier_order.index(self.tier)
            if current_index < len(tier_order) - 1:
                new_tier = tier_order[current_index + 1]
                if new_tier == RankTier.MYTHIC:
                    # Promote to Mythic
                    return Rank(
                        tier=RankTier.MYTHIC,
                        mythic_percentage=95.0,  # Default starting percentage
                    )
                else:
                    # Promote to next tier, division 4
                    new_division = 4
                    new_pips = 0

        return Rank(
            tier=new_tier,
            division=new_division,
            pips=min(new_pips, self.max_pips),
            max_pips=self.max_pips,
            losses_at_zero=new_losses_at_zero,
        )

    def remove_pips(self, count: int) -> "Rank":
        """Remove pips from rank, handling demotion logic with demotion protection."""
        if not self.can_derank_division():
            return self  # Bronze/Silver protection

        if self.tier == RankTier.MYTHIC:
            # Mythic uses percentage, not pips
            return self

        new_pips = self.pips - count
        new_division = self.division
        new_tier = self.tier
        new_losses_at_zero = self.losses_at_zero

        # If already at 0 pips and losing more
        if self.pips == 0 and count > 0:
            new_losses_at_zero += 1
            # Need 3-4 consecutive losses at 0 pips to demote division
            demotion_threshold = 3  # Can be configurable later

            if new_losses_at_zero >= demotion_threshold and new_division < 4:
                # Demote to next division
                new_division += 1
                new_pips = self.max_pips - 1  # Start with almost full pips in lower division
                new_losses_at_zero = 0  # Reset counter after demotion
            else:
                # Stay at 0 pips, just increment loss counter
                new_pips = 0
        else:
            # Normal pip loss
            new_losses_at_zero = 0  # Reset counter if not at 0 pips
            new_pips = max(new_pips, 0)

        # If would demote below tier floor, stop at bottom of current tier
        if new_division > 4:
            new_division = 4
            new_pips = 0
            new_losses_at_zero = max(new_losses_at_zero - 1, 0)  # Don't over-penalize

        return Rank(
            tier=new_tier,
            division=new_division,
            pips=new_pips,
            max_pips=self.max_pips,
            losses_at_zero=new_losses_at_zero,
        )

    def is_boss_fight(self) -> bool:
        """Check if the next win would promote to the next tier (boss fight!)."""
        if self.tier == RankTier.MYTHIC:
            return False  # Already at highest tier

        # Boss fight: Division 1 with max_pips - 1 pips (5/6 pips = next win promotes)
        return self.division == 1 and self.pips == (self.max_pips - 1)

    def next_tier(self) -> Optional[str]:
        """Get the name of the next tier for promotion."""
        if self.tier == RankTier.MYTHIC:
            return None

        tier_order = list(RankTier)
        current_index = tier_order.index(self.tier)
        if current_index < len(tier_order) - 1:
            return tier_order[current_index + 1].value
        return None

    def __str__(self) -> str:
        """String representation of rank."""
        if self.tier == RankTier.MYTHIC:
            return f"Mythic {self.mythic_percentage:.1f}%"
        return f"{self.tier.value} Tier {self.division} ({self.pips}/{self.max_pips})"
