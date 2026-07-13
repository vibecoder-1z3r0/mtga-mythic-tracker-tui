#!/usr/bin/env python3
"""
Test script for MTG Arena tracker models.
"""

from src.models.rank import Rank, RankTier, FormatType
from src.models.game import Game, GameResult, PlayOrder, GameStats


def test_rank_promotion_and_demotion():
    """Test basic pip addition/removal, promotion, and protection."""
    rank = Rank(tier=RankTier.GOLD, division=3, pips=4, max_pips=6)
    assert str(rank) == "Gold Tier 3 (4/6)"

    promoted_rank = rank.add_pips(3)
    assert str(promoted_rank) == "Gold Tier 2 (1/6)"

    demoted_rank = promoted_rank.remove_pips(8)
    assert str(demoted_rank) == "Gold Tier 2 (0/6)"

    mythic_rank = Rank(tier=RankTier.MYTHIC, mythic_percentage=85.5)
    assert str(mythic_rank) == "Mythic 85.5%"

    # Bronze/Silver can never lose pips (always protected).
    bronze_rank = Rank(tier=RankTier.BRONZE, division=4, pips=2)
    bronze_after_loss = bronze_rank.remove_pips(5)
    assert str(bronze_after_loss) == "Bronze Tier 4 (2/6)"

    # Tier floor: once in Gold, big losses can't drop below Gold Tier 4.
    gold_bottom = Rank(tier=RankTier.GOLD, division=4, pips=0)
    gold_after_losses = gold_bottom.remove_pips(10)
    assert str(gold_after_losses) == "Gold Tier 4 (0/6)"


def test_division_demotion_protection():
    """Test that division demotion requires 3+ consecutive losses at 0 pips."""
    gold_2 = Rank(tier=RankTier.GOLD, division=2, pips=0)
    expected = [
        (2, 0, 1),  # protected, loss counter increments
        (2, 0, 2),  # protected
        (3, 5, 0),  # demoted: division 2 -> 3, refilled to 5 pips, counter reset
        (3, 4, 0),  # normal pip loss after demotion
    ]
    for division, pips, losses_at_zero in expected:
        gold_2 = gold_2.remove_pips(1)
        assert gold_2.division == division
        assert gold_2.pips == pips
        assert gold_2.losses_at_zero == losses_at_zero

    plat_3 = Rank(tier=RankTier.PLATINUM, division=3, pips=0)
    expected = [
        (3, 0, 1),
        (3, 0, 2),
        (4, 5, 0),
        (4, 4, 0),
    ]
    for division, pips, losses_at_zero in expected:
        plat_3 = plat_3.remove_pips(1)
        assert plat_3.division == division
        assert plat_3.pips == pips
        assert plat_3.losses_at_zero == losses_at_zero


def test_win_resets_demotion_counter():
    """Test that any pip gain resets the demotion protection counter."""
    test_rank = Rank(tier=RankTier.DIAMOND, division=1, pips=0, losses_at_zero=2)
    after_win = test_rank.add_pips(1)
    assert after_win.pips == 1
    assert after_win.losses_at_zero == 0


def test_game_tracking():
    """Test game tracking functionality."""
    rank_before = Rank(tier=RankTier.PLATINUM, division=2, pips=4)
    rank_after = Rank(tier=RankTier.PLATINUM, division=2, pips=6)

    game = Game(
        result=GameResult.WIN,
        play_order=PlayOrder.DRAW,
        format_type=FormatType.CONSTRUCTED,
        player_deck="Esper Control",
        opponent_deck="Mono-Red Aggro",
        notes="Close game, stabilized at 3 life",
        rank_before=rank_before,
        rank_after=rank_after,
        pips_gained=2,
    )

    assert game.rank_change_str() == "+2 pips"
    assert game.was_promotion() is False


def test_game_stats():
    """Test game statistics functionality."""
    stats = GameStats()

    games = [
        Game(
            result=GameResult.WIN,
            play_order=PlayOrder.PLAY,
            format_type=FormatType.CONSTRUCTED,
        ),
        Game(
            result=GameResult.LOSS,
            play_order=PlayOrder.DRAW,
            format_type=FormatType.CONSTRUCTED,
        ),
        Game(
            result=GameResult.WIN,
            play_order=PlayOrder.DRAW,
            format_type=FormatType.CONSTRUCTED,
        ),
        Game(
            result=GameResult.WIN,
            play_order=PlayOrder.PLAY,
            format_type=FormatType.CONSTRUCTED,
        ),
        Game(
            result=GameResult.LOSS,
            play_order=PlayOrder.PLAY,
            format_type=FormatType.CONSTRUCTED,
        ),
    ]

    for game in games:
        stats.update_with_game(game)

    assert stats.total_games == 5
    assert stats.wins == 3
    assert stats.losses == 2
    assert stats.win_rate() == 60.0
    assert stats.play_games == 3
    assert stats.draw_games == 2
    assert round(stats.play_win_rate(), 1) == 66.7
    assert stats.draw_win_rate() == 50.0


def main():
    """Run all tests."""
    test_rank_promotion_and_demotion()
    test_division_demotion_protection()
    test_win_resets_demotion_counter()
    test_game_tracking()
    test_game_stats()
    print("All model tests passed!")


if __name__ == "__main__":
    main()
