"""
Build a PowerPoint deck documenting the Site-Level Analysis Streamlit dashboard.

  pip install python-pptx
  python create_site_level_analysis_deck.py

Output: Site_Level_Analysis_Dashboard.pptx
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

MAGENTA = RGBColor(233, 69, 96)
DARK_BG = RGBColor(26, 26, 46)
WHITE = RGBColor(255, 255, 255)
LIGHT_GRAY = RGBColor(200, 200, 200)
BLUE = RGBColor(0, 180, 216)
GREEN = RGBColor(0, 217, 165)
ORANGE = RGBColor(247, 127, 0)
CARD_BG = RGBColor(40, 40, 60)


def _blank_slide(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK_BG
    bg.line.fill.background()
    return slide


def add_title_slide(prs: Presentation, title: str, subtitle: str) -> None:
    slide = _blank_slide(prs)
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(2.4), Inches(12.333), Inches(1.4))
    p = tb.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(48)
    p.font.bold = True
    p.font.color.rgb = MAGENTA
    p.alignment = PP_ALIGN.CENTER

    sb = slide.shapes.add_textbox(Inches(0.5), Inches(3.9), Inches(12.333), Inches(1))
    p = sb.text_frame.paragraphs[0]
    p.text = subtitle
    p.font.size = Pt(22)
    p.font.color.rgb = LIGHT_GRAY
    p.alignment = PP_ALIGN.CENTER

    db = slide.shapes.add_textbox(Inches(0.5), Inches(6.5), Inches(12.333), Inches(0.5))
    p = db.text_frame.paragraphs[0]
    p.text = datetime.now().strftime("%B %d, %Y")
    p.font.size = Pt(16)
    p.font.color.rgb = LIGHT_GRAY
    p.alignment = PP_ALIGN.CENTER


def add_section_title(prs: Presentation, title: str) -> None:
    slide = _blank_slide(prs)
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(3), Inches(12.333), Inches(1.2))
    p = tb.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = MAGENTA
    p.alignment = PP_ALIGN.CENTER


def add_bullet_slide(prs: Presentation, title: str, bullets: list[str], footer: str | None = None) -> None:
    slide = _blank_slide(prs)
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.333), Inches(0.75))
    p = tb.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = MAGENTA

    bb = slide.shapes.add_textbox(Inches(0.75), Inches(1.2), Inches(11.8), Inches(5.6))
    tf = bb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(bullets):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = f"• {line}"
        para.font.size = Pt(20)
        para.font.color.rgb = WHITE
        para.space_after = Pt(14)
        para.level = 0

    if footer:
        fb = slide.shapes.add_textbox(Inches(0.5), Inches(6.85), Inches(12.333), Inches(0.45))
        p = fb.text_frame.paragraphs[0]
        p.text = footer
        p.font.size = Pt(14)
        p.font.color.rgb = LIGHT_GRAY


def add_metrics_slide(prs: Presentation, title: str, metrics: list[tuple[str, str, RGBColor]]) -> None:
    slide = _blank_slide(prs)
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.333), Inches(0.75))
    p = tb.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = MAGENTA

    card_w, card_h = Inches(3.85), Inches(1.85)
    gap = Inches(0.28)
    sx, sy = Inches(0.5), Inches(1.25)

    for i, (label, value, color) in enumerate(metrics):
        row, col = divmod(i, 3)
        x = sx + col * (card_w + gap)
        y = sy + row * (card_h + gap)

        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, card_w, card_h)
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = color
        card.line.width = Pt(2)

        vb = slide.shapes.add_textbox(x, y + Inches(0.25), card_w, Inches(0.95))
        vp = vb.text_frame.paragraphs[0]
        vp.text = str(value)
        vp.font.size = Pt(36)
        vp.font.bold = True
        vp.font.color.rgb = color
        vp.alignment = PP_ALIGN.CENTER

        lb = slide.shapes.add_textbox(x, y + Inches(1.15), card_w, Inches(0.55))
        lp = lb.text_frame.paragraphs[0]
        lp.text = label
        lp.font.size = Pt(14)
        lp.font.color.rgb = LIGHT_GRAY
        lp.alignment = PP_ALIGN.CENTER


def main() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    add_title_slide(
        prs,
        "Site-Level Analysis Dashboard",
        "Streamlit network availability, COTTR, and customer-impact views",
    )

    add_bullet_slide(
        prs,
        "Purpose",
        [
            "Single dark-theme operations view aligned to field and executive workflows.",
            "Tracks availability %, downtime vs budget, outages, customer minutes, and impacted subscribers.",
            "Separates Availability vs COTTR category mix (summary and focus hierarchies).",
            "Supports drill paths: enterprise → region → market → site / incident context.",
            "Current build uses representative sample metrics; production binds to Snowflake / hourly extracts.",
        ],
    )

    add_bullet_slide(
        prs,
        "Navigation (eight tabs)",
        [
            "Executive Summary — national rollup, summary category bars, region spotlight table.",
            "Site Analysis — six KPI cards with sparklines, four stacked breakdown charts, Field Ops tables.",
            "Region Availability — regional availability bars, per-region category mix, rollup table.",
            "Area Availability — market-level availability, focus charts, market budget table.",
            "Availability Detail — planned vs unplanned, vendor/technology slices, top downtime sites.",
            "COTTR Detail — COTTR index, resolution/priority mix, COTTR by region.",
            "Customer Minutes Detail — CM drivers, normalized KPIs, top CM events.",
            "Data Diagnostics — load freshness, QA checks, partition and late-arrival views.",
        ],
        footer="Streamlit runs all tab bodies each rerun; each Plotly widget uses a unique key prefix per tab.",
    )

    add_metrics_slide(
        prs,
        "Executive Summary — sample KPIs",
        [
            ("Network availability", "99.58%", GREEN),
            ("Downtime (enterprise)", "412.7M sec", GREEN),
            ("Outage events", "2,847", ORANGE),
            ("Outage minutes", "428K", ORANGE),
            ("Customer minutes", "18.2M", MAGENTA),
            ("Impacted subscribers", "512K", MAGENTA),
        ],
    )

    add_bullet_slide(
        prs,
        "Site Analysis — layout",
        [
            "KPI row: daily availability, downtime vs budget, outage events/minutes, customer minutes, impacted subs.",
            "Charts: Availability summary + focus; COTTR summary + focus (horizontal stacked 100% bars).",
            "Tables: Field Ops assignment groups and managers (Down, Avail%, budget bar, variance, site counts).",
            "Color language: green availability, pink/red downtime and over-budget, orange operational load.",
        ],
    )

    add_bullet_slide(
        prs,
        "Region & area views",
        [
            "Region Availability: horizontal bars of availability % by region; compare South vs Northeast mix.",
            "Area Availability: market-level bars (e.g., West), focus category charts, market downtime table.",
            "Intended use: identify which geography drives enterprise misses before opening Site Analysis.",
        ],
    )

    add_bullet_slide(
        prs,
        "Detail tabs",
        [
            "Availability Detail: driver breakdown, vendor and RAT/technology slices, largest site drags.",
            "COTTR Detail: time-to-restore narrative, chronic tickets, resolution and priority distributions.",
            "Customer Minutes Detail: CM root-cause mix and highest-impact tickets/changes.",
            "Data Diagnostics: pipeline SLA, null/dup checks, ingest trend, source QA checklist.",
        ],
    )

    add_bullet_slide(
        prs,
        "Implementation & deployment",
        [
            "App: app_site_level_analysis.py — Streamlit + Plotly + NumPy (sparkline data).",
            "Repository: github.com/jvcjvcjvc-tech/streamlit-dashboards (streamlit run app_site_level_analysis.py).",
            "Streamlit Community Cloud: set main file path to app_site_level_analysis.py; requirements.txt installs dependencies.",
            "Next step: replace sample DataFrames with Snowflake queries or Parquet/CSV from VQTM hourly feeds.",
        ],
    )

    add_bullet_slide(
        prs,
        "Summary",
        [
            "End-to-end storyboard from executive KPIs through regional, market, and diagnostic depth.",
            "Consistent visual system matches dark operations dashboards and T-Mobile-style magenta accents.",
            "Ready for stakeholder walkthrough; data binding is the remaining production task.",
        ],
    )

    add_title_slide(prs, "Thank you", "Site-Level Analysis Dashboard documentation")

    out = Path(__file__).resolve().parent / "Site_Level_Analysis_Dashboard.pptx"
    prs.save(str(out))
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
