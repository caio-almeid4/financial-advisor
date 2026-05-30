from src.analysis.models import AllocationStatus, AssetReturn

INCEPTION_LOSS_THRESHOLD = -40.0   # flag stocks/funds down more than 40% since inception
ALLOCATION_GAP_THRESHOLD = 0.10    # flag asset classes deviating more than 10pp from target
UNDERPERFORM_CDI_LABEL = "rendeu abaixo do CDI no mês"


def _flag_large_inception_losses(assets: list[AssetReturn]) -> list[str]:
    flags = []
    for asset in assets:
        if asset.return_since_inception_pct < INCEPTION_LOSS_THRESHOLD:
            flags.append(
                f"{asset.name} acumula {asset.return_since_inception_pct:.1f}% desde a compra"
            )
    return flags


def _flag_allocation_gaps(allocation_status: list[AllocationStatus]) -> list[str]:
    flags = []
    for status in allocation_status:
        if abs(status.gap_pct) > ALLOCATION_GAP_THRESHOLD:
            direction = "acima" if status.gap_pct > 0 else "abaixo"
            flags.append(
                f"{status.asset_class} está {abs(status.gap_pct)*100:.1f}pp {direction} da alocação-alvo"
                f" (atual: {status.current_pct*100:.1f}%, alvo: {status.target_pct*100:.1f}%)"
            )
    return flags


def _flag_underperforming_cdi(assets: list[AssetReturn]) -> list[str]:
    flags = []
    for asset in assets:
        if asset.monthly_vs_cdi is not None and asset.monthly_vs_cdi < 0:
            flags.append(
                f"{asset.name} {UNDERPERFORM_CDI_LABEL}"
                f" ({asset.monthly_return_pct:.2f}% vs CDI)"
            )
    return flags


def generate_flags(
    assets: list[AssetReturn],
    allocation_status: list[AllocationStatus],
    cdi_monthly_pct: float,
) -> list[str]:
    return (
        _flag_large_inception_losses(assets)
        + _flag_allocation_gaps(allocation_status)
        + _flag_underperforming_cdi(assets)
    )
