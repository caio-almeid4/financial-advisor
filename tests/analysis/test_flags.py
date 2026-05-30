import pytest

from src.analysis.flags import (
    ALLOCATION_GAP_THRESHOLD,
    INCEPTION_LOSS_THRESHOLD,
    generate_flags,
    _flag_allocation_gaps,
    _flag_large_inception_losses,
    _flag_underperforming_cdi,
)
from src.analysis.models import AllocationStatus, AssetReturn


def make_asset(**overrides) -> AssetReturn:
    defaults = dict(
        name="LREN3",
        asset_class="acoes",
        allocation_pct=8.91,
        monthly_return_pct=9.0,
        return_since_inception_pct=-10.0,
        monthly_vs_cdi=8.0,
        investment_date="01/01/2024",
    )
    return AssetReturn(**{**defaults, **overrides})


def make_status(**overrides) -> AllocationStatus:
    defaults = dict(asset_class="acoes", current_pct=0.20, target_pct=0.20, gap_pct=0.0)
    return AllocationStatus(**{**defaults, **overrides})


# --- Inception loss flags ---

class TestFlagLargeInceptionLosses:
    def test_flags_asset_below_threshold(self):
        asset = make_asset(name="HAPV3", return_since_inception_pct=-74.58)
        flags = _flag_large_inception_losses([asset])
        assert len(flags) == 1
        assert "HAPV3" in flags[0]
        assert "-74.6%" in flags[0]

    def test_no_flag_above_threshold(self):
        asset = make_asset(return_since_inception_pct=-39.9)
        assert _flag_large_inception_losses([asset]) == []

    def test_exactly_at_threshold_not_flagged(self):
        asset = make_asset(return_since_inception_pct=INCEPTION_LOSS_THRESHOLD)
        assert _flag_large_inception_losses([asset]) == []

    def test_positive_return_not_flagged(self):
        asset = make_asset(return_since_inception_pct=43.5)
        assert _flag_large_inception_losses([asset]) == []

    def test_multiple_assets_flags_only_losers(self):
        assets = [
            make_asset(name="HAPV3", return_since_inception_pct=-74.58),
            make_asset(name="MRFG3", return_since_inception_pct=43.5),
            make_asset(name="LREN3", return_since_inception_pct=-41.7),
        ]
        flags = _flag_large_inception_losses(assets)
        assert len(flags) == 2
        assert any("HAPV3" in f for f in flags)
        assert any("LREN3" in f for f in flags)
        assert not any("MRFG3" in f for f in flags)


# --- Allocation gap flags ---

class TestFlagAllocationGaps:
    def test_flags_overweight_class(self):
        status = make_status(asset_class="renda_fixa", current_pct=0.45, target_pct=0.30, gap_pct=0.15)
        flags = _flag_allocation_gaps([status])
        assert len(flags) == 1
        assert "renda_fixa" in flags[0]
        assert "acima" in flags[0]

    def test_flags_underweight_class(self):
        status = make_status(asset_class="acoes", current_pct=0.05, target_pct=0.20, gap_pct=-0.15)
        flags = _flag_allocation_gaps([status])
        assert len(flags) == 1
        assert "abaixo" in flags[0]

    def test_no_flag_within_threshold(self):
        status = make_status(gap_pct=0.09)
        assert _flag_allocation_gaps([status]) == []

    def test_exactly_at_threshold_not_flagged(self):
        status = make_status(gap_pct=ALLOCATION_GAP_THRESHOLD)
        assert _flag_allocation_gaps([status]) == []

    def test_flags_contain_current_and_target(self):
        status = make_status(current_pct=0.45, target_pct=0.30, gap_pct=0.15)
        flags = _flag_allocation_gaps([status])
        assert "45.0%" in flags[0]
        assert "30.0%" in flags[0]


# --- Underperforming CDI flags ---

class TestFlagUnderperformingCdi:
    def test_flags_asset_below_cdi(self):
        asset = make_asset(name="ARZZ3", monthly_return_pct=0.5, monthly_vs_cdi=-0.4)
        flags = _flag_underperforming_cdi([asset])
        assert len(flags) == 1
        assert "ARZZ3" in flags[0]

    def test_no_flag_above_cdi(self):
        asset = make_asset(monthly_return_pct=2.0, monthly_vs_cdi=1.0)
        assert _flag_underperforming_cdi([asset]) == []

    def test_no_flag_when_monthly_return_is_none(self):
        asset = make_asset(monthly_return_pct=None, monthly_vs_cdi=None)
        assert _flag_underperforming_cdi([asset]) == []


# --- generate_flags (integration of all rules) ---

class TestGenerateFlags:
    def test_combines_all_flag_types(self):
        assets = [
            make_asset(name="HAPV3", return_since_inception_pct=-74.58, monthly_return_pct=0.3, monthly_vs_cdi=-0.6),
        ]
        allocation_status = [
            make_status(asset_class="acoes", current_pct=0.05, target_pct=0.20, gap_pct=-0.15),
        ]
        flags = generate_flags(assets, allocation_status, cdi_monthly_pct=0.89)
        assert any("HAPV3" in f and "-74" in f for f in flags)
        assert any("acoes" in f and "abaixo" in f for f in flags)
        assert any("HAPV3" in f and "CDI" in f for f in flags)

    def test_empty_inputs_return_no_flags(self):
        assert generate_flags([], [], cdi_monthly_pct=0.89) == []
