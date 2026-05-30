import re

from src.analysis.models import PortfolioAnalysis

_CLASS_LABELS = {
    "acoes":               "Ações",
    "renda_fixa":          "Renda Fixa",
    "fundos_multimercado": "Multimercado",
    "fundos_acoes":        "Fundos de Ações",
}

_YELLOW = "#FFD100"
_DARK   = "#1A1A1A"
_GREEN  = "#1A7A40"
_AMBER  = "#E67E22"
_RED    = "#C0392B"
_GRID   = "#EBEBEB"
_TEXT   = "#2D2D2D"
_MUTED  = "#888888"


def _trunc(name: str, n: int = 30) -> str:
    return name if len(name) <= n else name[:n - 1] + "…"


def allocation_chart(analysis: PortfolioAnalysis) -> str:
    """Horizontal paired bars (current=yellow, target=dark) — returns inline SVG."""
    statuses = analysis.allocation_status
    n = len(statuses)

    W, LABEL_W, RIGHT_M = 680, 168, 10
    TOP_M, BOT_M = 20, 28
    ROW_H, BAR_H, BAR_GAP = 46, 13, 5
    H = TOP_M + n * ROW_H + BOT_M

    chart_w = W - LABEL_W - RIGHT_M
    max_val = max(
        max(s.current_pct * 100 for s in statuses),
        max(s.target_pct * 100 for s in statuses),
        1.0,
    )
    x_max = max_val * 1.55
    scale = chart_w / x_max

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'style="width:100%;height:auto;display:block;'
        f'font-family:Inter,Helvetica,Arial,sans-serif">'
    ]

    # Grid lines + x-axis labels
    for gi in range(6):
        gv = (x_max / 5) * gi
        gx = LABEL_W + gv * scale
        out.append(
            f'<line x1="{gx:.1f}" y1="{TOP_M}" x2="{gx:.1f}" '
            f'y2="{TOP_M + n * ROW_H}" stroke="{_GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{gx:.1f}" y="{H - 8}" text-anchor="middle" '
            f'font-size="8" fill="{_MUTED}">{gv:.0f}%</text>'
        )

    # Legend
    lx = LABEL_W + 4
    out.append(
        f'<rect x="{lx}" y="4" width="9" height="9" rx="2" fill="{_YELLOW}"/>'
        f'<text x="{lx+12}" y="12.5" font-size="8.5" fill="{_TEXT}">Atual</text>'
        f'<rect x="{lx+46}" y="4" width="9" height="9" rx="2" fill="{_DARK}" opacity="0.75"/>'
        f'<text x="{lx+58}" y="12.5" font-size="8.5" fill="{_TEXT}">Alvo</text>'
    )

    for i, s in enumerate(statuses):
        label = _CLASS_LABELS.get(s.asset_class, s.asset_class)
        c = round(s.current_pct * 100, 1)
        t = round(s.target_pct * 100, 1)

        y_mid  = TOP_M + i * ROW_H + ROW_H // 2
        y_curr = y_mid - BAR_GAP // 2 - BAR_H
        y_tgt  = y_mid + BAR_GAP // 2

        out.append(
            f'<text x="{LABEL_W - 8}" y="{y_mid + 4}" text-anchor="end" '
            f'font-size="10" fill="{_TEXT}">{label}</text>'
        )

        # Current (yellow)
        bw_c = c * scale
        out.append(
            f'<rect x="{LABEL_W}" y="{y_curr}" width="{bw_c:.1f}" '
            f'height="{BAR_H}" rx="2" fill="{_YELLOW}"/>'
        )
        out.append(
            f'<text x="{LABEL_W + bw_c + 4:.1f}" y="{y_curr + BAR_H - 1}" '
            f'font-size="9" fill="#9A7800" font-weight="600">{c:.1f}%</text>'
        )

        # Target (dark)
        bw_t = t * scale
        out.append(
            f'<rect x="{LABEL_W}" y="{y_tgt}" width="{bw_t:.1f}" '
            f'height="{BAR_H}" rx="2" fill="{_DARK}" opacity="0.72"/>'
        )
        out.append(
            f'<text x="{LABEL_W + bw_t + 4:.1f}" y="{y_tgt + BAR_H - 1}" '
            f'font-size="9" fill="{_TEXT}" font-weight="600">{t:.1f}%</text>'
        )

        # Gap annotation
        gap_pp = c - t
        if abs(gap_pp) >= 1.0:
            sign  = "▲" if gap_pp > 0 else "▼"
            color = _RED if abs(gap_pp) >= 5 else _AMBER
            xa = LABEL_W + max(bw_c, bw_t) + 46
            out.append(
                f'<text x="{xa:.1f}" y="{y_mid + 4}" font-size="8.5" '
                f'fill="{color}" font-weight="600">{sign} {abs(gap_pp):.1f}pp</text>'
            )

    out.append("</svg>")
    return "\n".join(out)


def returns_chart(analysis: PortfolioAnalysis) -> str:
    """Horizontal bars colored by performance vs CDI — returns inline SVG."""
    assets = sorted(
        [a for a in analysis.assets if a.monthly_return_pct is not None],
        key=lambda a: a.monthly_return_pct or 0,
    )
    if not assets:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 60" '
            'style="width:100%;height:auto;display:block">'
            f'<text x="10" y="35" font-size="11" fill="{_MUTED}">'
            "Sem dados de retorno mensal disponíveis.</text></svg>"
        )

    cdi = analysis.cdi_monthly_pct
    n   = len(assets)

    W, LABEL_W, RIGHT_M = 680, 215, 10
    TOP_M, BOT_M = 34, 22
    ROW_H, BAR_H = 38, 16
    H = TOP_M + n * ROW_H + BOT_M

    chart_w = W - LABEL_W - RIGHT_M
    values   = [a.monthly_return_pct for a in assets]
    all_abs  = [abs(v) for v in values]
    ref      = sorted(all_abs)[-2] if len(all_abs) > 1 else all_abs[0]
    x_max    = max(ref * 2.2, cdi * 6, 4.0)
    neg      = [v for v in values if v < 0]
    x_min    = min(min(neg) * 1.5, -cdi * 1.5) if neg else -x_max * 0.08
    x_range  = x_max - x_min

    def px(v: float) -> float:
        return LABEL_W + (v - x_min) / x_range * chart_w

    def bar_color(v: float) -> str:
        if v < 0:     return _RED
        if v >= cdi:  return _GREEN
        return _AMBER

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'style="width:100%;height:auto;display:block;'
        f'font-family:Inter,Helvetica,Arial,sans-serif">'
    ]

    # Legend — top row, same style as allocation chart
    lx = LABEL_W + 4
    for color, lbl, offset in [(_GREEN, "Acima do CDI", 0),
                                (_AMBER, "Positivo, abaixo do CDI", 108),
                                (_RED, "Retorno negativo", 258)]:
        ox = lx + offset
        out.append(
            f'<rect x="{ox}" y="4" width="9" height="9" rx="2" fill="{color}"/>'
            f'<text x="{ox + 12}" y="12.5" font-size="8.5" fill="{_TEXT}">{lbl}</text>'
        )

    # Grid + x-axis labels
    for gi in range(6):
        gv = x_min + (x_range / 5) * gi
        gx = px(gv)
        out.append(
            f'<line x1="{gx:.1f}" y1="{TOP_M}" x2="{gx:.1f}" '
            f'y2="{TOP_M + n * ROW_H}" stroke="{_GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{gx:.1f}" y="{H - 6}" text-anchor="middle" '
            f'font-size="8" fill="{_MUTED}">{gv:.1f}%</text>'
        )

    # Zero baseline
    zx = px(0)
    out.append(
        f'<line x1="{zx:.1f}" y1="{TOP_M}" x2="{zx:.1f}" '
        f'y2="{TOP_M + n * ROW_H}" stroke="#CCCCCC" stroke-width="0.8"/>'
    )

    # CDI reference line + label (inside chart area, above first bar)
    cx = px(cdi)
    out.append(
        f'<line x1="{cx:.1f}" y1="{TOP_M}" x2="{cx:.1f}" '
        f'y2="{TOP_M + n * ROW_H}" stroke="{_DARK}" stroke-width="1.8" '
        f'stroke-dasharray="5,3"/>'
    )
    out.append(
        f'<text x="{cx:.1f}" y="{TOP_M - 4}" text-anchor="middle" '
        f'font-size="8" fill="{_DARK}" font-weight="700">CDI {cdi:.2f}%</text>'
    )

    for i, a in enumerate(assets):
        v     = a.monthly_return_pct
        y_mid = TOP_M + i * ROW_H + ROW_H // 2
        y_bar = y_mid - BAR_H // 2

        out.append(
            f'<text x="{LABEL_W - 8}" y="{y_mid + 4}" text-anchor="end" '
            f'font-size="9.5" fill="{_TEXT}">{_trunc(a.name)}</text>'
        )

        clipped    = max(x_min * 0.9, min(v, x_max * 0.9))
        is_clipped = v > x_max * 0.9 or v < x_min * 0.9
        x_bar = px(min(clipped, 0))
        x_end = px(max(clipped, 0))
        bw    = max(x_end - x_bar, 1.0)
        color = bar_color(v)

        out.append(
            f'<rect x="{x_bar:.1f}" y="{y_bar}" width="{bw:.1f}" '
            f'height="{BAR_H}" rx="2" fill="{color}" '
            f'opacity="{"0.55" if is_clipped else "1"}"/>'
        )

        val_txt = f"{v:+.2f}%" + (" ▶" if is_clipped and v > 0 else " ◀" if is_clipped else "")
        if v >= 0:
            lx2, anc = px(max(clipped, 0)) + 4, "start"
        else:
            lx2, anc = px(min(clipped, 0)) - 4, "end"
        out.append(
            f'<text x="{lx2:.1f}" y="{y_mid + 4}" text-anchor="{anc}" '
            f'font-size="9" fill="{_TEXT}">{val_txt}</text>'
        )

    out.append("</svg>")
    return "\n".join(out)


def inception_chart(analysis: PortfolioAnalysis) -> str:
    """Horizontal bars showing return since purchase date — green/red only."""
    assets = sorted(
        [a for a in analysis.assets if a.return_since_inception_pct is not None],
        key=lambda a: a.return_since_inception_pct or 0,
    )
    if not assets:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 60" '
            'style="width:100%;height:auto;display:block">'
            f'<text x="10" y="35" font-size="11" fill="{_MUTED}">'
            "Sem dados de retorno acumulado.</text></svg>"
        )

    n = len(assets)

    W, LABEL_W, RIGHT_M = 680, 215, 10
    TOP_M, BOT_M = 22, 22
    ROW_H, BAR_H = 38, 16
    H = TOP_M + n * ROW_H + BOT_M

    chart_w = W - LABEL_W - RIGHT_M
    values   = [a.return_since_inception_pct for a in assets]
    all_abs  = [abs(v) for v in values]
    ref      = sorted(all_abs)[-2] if len(all_abs) > 1 else all_abs[0]
    x_max    = max(ref * 1.6, 10.0)
    neg      = [v for v in values if v < 0]
    x_min    = min(min(neg) * 1.3, -5.0) if neg else -x_max * 0.08
    x_range  = x_max - x_min

    def px(v: float) -> float:
        return LABEL_W + (v - x_min) / x_range * chart_w

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'style="width:100%;height:auto;display:block;'
        f'font-family:Inter,Helvetica,Arial,sans-serif">'
    ]

    # Grid + x-axis labels
    for gi in range(6):
        gv = x_min + (x_range / 5) * gi
        gx = px(gv)
        out.append(
            f'<line x1="{gx:.1f}" y1="{TOP_M}" x2="{gx:.1f}" '
            f'y2="{TOP_M + n * ROW_H}" stroke="{_GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{gx:.1f}" y="{H - 6}" text-anchor="middle" '
            f'font-size="8" fill="{_MUTED}">{gv:.0f}%</text>'
        )

    # Zero baseline
    zx = px(0)
    out.append(
        f'<line x1="{zx:.1f}" y1="{TOP_M}" x2="{zx:.1f}" '
        f'y2="{TOP_M + n * ROW_H}" stroke="#BBBBBB" stroke-width="1.2"/>'
    )

    for i, a in enumerate(assets):
        v     = a.return_since_inception_pct
        y_mid = TOP_M + i * ROW_H + ROW_H // 2
        y_bar = y_mid - BAR_H // 2

        # Label with investment date when available
        label = _trunc(a.name)
        if a.investment_date:
            label += f"  ({a.investment_date[:7] if len(a.investment_date) > 7 else a.investment_date})"

        out.append(
            f'<text x="{LABEL_W - 8}" y="{y_mid + 4}" text-anchor="end" '
            f'font-size="9.5" fill="{_TEXT}">{label}</text>'
        )

        clipped    = max(x_min * 0.9, min(v, x_max * 0.9))
        is_clipped = v > x_max * 0.9 or v < x_min * 0.9
        x_bar = px(min(clipped, 0))
        x_end = px(max(clipped, 0))
        bw    = max(x_end - x_bar, 1.0)
        color = _GREEN if v >= 0 else _RED

        out.append(
            f'<rect x="{x_bar:.1f}" y="{y_bar}" width="{bw:.1f}" '
            f'height="{BAR_H}" rx="2" fill="{color}" '
            f'opacity="{"0.55" if is_clipped else "1"}"/>'
        )

        val_txt = f"{v:+.1f}%" + (" ▶" if is_clipped and v > 0 else " ◀" if is_clipped else "")
        if v >= 0:
            lx2, anc = px(max(clipped, 0)) + 4, "start"
        else:
            lx2, anc = px(min(clipped, 0)) - 4, "end"
        out.append(
            f'<text x="{lx2:.1f}" y="{y_mid + 4}" text-anchor="{anc}" '
            f'font-size="9" fill="{_TEXT}" font-weight="600">{val_txt}</text>'
        )

    out.append("</svg>")
    return "\n".join(out)
