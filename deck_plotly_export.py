"""
Export Plotly figures to PNG: try Kaleido first, then Matplotlib (no Chromium).
Used by create_site_level_analysis_deck.py when Kaleido is missing or broken.
"""
from __future__ import annotations

from pathlib import Path


def _kaleido_write(fig, path: Path, width: int, height: int, scale: int = 2) -> bool:
    try:
        import kaleido  # noqa: F401
    except ImportError:
        return False
    try:
        fig.write_image(str(path), width=width, height=height, scale=scale)
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _mpl_setup():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _hex_to_mpl(c: str) -> str:
    if isinstance(c, str) and c.startswith("#"):
        return c
    return "#6b7280"


def export_stacked_h_bar_mpl(fig, path: Path, dpi: int = 120) -> None:
    plt = _mpl_setup()
    traces = [t for t in fig.data if getattr(t, "type", None) == "bar"]
    if not traces:
        raise ValueError("expected bar traces")
    title = ""
    if fig.layout.title and fig.layout.title.text:
        title = fig.layout.title.text

    left = 0.0
    fig_mpl, ax = plt.subplots(figsize=(11, 2.9), dpi=dpi)
    fig_mpl.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    for tr in traces:
        w = float(tr.x[0]) if tr.x else 0.0
        c = _hex_to_mpl(tr.marker.color) if tr.marker and tr.marker.color else "#888"
        ax.barh([0], [w], left=left, height=0.55, color=c)
        if w >= 8:
            ax.text(left + w / 2, 0, f"{w:.0f}%", ha="center", va="center", color="white", fontsize=10)
        left += w

    ax.set_xlim(0, 100)
    ax.set_ylim(-0.65, 0.65)
    ax.set_title(title, color="#e5e7eb", fontsize=13, pad=14)
    ax.set_yticks([])
    ax.tick_params(axis="x", colors="#9ca3af")
    ax.grid(axis="x", color="#ffffff15")
    for s in ax.spines.values():
        s.set_visible(False)
    plt.tight_layout()
    plt.savefig(path, facecolor="#1a1a2e", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig_mpl)


def export_region_bars_mpl(fig, path: Path, dpi: int = 120) -> None:
    plt = _mpl_setup()
    traces = [t for t in fig.data if getattr(t, "type", None) == "bar"]
    if len(traces) != 1:
        raise ValueError("expected single bar trace for region chart")
    tr = traces[0]
    title = ""
    if fig.layout.title and fig.layout.title.text:
        title = fig.layout.title.text
    names = [str(y) for y in tr.y]
    vals = [float(x) for x in tr.x]
    colors = tr.marker.color
    if not isinstance(colors, list):
        colors = [colors] * len(vals)
    colors = [_hex_to_mpl(c) for c in colors]

    h = max(3.2, 0.42 * len(names) + 1.2)
    fig_mpl, ax = plt.subplots(figsize=(11, h), dpi=dpi)
    fig_mpl.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.barh(names, vals, color=colors, height=0.55)
    for i, (n, v) in enumerate(zip(names, vals)):
        ax.text(v + 0.02, i, f"{v:.3f}%", va="center", color="#e5e7eb", fontsize=9)
    ax.set_xlim(98.8, 100)
    ax.set_title(title, color="#e5e7eb", fontsize=13, pad=14)
    ax.tick_params(axis="both", colors="#9ca3af")
    ax.invert_yaxis()
    ax.grid(axis="x", color="#ffffff15")
    for s in ax.spines.values():
        s.set_color("#ffffff20")
    plt.tight_layout()
    plt.savefig(path, facecolor="#1a1a2e", bbox_inches="tight", pad_inches=0.2)
    plt.close(fig_mpl)


def export_sparkline_mpl(fig, path: Path, dpi: int = 120, wide: bool = False) -> None:
    plt = _mpl_setup()
    traces = [t for t in fig.data if getattr(t, "type", None) == "scatter"]
    if not traces:
        raise ValueError("expected scatter trace")
    tr = traces[0]
    x = list(tr.x)
    y = list(tr.y)
    line_c = "#00d9a5"
    if tr.line and tr.line.color:
        line_c = tr.line.color if isinstance(tr.line.color, str) else line_c
    fill_c = line_c

    w_in, h_in = (12, 3.2) if wide else (4.2, 1.35)
    fig_mpl, ax = plt.subplots(figsize=(w_in, h_in), dpi=dpi)
    fig_mpl.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    y0 = min(0.0, min(y))
    ax.fill_between(x, y, y2=y0, alpha=0.25, color=fill_c)
    ax.plot(x, y, color=line_c, linewidth=2)
    ax.axhline(0.55, color="#ffffff40", linewidth=1, linestyle=":")
    ax.set_xlim(0, max(x) if x else 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.tight_layout(pad=0.1)
    plt.savefig(path, facecolor="#1a1a2e", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig_mpl)


def _is_stacked_single_row(fig) -> bool:
    bars = [t for t in fig.data if getattr(t, "type", None) == "bar"]
    if len(bars) < 2:
        return False

    def _y_key(tr):
        if tr.y is None:
            return ()
        return tuple(str(v) for v in tr.y)

    ysets = {_y_key(t) for t in bars}
    if len(ysets) != 1:
        return False
    only = next(iter(ysets))
    return only == () or only == ("",)


def _is_region_style(fig) -> bool:
    bars = [t for t in fig.data if getattr(t, "type", None) == "bar"]
    return len(bars) == 1 and bars[0].orientation == "h" and bars[0].y and len(bars[0].y) > 1


def write_figure_png(fig, path: Path, width: int = 1320, height: int = 400, scale: int = 2) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _kaleido_write(fig, path, width=width, height=height, scale=scale):
        return True
    try:
        scatters = [t for t in fig.data if getattr(t, "type", None) == "scatter"]
        bars = [t for t in fig.data if getattr(t, "type", None) == "bar"]
        if scatters and not bars:
            export_sparkline_mpl(fig, path, wide=(width >= 900))
            return path.is_file()
        if _is_region_style(fig):
            export_region_bars_mpl(fig, path)
            return path.is_file()
        if _is_stacked_single_row(fig) or (len(bars) >= 1 and bars[0].orientation == "h"):
            export_stacked_h_bar_mpl(fig, path)
            return path.is_file()
    except Exception:
        pass
    return False


def write_sparkline_png(fig, path: Path, width: int = 520, height: int = 200) -> bool:
    if _kaleido_write(fig, path, width=width, height=height, scale=2):
        return True
    try:
        export_sparkline_mpl(fig, path, wide=False)
        return path.is_file()
    except Exception:
        return False


def write_wide_spark_png(fig, path: Path) -> bool:
    if _kaleido_write(fig, path, width=1280, height=320, scale=2):
        return True
    try:
        export_sparkline_mpl(fig, path, wide=True)
        return path.is_file()
    except Exception:
        return False
