from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from typing import Any

from anthropic import Anthropic


# ============================================================================
# SYSTEM PROMPT FOR AI BRIEF GENERATION
# ============================================================================

BRIEFING_SYSTEM_PROMPT = """You are the senior portfolio analyst for a concentrated, high-conviction investment firm managing approximately $900 million in assets under management. The CEO and investment team read your intelligence brief before anything else each morning. Your singular purpose is to synthesize raw market data into actionable investment intelligence—not to summarize it.

PORTFOLIO CONTEXT & PHILOSOPHY:
- PLTR (Palantir) is the anchor position (~30% of portfolio), a core strategic holding
- The firm runs deeply concentrated positions (not diversified); thesis quality and moat strength matter far more than sector balance
- Investment conviction centers on: monopolistic businesses with pricing power, long-term competitive moats, founder-aligned incentive structures, and secular growth tailwinds
- The CEO's operating principle: "Never be surprised by material events." Your job is to surface the signals that matter before consensus does
- Priority holdings: PLTR, NVDA, TSLA, META, AMZN, GOOGL, AMD, SOFI, UBER, MSFT, AAPL, JPM, COST, ABNB, AFRM, HIMS, NU, ASML

WRITING DISCIPLINE:
- Lead with what matters. The single most important signal today gets top real estate. If the market is pricing a tariff shock, lead with that. If earnings are revealing a cycle inflection, lead with that. Always explain WHY it matters for THIS portfolio specifically.
- Be direct and opinionated. Hedge only when genuine uncertainty exists. Avoid "could," "might," "may"; use "is," "signals," "suggests."
- Cross-reference data points. If TSLA is down 4% pre-market AND Elon is making a material announcement about robotics, connect those dots explicitly. If NVDA is flat but GPU shipments to China are questioned, name the disconnect.
- Name the trade setup when you see one. "This looks like a crowded long ready to fade," or "This is a classic contrarian entry," or "Ignore the noise—the thesis is intact." Help the CEO calibrate conviction.
- If something is noise, say so and explain why. Don't let signal get buried in data.
- Use concrete numbers and percentages. Avoid vague qualifiers like "significant" or "notable" without context.
- Connect to portfolio mechanics: do these moves validate existing positioning, or do they signal thesis drift?
- Maximum 800 words across all sections.

OUTPUT STRUCTURE (return as valid JSON with these exact keys):
{
  "what_matters": "1-3 paragraph lead. THE most critical signal today—earnings surprise, macro pivot, holdings catalyst, or market structure break. Always explain the specific impact on the portfolio. This is the section the CEO reads in 30 seconds when running late.",
  "market_context": "2-3 sentences on macro backdrop: futures direction, Treasury move, VIX, sector breadth. Not raw numbers—what they mean for positioning. 'Bonds selling hard (10Y up 12bps) while equities rally = risk-on and inflation concerns rising' not just 'S&P +0.5%, 10Y 4.31%.'",
  "premarket_analysis": "Analysis of any portfolio holdings moving >3% pre-market (up or down). For each mover, explain the WHY: earnings miss, sector rotation, company news, macro spillover. Group by theme if patterns exist. Call out if the move is signal or noise: 'AMD down 2.3%—GPU oversupply fears from China slowdown, real thesis risk' vs. 'UBER +1.1% on broader tech recovery, thesis unchanged.'",
  "earnings_intelligence": "Synthesis of recent earnings scorecard (beats/misses) and upcoming reports on the calendar. What do yesterday's misses reveal about the earnings cycle? Margins contracting? Guidance conservative? Which upcoming reports are pivotal for the portfolio? 'AMZN reports Thursday—Street expects AWS margin expansion; watch for cloud pricing comments and capex guidance' not just 'AMZN earnings Thursday.'",
  "news_signal": "The 2-4 genuinely material news items. Explain why each matters for the portfolio—not just 'this is important news' but 'this affects PLTR because of Y, signals Z about the macro.'",
  "watchlist": "2-4 specific tactical things to monitor today: key support/resistance levels, extreme RSI conditions, catalyst timing, earnings premarket/AH, Fed speaker, options expiry effects. Be specific: 'JPM reports pre-market Thursday; Street expects $16.86 EPS—watch trading desk commentary on NIM pressure' not 'JPM earnings this week.'  Include any cross-asset signals (rates, commodities) that will move the portfolio."
}

CRITICAL NOTES:
- Social media intelligence (Elon tweets, executive commentary, creator signals) is handled in a separate 6:20 AM brief. Do NOT force social data into this morning brief. If social alerts are empty, ignore them.
- Your job is market structure, financial performance, and portfolio impact—not social noise.
- If a holdings is down on no news, investigate: market rotation, sector headwind, or irrational? Help the CEO calibrate.
- Earnings surprise synthesis matters enormously. A string of 5% beats might signal conservative guidance. A string of misses might signal cycle inflection.
- RSI extremes and 52-week lows are tactical—mention only if they're actionable (approaching support, oversold entry, contrarian signal).
- Your output is the CEO's input to the day. Make every word count."""


# ============================================================================
# 1. AI BRIEF GENERATION
# ============================================================================

def generate_ai_morning_brief(data: dict[str, Any], api_key: str) -> dict[str, str]:
    """
    Generate an editorial intelligence brief using Claude.

    Args:
        data: Dictionary containing market_snapshot, premarket_movers, filtered_news,
              scorecard, earnings, rsi_alerts, vk_highlights, miss_explanations,
              social_alerts (empty list for morning brief), creator_signals
        api_key: Anthropic API key

    Returns:
        Dictionary with keys: what_matters, market_context, premarket_analysis,
        earnings_intelligence, news_signal, watchlist
    """
    client = Anthropic(api_key=api_key)

    # Build detailed text payload from structured data
    payload = _build_ai_payload(data)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=BRIEFING_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": payload,
                }
            ],
        )

        response_text = message.content[0].text

        # Extract JSON from response (Claude may wrap it in markdown code blocks)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            brief_dict = json.loads(json_match.group())
            # Ensure all required keys exist
            required_keys = [
                "what_matters",
                "market_context",
                "premarket_analysis",
                "earnings_intelligence",
                "news_signal",
                "watchlist",
            ]
            for key in required_keys:
                if key not in brief_dict:
                    brief_dict[key] = ""
            return brief_dict
        else:
            print("ERROR: Could not parse JSON from AI response")
            return _fallback_brief(data)

    except Exception as e:
        print(f"ERROR in AI brief generation: {e}")
        return _fallback_brief(data)


def _build_ai_payload(data: dict[str, Any]) -> str:
    """
    Construct detailed text payload for Claude from structured market data.
    """
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])
    news = data.get("filtered_news", [])
    scorecard = data.get("scorecard", [])
    earnings = data.get("earnings", [])
    rsi = data.get("rsi_alerts", [])
    vk = data.get("vk_highlights", [])
    misses = data.get("miss_explanations", {})

    # Build market snapshot section dynamically (only include available data)
    snapshot_lines = []
    snapshot_fields = [
        ("S&P 500 Futures", "sp500_futures", "sp500_change"),
        ("NASDAQ Futures", "nasdaq_futures", "nasdaq_change"),
        ("10Y Treasury Yield", "treasury_10y", None),
        ("Russell 2000 Futures", "russell2000_futures", "russell2000_change"),
        ("VIX", "vix", "vix_change"),
        ("2Y Treasury Yield", "treasury_2y", None),
        ("Oil (WTI)", "oil_price", "oil_change"),
        ("Gold", "gold_price", "gold_change"),
        ("Dollar Index", "dxy", "dxy_change"),
        ("Bitcoin", "btc_price", "btc_change"),
    ]
    for label, val_key, chg_key in snapshot_fields:
        val = snapshot.get(val_key)
        if val is not None:
            chg = snapshot.get(chg_key) if chg_key else None
            chg_str = f" ({chg})" if chg is not None else ""
            snapshot_lines.append(f"- {label}: {val}{chg_str}")

    snapshot_text = "\n".join(snapshot_lines) if snapshot_lines else "- Market data unavailable"

    payload = f"""
MARKET SNAPSHOT (as of brief generation):
{snapshot_text}

PRE-MARKET MOVERS (>3% or strategically important):
"""

    if movers:
        for mover in movers[:20]:
            sym = mover.get('symbol', 'N/A')
            price = mover.get('price', 'N/A')
            chg = mover.get('change_pct', 0)
            sign = "+" if isinstance(chg, (int, float)) and chg >= 0 else ""
            chg_str = f"{sign}{chg:.1f}%" if isinstance(chg, (int, float)) else str(chg)
            payload += f"- {sym}: ${price} ({chg_str})\n"
    else:
        payload += "- No significant pre-market movers\n"

    payload += "\nRSI ALERTS (extreme conditions):\n"
    if rsi:
        for alert in rsi[:10]:
            payload += f"- {alert.get('symbol', 'N/A')}: RSI {alert.get('current_rsi', 'N/A')} | 52W Low RSI: {alert.get('min_rsi_52w', 'N/A')} | Oversold: {alert.get('is_oversold', False)} | 52W Low: {alert.get('is_52w_low', False)}\n"
    else:
        payload += "- No RSI extremes detected\n"

    payload += "\nEARNINGS SCORECARD (recent reports):\n"
    if scorecard:
        for item in scorecard[:15]:
            beat_status = "BEAT" if item.get('beat') else "MISS"
            payload += f"- {item.get('symbol', 'N/A')}: {beat_status} | EPS: {item.get('eps_actual', 'N/A')} vs {item.get('eps_estimate', 'N/A')} ({item.get('surprise_pct', 'N/A')}) | Revenue: {item.get('rev_beat', 'N/A')} ({item.get('rev_surprise_pct', 'N/A')})\n"
    else:
        payload += "- No recent earnings in portfolio\n"

    payload += "\nEARNINGS CALENDAR (upcoming):\n"
    if earnings:
        for item in earnings[:10]:
            payload += f"- {item.get('symbol', 'N/A')}: {item.get('date', 'N/A')} {item.get('hour', 'N/A')} | Est. EPS: {item.get('eps_estimate', 'N/A')}\n"
    else:
        payload += "- No upcoming earnings in next 5 days\n"

    if misses:
        payload += "\nEARNINGS MISS CONTEXT:\n"
        for symbol, explanation in misses.items():
            payload += f"- {symbol}: {explanation}\n"

    payload += "\nMATERIAL NEWS (filtered for portfolio relevance):\n"
    if news:
        for item in news[:10]:
            payload += f"- [{item.get('ticker', 'N/A')}] {item.get('title', 'N/A')}\n  Category: {item.get('category', 'N/A')} | Summary: {item.get('summary', 'N/A')[:150]}...\n"
    else:
        payload += "- No material news for priority holdings\n"

    if vk:
        payload += "\nVITAL KNOWLEDGE HIGHLIGHTS:\n"
        for item in vk:
            if item.get('text'):
                payload += f"- Tickers: {item.get('tickers', 'N/A')} | {item.get('text', 'N/A')}\n"

    payload += "\nBRIEFING CONTEXT:\n- This is the morning intelligence brief (5:05 AM PT)\n- Social media intelligence is covered in a separate 6:20 AM brief\n- Focus on market structure, financial performance, and direct portfolio impact\n- CEO priority: actionable signals, not noise\n"

    return payload


def _fallback_brief(data: dict[str, Any]) -> dict[str, str]:
    """
    Fallback brief structure if AI generation fails.
    """
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])

    mover_text = "\n".join(
        [f"• {m.get('symbol')}: {m.get('change_pct')}" for m in movers[:5]]
    ) if movers else "• No significant movers"

    return {
        "what_matters": f"S&P futures {snapshot.get('sp500_futures_change', 'flat')} | NASDAQ futures {snapshot.get('nasdaq_futures_change', 'flat')} | 10Y Treasury {snapshot.get('treasury_10y', 'N/A')}. See detailed brief below.",
        "market_context": f"Macro backdrop: Treasuries {'selling' if snapshot.get('treasury_10y', 0) else 'bid'}, equity futures {'strong' if '+' in str(snapshot.get('sp500_futures_change', '')) else 'weak'}.",
        "premarket_analysis": mover_text,
        "earnings_intelligence": "See earnings scorecard in detailed data below.",
        "news_signal": "See filtered news section in detailed data below.",
        "watchlist": "Monitor market open and earnings pre-reports. See calendar below.",
    }


# ============================================================================
# 2. HTML EMAIL FORMATTING
# ============================================================================

def format_morning_html(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """
    Format the morning intelligence brief as a styled HTML email.

    Returns a complete HTML document with inline CSS, MoMA Penguin Books aesthetic:
    black header with red accent, clean serif/sans-serif typography, editorial layout.
    """
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])
    scorecard = data.get("scorecard", [])
    earnings = data.get("earnings", [])
    news = data.get("filtered_news", [])

    now = datetime.now()
    date_str = now.strftime("%A, %B %d")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Morning Intelligence Brief</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f5f0eb; font-family: Georgia, serif; color: #1a1a1a; line-height: 1.6;">

<!-- HEADER BANNER -->
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f0eb;">
<tr>
<td style="padding: 0;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #1a1a1a; border-top: 3px solid #c0392b;">
<tr>
<td style="padding: 32px 40px 24px 40px;">
    <div style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 2px; color: #999; text-transform: uppercase; margin-bottom: 8px;">
        Morning Intelligence
    </div>
    <h1 style="font-family: Georgia, serif; font-size: 32px; font-weight: 400; color: #ffffff; margin: 0 0 8px 0; line-height: 1.2;">
        Morning Brief
    </h1>
    <div style="font-family: Arial, sans-serif; font-size: 13px; color: #cccccc; margin: 0;">
        {date_str}
    </div>
</td>
</tr>
</table>
</td>
</tr>
</table>

<!-- CONTENT -->
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f0eb;">
<tr>
<td align="center" style="padding: 40px 20px;">

<table width="640" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border: 1px solid #e8e3de;">
<tr>
<td style="padding: 40px;">

<!-- WHAT MATTERS -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
1. WHAT MATTERS TODAY
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 32px; line-height: 1.7;">
{ai_brief.get('what_matters', 'No data available')}
</div>

<!-- MARKET CONTEXT -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
2. MARKET CONTEXT
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 32px; line-height: 1.7;">
{ai_brief.get('market_context', 'No data available')}
</div>

{_format_snapshot_table(snapshot)}

<!-- PRE-MARKET ANALYSIS -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
3. PRE-MARKET ANALYSIS
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 24px; line-height: 1.7;">
{ai_brief.get('premarket_analysis', 'No significant pre-market movers')}
</div>

{_format_movers_table(movers) if movers else '<div style="font-family: Arial, sans-serif; font-size: 13px; color: #666; margin-bottom: 32px;">No pre-market movers >3%</div>'}

<!-- EARNINGS INTELLIGENCE -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
4. EARNINGS INTELLIGENCE
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 24px; line-height: 1.7;">
{ai_brief.get('earnings_intelligence', 'No recent earnings or upcoming reports')}
</div>

{_format_scorecard_table(scorecard) if scorecard else ''}

<!-- NEWS SIGNAL -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
5. NEWS SIGNAL
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 32px; line-height: 1.7;">
{ai_brief.get('news_signal', 'No material news identified')}
</div>

<!-- WATCHLIST -->
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
6. WATCHLIST
</h2>
<div style="font-family: Georgia, serif; font-size: 15px; color: #1a1a1a; margin-bottom: 40px; line-height: 1.7;">
{ai_brief.get('watchlist', 'Monitor market open and earnings pre-reports')}
</div>

<!-- APPENDIX: RAW DATA -->
<hr style="border: none; border-bottom: 2px solid #e8e3de; margin: 40px 0;">

<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #666; margin: 32px 0 16px 0; text-transform: uppercase; letter-spacing: 1px;">
APPENDIX: DETAILED DATA
</h3>

{_format_full_earnings_table(scorecard, earnings) if scorecard or earnings else '<p style="font-family: Arial, sans-serif; font-size: 13px; color: #999;">No earnings data available</p>'}

{_format_full_news_table(news) if news else '<p style="font-family: Arial, sans-serif; font-size: 13px; color: #999;">No news data available</p>'}

<!-- FOOTER -->
<div style="margin-top: 40px; padding-top: 24px; border-top: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px; color: #999; line-height: 1.6;">
    <div style="margin-bottom: 12px;">85 holdings · {time_str}</div>
    <div style="color: #bbb;">Full brief data complete. Next update: 6:20 AM PT (Social Intelligence Brief)</div>
</div>

</td>
</tr>
</table>

</td>
</tr>
</table>

</body>
</html>
"""
    return html


def _format_snapshot_table(snapshot: dict[str, Any]) -> str:
    """Format market snapshot as HTML table, only showing available data."""
    # Define all possible rows: (label, value_key, change_key)
    # Keys match what fetch_market_snapshot actually returns, plus optional extras
    rows_config = [
        ("S&P 500 Futures", "sp500_futures", "sp500_change"),
        ("NASDAQ Futures", "nasdaq_futures", "nasdaq_change"),
        ("10Y Treasury Yield", "treasury_10y", None),
        # Optional fields (only appear if data fetching is expanded)
        ("Russell 2000 Futures", "russell2000_futures", "russell2000_change"),
        ("VIX", "vix", "vix_change"),
        ("2Y Treasury Yield", "treasury_2y", None),
        ("Oil (WTI)", "oil_price", "oil_change"),
        ("Gold", "gold_price", "gold_change"),
        ("Bitcoin", "btc_price", "btc_change"),
        ("Dollar Index", "dxy", "dxy_change"),
    ]

    rows_html = ""
    for label, val_key, chg_key in rows_config:
        val = snapshot.get(val_key)
        if val is None:
            continue  # Skip rows with no data

        # Format value
        if isinstance(val, float):
            if "treasury" in val_key or val_key == "vix":
                val_str = f"{val:.2f}%"
            elif val > 100:
                val_str = f"{val:,.0f}"
            else:
                val_str = f"{val:.2f}"
        else:
            val_str = str(val)

        # Format change
        chg_str = ""
        chg_color = "#1a1a1a"
        if chg_key:
            chg = snapshot.get(chg_key)
            if chg is not None:
                if isinstance(chg, (int, float)):
                    sign = "+" if chg >= 0 else ""
                    chg_str = f"{sign}{chg:.2f}%"
                    chg_color = "#c0392b" if chg < 0 else "#27ae60"
                else:
                    chg_str = str(chg)
                    chg_color = "#c0392b" if "-" in chg_str else "#27ae60"

        rows_html += f"""<tr style="border-bottom: 1px solid #e8e3de;">
    <td>{label}</td>
    <td style="text-align: right;">{val_str}</td>
    <td style="text-align: right; color: {chg_color}; font-weight: 600;">{chg_str}</td>
</tr>"""

    if not rows_html:
        return '<div style="font-family: Arial, sans-serif; font-size: 13px; color: #666; margin-bottom: 32px;">Market snapshot unavailable</div>'

    return f"""
<h2 style="font-family: Arial, sans-serif; font-size: 14px; font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 1px solid #c0392b;">
MARKET SNAPSHOT
</h2>
<table width="100%" cellpadding="10" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;">
    <td style="font-weight: 700; color: #1a1a1a;">Asset</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Price</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Change</td>
</tr>
{rows_html}
</table>
"""


def _format_movers_table(movers: list[dict[str, Any]]) -> str:
    """Format pre-market movers as a clean HTML table."""
    if not movers:
        return ""

    rows = ""
    for mover in movers[:10]:
        symbol = mover.get("symbol", "N/A")
        price = mover.get("price", 0)
        change = mover.get("change_pct", 0)

        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else str(price)
        sign = "+" if isinstance(change, (int, float)) and change >= 0 else ""
        chg_str = f"{sign}{change:.1f}%" if isinstance(change, (int, float)) else str(change)
        color = "#c0392b" if isinstance(change, (int, float)) and change < 0 else "#27ae60"

        rows += f"""
<tr style="border-bottom: 1px solid #e8e3de;">
    <td style="font-weight: 700;">{symbol}</td>
    <td style="text-align: right;">{price_str}</td>
    <td style="text-align: right; color: {color}; font-weight: 600;">{chg_str}</td>
</tr>
"""

    return f"""
<table width="100%" cellpadding="10" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;">
    <td style="font-weight: 700; color: #1a1a1a;">Ticker</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Price</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Change</td>
</tr>
{rows}
</table>
"""


def _format_scorecard_table(scorecard: list[dict[str, Any]]) -> str:
    """Format recent earnings scorecard."""
    if not scorecard:
        return ""

    rows = ""
    for item in scorecard[:8]:
        symbol = item.get("symbol", "N/A")
        beat_status = "BEAT" if item.get("beat") else "MISS"
        eps_actual = item.get("eps_actual", 0)
        eps_estimate = item.get("eps_estimate", 0)
        surprise = item.get("surprise_pct", 0)

        badge_color = "#27ae60" if beat_status == "BEAT" else "#c0392b"
        eps_a_str = f"${eps_actual:.2f}" if isinstance(eps_actual, (int, float)) else str(eps_actual)
        eps_e_str = f"${eps_estimate:.2f}" if isinstance(eps_estimate, (int, float)) else str(eps_estimate)
        surp_sign = "+" if isinstance(surprise, (int, float)) and surprise >= 0 else ""
        surp_str = f"{surp_sign}{surprise:.1f}%" if isinstance(surprise, (int, float)) else str(surprise)
        surp_color = "#27ae60" if isinstance(surprise, (int, float)) and surprise >= 0 else "#c0392b"

        rows += f"""
<tr style="border-bottom: 1px solid #e8e3de;">
    <td style="font-weight: 700;">{symbol}</td>
    <td style="color: {badge_color}; font-weight: 600; text-align: center;">{beat_status}</td>
    <td style="text-align: right;">{eps_a_str}</td>
    <td style="text-align: right; color: #999;">{eps_e_str}</td>
    <td style="text-align: right; color: {surp_color}; font-weight: 600;">{surp_str}</td>
</tr>
"""

    return f"""
<table width="100%" cellpadding="10" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;">
    <td style="font-weight: 700; color: #1a1a1a;">Ticker</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: center;">Result</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Actual EPS</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Est. EPS</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Surprise %</td>
</tr>
{rows}
</table>
"""


def _format_full_earnings_table(scorecard: list[dict[str, Any]], earnings: list[dict[str, Any]]) -> str:
    """Format full earnings scorecard and calendar in appendix."""
    html = ""

    if scorecard:
        html += '<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Recent Earnings</h4>'
        html += '<table width="100%" cellpadding="8" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px;">'
        html += '<tr style="background-color: #ebe7e1;"><td style="font-weight: 700;">Ticker</td><td>Result</td><td>EPS Act./Est.</td><td>Rev. Beat</td></tr>'

        for item in scorecard[:15]:
            symbol = item.get("symbol", "N/A")
            beat = "BEAT" if item.get("beat") else "MISS"
            eps_a = item.get("eps_actual", "N/A")
            eps_e = item.get("eps_estimate", "N/A")
            rev = item.get("rev_beat", "N/A")

            html += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="font-weight: 700;">{symbol}</td><td>{beat}</td><td>{eps_a} / {eps_e}</td><td>{rev}</td></tr>'

        html += '</table>'

    if earnings:
        html += '<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Upcoming Earnings Calendar</h4>'
        html += '<table width="100%" cellpadding="8" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px;">'
        html += '<tr style="background-color: #ebe7e1;"><td style="font-weight: 700;">Ticker</td><td>Date</td><td>Hour</td><td>Est. EPS</td></tr>'

        for item in earnings[:10]:
            symbol = item.get("symbol", "N/A")
            date = item.get("date", "N/A")
            hour = item.get("hour", "N/A")
            eps_est = item.get("eps_estimate", "N/A")

            html += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="font-weight: 700;">{symbol}</td><td>{date}</td><td>{hour}</td><td>{eps_est}</td></tr>'

        html += '</table>'

    return html


def _format_full_news_table(news: list[dict[str, Any]]) -> str:
    """Format full news list in appendix."""
    if not news:
        return ""

    html = '<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Filtered News</h4>'

    for item in news[:15]:
        ticker = item.get("ticker", "N/A")
        title = item.get("title", "N/A")
        category = item.get("category", "N/A")
        summary = item.get("summary", "N/A")
        link = item.get("link", "#")

        html += f"""
<div style="margin-bottom: 16px; padding: 12px; background-color: #f9f7f5; border-left: 3px solid #c0392b;">
    <div style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #1a1a1a; margin-bottom: 4px;">
        [{ticker}] {title}
    </div>
    <div style="font-family: Arial, sans-serif; font-size: 11px; color: #999; margin-bottom: 6px;">{category}</div>
    <div style="font-family: Georgia, serif; font-size: 12px; color: #1a1a1a; margin-bottom: 8px; line-height: 1.5;">{summary}</div>
    <a href="{link}" style="font-family: Arial, sans-serif; font-size: 11px; color: #c0392b; text-decoration: none; font-weight: 600;">Read more →</a>
</div>
"""

    return html


# ============================================================================
# 3. PLAIN TEXT FORMATTING FOR iMESSAGE
# ============================================================================

def format_morning_text(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """
    Format the morning intelligence brief as plain text for iMessage delivery.
    Uses box-drawing characters and editorial voice.

    Returns a string optimized for multi-part iMessage delivery (split at ~4000 chars).
    """
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])
    scorecard = data.get("scorecard", [])
    earnings = data.get("earnings", [])

    now = datetime.now()
    date_str = now.strftime("%A, %B %d")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    text = f"""
┌─────────────────────────────────────────┐
│   MORNING INTELLIGENCE                  │
│   {date_str:<35} │
└─────────────────────────────────────────┘

▸ WHAT MATTERS

{ai_brief.get('what_matters', 'No data available')}

▸ MARKET SNAPSHOT

{_format_snapshot_text(snapshot)}

▸ PRE-MARKET ANALYSIS

{ai_brief.get('premarket_analysis', 'No significant movers')}
"""

    if movers:
        text += "\nPRE-MARKET MOVERS:\n"
        for mover in movers[:10]:
            symbol = mover.get("symbol", "N/A")
            price = mover.get("price", "N/A")
            change = mover.get("change_pct", "N/A")
            text += f"  {symbol:<6} {price:>8}  {change:>8}\n"

    text += f"""
▸ EARNINGS INTELLIGENCE

{ai_brief.get('earnings_intelligence', 'No recent earnings')}
"""

    if scorecard:
        text += "\nRECENT SCORES:\n"
        for item in scorecard[:8]:
            symbol = item.get("symbol", "N/A")
            beat_status = "✓ BEAT" if item.get("beat") else "✗ MISS"
            surprise = item.get("surprise_pct", "N/A")
            text += f"  {symbol:<6} {beat_status:<8} EPS {surprise:>8}\n"

    text += f"""
▸ NEWS SIGNAL

{ai_brief.get('news_signal', 'No material news identified')}

▸ WATCHLIST

{ai_brief.get('watchlist', 'Monitor market open and earnings')}

───────────────────────────────────────────
85 holdings · {time_str}
Full brief + data → email
"""

    return text


# ============================================================================
# 4. EMAIL SENDING VIA APPLE MAIL APPLESCRIPT
# ============================================================================

def send_html_email(
    recipient: str,
    subject: str,
    html_body: str,
    max_retries: int = 3,
) -> bool:
    """
    Send an HTML email via Apple Mail using AppleScript.

    Args:
        recipient: Email address of recipient
        subject: Email subject line
        html_body: HTML content (will be properly escaped for AppleScript)
        max_retries: Number of retry attempts on failure

    Returns:
        True if successful, False otherwise
    """

    def _wake_app(app_name: str) -> None:
        """Activate an app to wake it from App Nap before sending Apple Events."""
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to activate'],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(2)  # Give app time to fully wake
        except Exception:
            pass  # Best effort — continue even if activate fails

    # Escape HTML for AppleScript embedding
    escaped_html = html_body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\r")
    escaped_subject = subject.replace('"', '\\"')

    # Wake Mail.app from App Nap (critical for 5 AM launchd runs)
    _wake_app("Mail")

    applescript = f'''
    with timeout of 300 seconds
        tell application "Mail"
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", visible:false}}
            tell newMessage
                set html content to "{escaped_html}"
                make new to recipient at end of to recipients with properties {{address:"{recipient}"}}
                send
            end tell
        end tell
    end timeout
    '''

    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(
                ["osascript", "-e", applescript],
                check=True,
                capture_output=True,
                text=True,
                timeout=320,
            )
            print(f"✓ HTML email sent to {recipient}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  ✗ HTML email attempt {attempt}/{max_retries}: {e.stderr.strip()}")
            if attempt < max_retries:
                print(f"    Retrying in 5s (re-activating Mail.app)...")
                _wake_app("Mail")
                time.sleep(3)
        except subprocess.TimeoutExpired:
            print(f"  ✗ HTML email attempt {attempt}/{max_retries}: Python subprocess timeout (320s)")
            if attempt < max_retries:
                _wake_app("Mail")
                time.sleep(3)

    print(f"✗ Failed to send HTML email after {max_retries} attempts")
    return False


# ============================================================================
# 5. MAIN ORCHESTRATION FUNCTION
# ============================================================================

def run_morning_briefing_v2(
    api_key: str,
    email_recipient: str,
    imessage_recipient: str,
    market_snapshot: dict[str, Any],
    premarket_movers: list[dict[str, Any]],
    filtered_news: list[dict[str, Any]],
    scorecard: list[dict[str, Any]],
    earnings: list[dict[str, Any]],
    rsi_alerts: list[dict[str, Any]],
    vk_highlights: list[dict[str, Any]],
    miss_explanations: dict[str, str],
) -> None:
    """
    Run the complete morning briefing pipeline: AI generation, formatting, and delivery.

    This function:
    1. Bundles all market data
    2. Generates AI-powered editorial brief
    3. Formats HTML email and plain text iMessage
    4. Sends both via Apple Mail and Messages.app

    Args:
        api_key: Anthropic API key
        email_recipient: Email address for HTML brief
        imessage_recipient: Phone number or email for iMessage
        [All other args: market data as collected by existing functions]
    """

    print("\n" + "=" * 70)
    print("MORNING BRIEFING v2 - STARTING")
    print("=" * 70)

    # Bundle all data
    data = {
        "market_snapshot": market_snapshot,
        "premarket_movers": premarket_movers,
        "filtered_news": filtered_news,
        "scorecard": scorecard,
        "earnings": earnings,
        "rsi_alerts": rsi_alerts,
        "vk_highlights": vk_highlights,
        "miss_explanations": miss_explanations,
        "social_alerts": [],  # Morning brief has no social data
        "creator_signals": [],
    }

    print("\n[1/4] Generating AI intelligence brief...")
    ai_brief = generate_ai_morning_brief(data, api_key)
    print("✓ AI brief generated")

    print("\n[2/4] Formatting HTML email...")
    html_email = format_morning_html(ai_brief, data)
    print(f"✓ HTML email formatted ({len(html_email)} bytes)")

    print("\n[3/4] Formatting plain text iMessage...")
    text_message = format_morning_text(ai_brief, data)
    print(f"✓ Plain text formatted ({len(text_message)} chars)")

    print("\n[4/4] Sending via Apple Mail and Messages...")

    # Send HTML email
    email_sent = send_html_email(
        recipient=email_recipient,
        subject=f"Morning Brief – {datetime.now().strftime('%b %d')}",
        html_body=html_email,
    )

    # Send iMessage (uses existing send_imessage from morning_briefing.py)
    # This function must be imported or called from the main script
    imessage_sent = send_imessage(imessage_recipient, text_message)

    # Summary
    print("\n" + "=" * 70)
    if email_sent and imessage_sent:
        print("✓ MORNING BRIEFING COMPLETE – Email and iMessage sent")
    elif email_sent:
        print("⚠ PARTIAL – Email sent, iMessage failed")
    elif imessage_sent:
        print("⚠ PARTIAL – iMessage sent, Email failed")
    else:
        print("✗ BRIEFING FAILED – Both deliveries unsuccessful")
    print("=" * 70 + "\n")


def _format_snapshot_text(snapshot: dict[str, Any]) -> str:
    """Format market snapshot as plain text, only showing available data."""
    rows_config = [
        ("S&P Futures", "sp500_futures", "sp500_change"),
        ("NASDAQ Futures", "nasdaq_futures", "nasdaq_change"),
        ("10Y Treasury", "treasury_10y", None),
        ("Russell 2000", "russell2000_futures", "russell2000_change"),
        ("VIX", "vix", "vix_change"),
        ("Oil (WTI)", "oil_price", "oil_change"),
        ("Gold", "gold_price", "gold_change"),
        ("Bitcoin", "btc_price", "btc_change"),
    ]

    lines = []
    for label, val_key, chg_key in rows_config:
        val = snapshot.get(val_key)
        if val is None:
            continue

        if isinstance(val, float):
            if "treasury" in val_key or val_key == "vix":
                val_str = f"{val:.2f}%"
            elif val > 100:
                val_str = f"{val:,.0f}"
            else:
                val_str = f"{val:.2f}"
        else:
            val_str = str(val)

        chg_str = ""
        if chg_key:
            chg = snapshot.get(chg_key)
            if chg is not None:
                if isinstance(chg, (int, float)):
                    arrow = "▲" if chg >= 0 else "▼"
                    sign = "+" if chg >= 0 else ""
                    chg_str = f" {arrow} {sign}{chg:.2f}%"
                else:
                    chg_str = f" {chg}"

        lines.append(f"  {label:<18} {val_str:>10}{chg_str}")

    return "\n".join(lines) if lines else "  Market data unavailable"


# NOTE: For iMessage delivery, reuse the existing send_imessage() function
# from morning_briefing.py — it has proper chunking, retry logic, and the
# correct AppleScript pattern for the iMac's Messages.app configuration.
# Do NOT rewrite the iMessage sender here.


# ============================================================================
# END OF FILE
# ============================================================================
