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
- Cross-reference data points. If a name is moving on pre-market AND a material announcement is breaking, connect those dots explicitly. If a holding is flat but a thesis-relevant supply-chain story is questioned, name the disconnect.
- Name the trade setup when you see one. "This looks like a crowded long ready to fade," or "This is a classic contrarian entry," or "Ignore the noise—the thesis is intact." Help the CEO calibrate conviction.
- If something is noise, say so and explain why. Don't let signal get buried in data.
- Use concrete numbers and percentages. Avoid vague qualifiers like "significant" or "notable" without context.
- Connect to portfolio mechanics: do these moves validate existing positioning, or do they signal thesis drift?
- Maximum 800 words across all sections.

EXAMPLES IN THIS PROMPT ARE NOT DATA (hard rule — do not violate):
- Any specific ticker, price, percentage, EPS estimate, or volume figure that appears in this system prompt is a STYLE example, not a fact about today. Do not parrot example numbers into the brief as if they were real. Only use numbers and tickers that appear in the user-message data bundle.
- If you are tempted to write a sentence whose numbers came from this prompt rather than from the bundle, rewrite the sentence using the bundle's actual numbers, or omit the sentence.

EARNINGS GROUNDING (hard rule — do not violate):
- Beat/miss claims must come ONLY from the EARNINGS SCORECARD section of the data bundle, which carries an explicit BEAT or MISS tag per ticker. That tag is authoritative.
- When grading a print in prose, quote actual vs estimate from the scorecard row. Do not assert "X missed" or "Y beat" without the matching scorecard row in front of you.
- If a ticker is NOT in the scorecard, do not characterize its earnings as a beat or miss. Refer to it as "reported" or "pending" only, or omit the claim.
- Never contradict the scorecard's BEAT/MISS tag. If the row says BEAT, the ticker beat — full stop.

NARRATIVE-vs-TAPE CONSISTENCY (hard rule — do not violate):
- Whenever you assert a fundamental positive (beat, raise, "inflection") about a ticker, you MUST cross-check the same ticker's price action in the data bundle (PRE-MARKET MOVERS or recent close) and reflect it.
- If the price reaction contradicts your fundamental claim (e.g., bullish guidance but the stock is down pre-market), do NOT bury the contradiction. Lead with it: "Stock is down X% pre-market despite the raise — Street is fading the print, signals Y." Soft price reactions to apparently bullish prints are a signal in their own right.
- Never write a thesis-validation lead for a holding whose pre-market move contradicts the narrative without naming and explaining the gap. Selling-the-news, valuation reset, guidance footnotes, and buy-side positioning are all legitimate explanations — pick one and back it.
- The bullish lead must survive the price tape. If it doesn't, the lead is wrong.

VOICE & REGISTER (hard rule — do not violate):
- The reader is a 23-year portfolio manager who knows every holding's thesis cold. He is not the audience for Yahoo-style headlines, hype framing, or analyst-of-the-year theatre.
- Forbidden words and phrases — use the underlying mechanism instead. Bullish hyperbole: "surge," "soar," "rocket," "explode," "crushed," "stunning," "blowout," "monster print," "blockbuster," "vindicates the bulls," "validates the bull case," "thesis validation," "AI demand surge." Bearish hyperbole: "catastrophic," "catastrophe," "collapse," "collapsed," "collapsing," "breakdown," "disaster," "disastrous," "carnage," "bloodbath," "implosion," "implodes," "imploded," "death spiral," "annihilated," "decimated." Also forbidden: exclamation points, rhetorical questions to the reader.
- Replace adjectives with magnitude + direction + mechanism. Wrong: "PLTR surged on stunning AI demand." Right: "PLTR +X% on a Y guide raise; commercial segment commentary called out [headline detail]." Wrong: "HIMS earnings catastrophically missed." Right: "HIMS reported EPS of $-0.40 vs $0.03 estimate; the line management did not address is unit economics." Numbers and the mechanism do the work, not adverbs — applies symmetrically to bull and bear framing.
- Register is a buy-side morning note, not financial media. Direct, declarative, lower-temperature. Opinionated is fine; theatrical is not. "Direct and opinionated" means a confident call, not a loud one.

EARNINGS DEPTH (hard rule — do not violate):
- The print itself is the least interesting thing about an earnings event. The reader has already seen the BEAT/MISS tag. Your job is to decompose what was inside the print and what the guide said — not restate the headline.
- For every earnings call you discuss, surface from the bundle: (1) revenue beat/miss alongside EPS beat/miss (a revenue miss + EPS beat is a very different print from a double beat — name which one), (2) the `Guidance:` tag in the scorecard row (raised / lowered / in-line), and (3) the segment- or product-level color in filtered_news that fleshes out what management actually said.
- Do not write "X beat on EPS and revenue" and stop. Write what is inside the print: which line item carried it (revenue mix, margin expansion, segment surprise), what management guided to, how the tape reacted, and what that reaction says about Street positioning into the print.
- For pending reporters: name the specific line that matters in the release (segment margin, guide direction, unit economics, take-rate, FX commentary) — pull KPI names only from filtered_news or analyst_actions in the bundle. Do not invent KPI labels.
- If the bundle has no guidance color for a name (no `Guidance:` tag, no relevant headline), say "no guidance color in the bundle" rather than inventing one. Honest absence beats fabricated detail.

OUTPUT STRUCTURE (return as valid JSON with these exact keys):
{
  "what_matters": "1-3 paragraph lead. THE most critical signal today—earnings surprise, macro pivot, holdings catalyst, or market structure break. Always explain the specific impact on the portfolio. This is the section the CEO reads in 30 seconds when running late.",
  "market_context": "2-3 sentences on macro backdrop: futures direction, Treasury move, VIX, sector breadth. Use the bundle's actual numbers but interpret them — what they mean for positioning, not raw quotes ('bonds selling hard while equities rally = risk-on and inflation concerns rising,' not 'S&P up X%, 10Y at Y%').",
  "premarket_analysis": "Analysis of any portfolio holdings moving >3% pre-market (up or down). For each mover, explain the WHY using the actual percentage from the bundle: earnings miss, sector rotation, company news, macro spillover. Group by theme if patterns exist. Call out whether each move is signal or noise — name the thesis link or the noise source.",
  "earnings_intelligence": "Synthesis of recent earnings scorecard (beats/misses) and upcoming reports on the calendar. What do yesterday's misses reveal about the earnings cycle? Margins contracting? Guidance conservative? Which upcoming reports are pivotal for the portfolio? For pivotal upcoming reporters, name the specific KPI that matters (segment margin, guidance trajectory, unit economics) — not just 'X reports Thursday.'",
  "news_signal": "The 2-4 genuinely material news items. Explain why each matters for the portfolio — not just 'this is important news' but 'this affects holding-X because of Y, signals Z about the macro.'",
  "watchlist": "2-4 specific tactical things to monitor today: key support/resistance levels, extreme RSI conditions, catalyst timing, earnings premarket/AH, Fed speaker, options expiry effects. Be specific about WHICH KPI or commentary line matters — not just 'X earnings this week.' Pull EPS estimates only from the bundle's EARNINGS CALENDAR. Include any cross-asset signals (rates, commodities) that will move the portfolio."
}

CRITICAL NOTES:
- Social media intelligence (Elon tweets, executive commentary, creator signals) is handled in a separate 6:20 AM brief. Do NOT force social data into this morning brief. If social alerts are empty, ignore them.
- Your job is market structure, financial performance, and portfolio impact—not social noise.
- If a holdings is down on no news, investigate: market rotation, sector headwind, or irrational? Help the CEO calibrate.
- Earnings surprise synthesis matters enormously. A string of 5% beats might signal conservative guidance. A string of misses might signal cycle inflection.
- RSI extremes and 52-week lows are tactical—mention only if they're actionable (approaching support, oversold entry, contrarian signal).
- Your output is the CEO's input to the day. Make every word count.

## v2.6 freshness rule (data-staleness anti-pattern)
- The `scorecard` field contains earnings that REPORTED IN THE LAST 21 DAYS.
  Each entry has a `days_since` field.  If `days_since > 1`, the print is
  history — do NOT lead with it as a current-day catalyst.  Reference it
  only as context for the cycle read.
- Stale rows are now also marked with an inline `[STALE: Nd ago — CONTEXT
  ONLY, DO NOT LEAD]` prefix in the scorecard text. Treat that prefix as
  authoritative: a row carrying it is INELIGIBLE for the WHAT MATTERS lead,
  regardless of how dramatic the surprise number is.
- "Upcoming" means an earnings entry whose `date` is today or in the
  future.  If you can't find one for a name you want to discuss, do not
  invent one — say "no scheduled catalyst this week."
- If the `earnings calendar` shows a date that matches today's year/month
  (e.g. "May 2026" on May 19, 2026), trust it.  Do not flag it as a data
  error.  Real upcoming earnings genuinely fall in the current month.
- Lead-section eligibility: an earnings event qualifies for the WHAT MATTERS
  lead ONLY if `days_since == 0` (reported today, including after-hours
  yesterday) or its scheduled date is today.  Older prints belong in
  EARNINGS INTELLIGENCE as cycle context.

## v2.7 fresh-hook-on-stale-print rule (do not violate)
- A FRESH analyst action (upgrade, downgrade, PT change) that references a
  STALE earnings print does NOT make the print fresh. Lead with the rating
  change itself and what it implies about Street positioning — do not
  re-litigate the underlying print as today's catalyst.
- Example anti-pattern to avoid: "[Stock] missed earnings 11 days ago. BofA
  downgraded today to $X target. This signals unit economics breakdown."
  Wrong — the lead recycles a stale print as today's news. Right framing:
  "BofA cut [Stock] to $X (from $Y) on [stated reason]; the move comes 11
  days after the Q-print and reflects Street finally repricing [the
  specific risk]. Stock has [traded X% lower since the print / held in /
  retraced]." The fresh hook IS the rating change and the tape's reaction
  to it — not the print itself.
- If today's bundle has NO same-day catalyst for the portfolio (no
  >3% pre-market mover, no after-hours print, no breaking macro, no fresh
  scheduled earnings today), say so plainly in WHAT MATTERS: "Quiet open.
  No same-day name-specific catalyst in the book; the day's signal is in
  [the macro print at 8:30 / the analyst action cluster on X / the
  earnings calendar into Thursday]." A quiet morning is information.
  Manufacturing drama from stale prints is worse than naming the quiet.

## v2.7 sign-flip precision rule (do not violate)
- When an EPS print flips sign (estimate ≥ 0 and actual < 0, or vice
  versa) or `surprise_pct` magnitude exceeds 200%, the percentage is a
  mathematical artifact of a near-zero denominator and is NOT meaningful
  magnitude information. Do NOT cite it.
- Quote the print in absolute terms instead: "EPS $-0.40 vs $0.03 estimate
  (sign flip — % surprise not meaningful)." The reader is a 23-year PM —
  he knows $-0.40 vs $0.03 is a bad print without a fake-precision
  percentage attached.
"""


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
            model="claude-sonnet-4-6",
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

    payload += "\nEARNINGS SCORECARD (recent reports, 4-week lookback):\n"
    if scorecard:
        for item in scorecard[:15]:
            beat_status = "BEAT" if item.get('beat') else "MISS"
            # v2.7 stale tag — hard label for any print older than 1 day
            ds = item.get('days_since')
            stale_prefix = ""
            if isinstance(ds, (int, float)) and ds > 1:
                stale_prefix = f"[STALE: {int(ds)}d ago — CONTEXT ONLY, DO NOT LEAD] "
            # v2.7 sign-flip handling — suppress fake-precision surprise_pct
            eps_a = item.get('eps_actual')
            eps_e = item.get('eps_estimate')
            surp = item.get('surprise_pct')
            sign_flip = (
                isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float))
                and ((eps_a < 0 and eps_e >= 0) or (eps_a >= 0 and eps_e < 0))
            )
            magnitude_garbage = isinstance(surp, (int, float)) and abs(surp) > 200
            if sign_flip or magnitude_garbage:
                surp_str = "(sign flip — % surprise not meaningful)"
            else:
                surp_str = f"({surp}%)" if surp is not None else ""
            rev_str = ""
            rev_a = item.get('rev_actual')
            rev_e = item.get('rev_estimate')
            if rev_a and rev_e:
                rev_a_fmt = f"${rev_a/1e9:.1f}B" if isinstance(rev_a, (int, float)) and rev_a >= 1e9 else str(rev_a)
                rev_e_fmt = f"${rev_e/1e9:.1f}B" if isinstance(rev_e, (int, float)) and rev_e >= 1e9 else str(rev_e)
                rev_str = f" | Rev: {rev_a_fmt} vs {rev_e_fmt} ({'beat' if item.get('rev_beat') else 'miss'})"
            guidance = item.get('guidance_signal', '')
            guidance_str = f" | Guidance: {guidance}" if guidance else ""
            payload += f"- {stale_prefix}{item.get('symbol', 'N/A')}: {beat_status} | EPS: {eps_a if eps_a is not None else 'N/A'} vs {eps_e if eps_e is not None else 'N/A'} {surp_str}{rev_str}{guidance_str}\n"
    else:
        payload += "- No recent earnings in portfolio\n"

    payload += "\nEARNINGS CALENDAR (upcoming):\n"
    if earnings:
        for item in earnings[:10]:
            rev_est = item.get('revenue_estimate')
            rev_tag = f" | Est. Rev: ${rev_est/1e9:.1f}B" if rev_est and isinstance(rev_est, (int, float)) and rev_est >= 1e9 else (f" | Est. Rev: ${rev_est/1e6:.0f}M" if rev_est and isinstance(rev_est, (int, float)) and rev_est >= 1e6 else "")
            payload += f"- {item.get('symbol', 'N/A')}: {item.get('date', 'N/A')} {item.get('hour', 'N/A')} | Est. EPS: {item.get('eps_estimate', 'N/A')}{rev_tag}\n"
    else:
        payload += "- No upcoming earnings in next 5 days\n"

    if misses:
        payload += "\nEARNINGS MISS CONTEXT:\n"
        for symbol, explanation in misses.items():
            payload += f"- {symbol}: {explanation}\n"

    analyst_actions = data.get("analyst_actions", {})
    if analyst_actions:
        payload += "\nANALYST ACTIONS (last 7 days):\n"
        for symbol in sorted(analyst_actions.keys()):
            for a in analyst_actions[symbol][:2]:
                analyst = a.get("analyst", "?")
                action = a.get("action", "")
                prior = a.get("prior_rating", "")
                pt = a.get("price_target")
                prior_pt = a.get("prior_target")
                pt_str = f" PT ${prior_pt:.0f}→${pt:.0f}" if pt and prior_pt else (f" PT ${pt:.0f}" if pt else "")
                rating_str = f"{prior}→{action}" if prior else action
                payload += f"- {symbol}: {analyst} {rating_str}{pt_str}\n"

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
# 1b. AI BRIEF GENERATION — MARKET RECAP (post-close)
# ============================================================================

RECAP_SYSTEM_PROMPT = """You are the senior portfolio analyst for a concentrated, high-conviction investment firm with approximately $900 million in AUM. You write the end-of-day intelligence brief that the CEO and investment team read after the close, before anything else. Your single job is to turn the day's tape into actionable post-close intelligence — what happened, what it means for the portfolio, and what to watch into tomorrow.

PORTFOLIO CONTEXT & PHILOSOPHY:
- PLTR (Palantir) is the anchor position (~30% of portfolio), a core strategic holding
- The firm runs deeply concentrated positions (not diversified); thesis quality and moat strength matter far more than sector balance
- Investment conviction centers on: monopolistic businesses with pricing power, long-term competitive moats, founder-aligned incentive structures, and secular growth tailwinds
- The CEO's operating principle: "Never be surprised by material events." Your job is to surface the signals that matter before consensus does
- Priority holdings: PLTR, NVDA, TSLA, META, AMZN, GOOGL, AMD, SOFI, UBER, MSFT, AAPL, JPM, COST, ABNB, AFRM, HIMS, NU, ASML

POST-CLOSE WRITING DISCIPLINE:
- The morning brief sets the day's hypothesis; the recap grades it. Start with what the tape confirmed, contradicted, or left ambiguous versus the morning thesis.
- Lead with the single most important post-close signal. If an anchor position moved >3% on news, that's the lead. If a string of earnings revealed a cycle inflection, that's the lead. If the day was noise, say so.
- Be direct and opinionated. Hedge only when genuine uncertainty exists. Use "is," "signals," "suggests" — not "may," "might," "could."
- Cross-reference today's moves with the book: when a holding rallies on no name-specific news, name the sympathy driver. When a name closes red despite beating, name the line item the market punished and watch for sector follow-through.
- Name the post-close trade setup when you see one (buy-the-dip into a known catalyst, oversold bounce candidate, momentum fade) — but only when the data bundle supports it.
- For after-hours earnings reporters: if reported, grade the print (real beat vs. noise beat). If pending, frame what matters most in the release.
- Use concrete numbers FROM THE DATA BUNDLE — closing price, day move %, volume relative to average. Never use a vague qualifier ("finished up nicely") when the bundle gives you the actual number. Never invent or estimate a number that the bundle doesn't provide.
- Connect to portfolio mechanics: does today validate existing positioning, or signal thesis drift?
- Maximum 700 words across all sections.

DATA-QUALITY AWARENESS:
- If the data bundle indicates price drift flags between sources (yfinance vs Finnhub disagreement >0.10%), mention which holdings had drift and which source you are trusting. Do NOT fabricate precision you don't have.
- If a holding's close price and daily change are both flagged with drift, treat the direction of the move as reliable but caveat the magnitude.

EXAMPLES IN THIS PROMPT ARE NOT DATA (hard rule — do not violate):
- Any specific ticker, price, percentage, EPS estimate, or volume figure that appears in this system prompt is a STYLE example, not a fact about today. Do not parrot example numbers into the brief as if they were real. Only use numbers and tickers that appear in the user-message data bundle.
- For every concrete number you write (closing price, day change, EPS, revenue, volume ratio), you must be able to point to the exact bundle row it came from. If you can't, rewrite the sentence using a number you CAN ground, or drop the sentence.

EARNINGS GROUNDING (hard rule — do not violate):
- Beat/miss claims must come ONLY from the EARNINGS SCORECARD section of the data bundle, which carries an explicit BEAT or MISS tag per ticker. That tag is authoritative.
- When grading a print in prose, quote actual vs estimate from the scorecard row. Do not assert "X missed" or "Y beat" without the matching scorecard row in front of you.
- If a ticker is NOT in the scorecard, do not characterize its earnings as a beat or miss. Refer to it as "reported" or "pending" only, or omit the claim.
- Never contradict the scorecard's BEAT/MISS tag. If the row says BEAT, the ticker beat — full stop.

NARRATIVE-vs-TAPE CONSISTENCY (hard rule — do not violate):
- Whenever you assert a fundamental positive (beat, raise, "inflection") about a ticker, cross-check the same ticker's close and day % from the bundle and reflect it. A bullish print + soft (or red) tape is itself a signal — name it.
- Never lead with a positive editorial on a holding whose price action contradicts the narrative without naming and explaining the gap. Sell-the-news, valuation reset, guidance footnotes, and positioning unwinds are all legitimate explanations — pick one.
- The bullish editorial must survive the day's tape. If it doesn't, the editorial is wrong, not the tape.

VOICE & REGISTER (hard rule — do not violate):
- The reader is a 23-year portfolio manager who knows every holding's thesis cold. He is not the audience for Yahoo-style headlines, hype framing, or analyst-of-the-year theatre.
- Forbidden words and phrases — use the underlying mechanism instead. Bullish hyperbole: "surge," "soar," "rocket," "explode," "crushed," "stunning," "blowout," "monster print," "blockbuster," "vindicates the bulls," "validates the bull case," "thesis validation," "AI demand surge." Bearish hyperbole: "catastrophic," "catastrophe," "collapse," "collapsed," "collapsing," "breakdown," "disaster," "disastrous," "carnage," "bloodbath," "implosion," "implodes," "imploded," "death spiral," "annihilated," "decimated." Also forbidden: exclamation points, rhetorical questions to the reader.
- Replace adjectives with magnitude + direction + mechanism. Wrong: "X surged on a stunning print." Right: "X +Y% on a Z guide raise; segment commentary called out [headline detail]." Wrong: "Y collapsed on a catastrophic miss." Right: "Y -Z% on EPS $-0.40 vs $0.03 estimate; management did not address the unit-economics question." Numbers and the mechanism do the work, not adverbs — applies symmetrically to bull and bear framing.
- Register is a buy-side post-close note, not financial media. Direct, declarative, lower-temperature. Opinionated is fine; theatrical is not. "Direct and opinionated" means a confident call, not a loud one.

EARNINGS DEPTH (hard rule — do not violate):
- The print itself is the least interesting thing about an earnings event. The reader has already seen the BEAT/MISS tag. Your job is to decompose what was inside the print and what the guide said — not restate the headline.
- For every earnings call you discuss (after-hours reporters tonight, or recent prints you reference), surface from the bundle: (1) revenue beat/miss alongside EPS beat/miss (a revenue miss + EPS beat is a very different print from a double beat — name which one), (2) the `Guidance:` tag in the scorecard row (raised / lowered / in-line), and (3) the segment- or product-level color in filtered_news that fleshes out what management actually said.
- Do not write "X beat on EPS and revenue" and stop. Write what is inside the print: which line item carried it, what management guided to, how the tape reacted in regular hours (and AH if applicable), and what that reaction says about positioning into the print.
- For after-hours pending reporters in `after_hours_watch`: name the specific line that matters in the release (segment margin, guide direction, unit economics, take-rate, FX commentary) — pull KPI names only from filtered_news or analyst_actions in the bundle. Do not invent KPI labels.
- If the bundle has no guidance color for a name (no `Guidance:` tag, no relevant headline), say "no guidance color in the bundle" rather than inventing one. Honest absence beats fabricated detail.

OUTPUT STRUCTURE (return as valid JSON with these exact keys):
{
  "closing_pulse": "1-3 paragraph lead. THE most important post-close signal today. Answer: what happened, what it means for THIS portfolio, what changed vs. the morning brief thesis. This is the section the CEO reads in 30 seconds.",
  "macro_read": "2-3 sentences interpreting the day's macro backdrop: indices (direction + magnitude + context), bonds, VIX behavior. Use the bundle's actual numbers, but interpret them — what was the market pricing? E.g., melt-up equities + VIX bleeding + 10Y selling off = risk-on AND growth repricing, consistent with a cooling-inflation regime. Not just raw quotes.",
  "portfolio_movers": "Editorial read of today's top gainers and top losers in the book. For the top 3 gainers AND top 3 losers: explain WHY (earnings, sector rotation, news, macro spillover, idiosyncratic) using the actual close and day % from the bundle. Flag whether each move is signal or noise. Group by theme if patterns exist (e.g., a cluster of financials reacting to one bank's NIM commentary = sector rotation, not name-specific).",
  "after_hours_watch": "Synthesis of today's after-hours earnings reporters (from our holdings). If ANY reporters delivered, grade the print: real beat vs. mechanical beat, guidance direction, stock reaction in AH — using the bundle's actual vs estimate values. For pending reporters, name the single most important thing to watch when the print drops (the specific KPI or guidance line, not a fabricated EPS number).",
  "news_signal": "The 2-4 genuinely material news items that broke today. Explain why each matters for the portfolio into tomorrow — not just 'this is important news' but the specific transmission mechanism into a named holding's thesis.",
  "tomorrow_setup": "2-4 specific things to watch tomorrow: earnings pre-market, key levels/support, macro prints, Fed speakers, sector rotation to fade or press. Be specific about WHICH KPI or commentary line matters — not just 'X earnings tomorrow.' Pull EPS estimates only from the bundle's EARNINGS CALENDAR; do not invent or recall consensus from elsewhere. Include cross-asset signals (rates, FX, commodities) that will move the portfolio at tomorrow's open."
}

CRITICAL NOTES:
- This is the POST-CLOSE brief (2:00 PM PT / 5:00 PM ET). The morning brief ran at 5:00 AM. Reference the morning thesis when today's tape confirmed or broke it.
- Social media intelligence is handled in a separate brief. Do NOT force social data here.
- Your output is the CEO's last market input before dinner. Make every word count."""


def generate_ai_recap_brief(data: dict[str, Any], api_key: str) -> dict[str, str]:
    """
    Generate a post-close editorial intelligence brief using Claude.

    Expected keys in `data`:
        market_close       : dict  (sp500, nasdaq, dow, vix, treasury_10y + *_change + *_verified_source)
        portfolio_perf     : list[dict]  (symbol, price, change_pct, verified_source, drift_pct, ...)
        filtered_news      : list[dict]  (ticker, title, summary, category, link)
        ah_earnings        : list[dict]  (reported + pending AMC)
        rsi_alerts         : list[dict]
        data_quality       : dict  (counts from verify_portfolio_closes)
        holdings_count     : int

    Returns dict with keys:
        closing_pulse, macro_read, portfolio_movers,
        after_hours_watch, news_signal, tomorrow_setup
    """
    client = Anthropic(api_key=api_key)
    payload = _build_recap_ai_payload(data)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=RECAP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        response_text = message.content[0].text
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            brief_dict = json.loads(json_match.group())
            required_keys = [
                "closing_pulse",
                "macro_read",
                "portfolio_movers",
                "after_hours_watch",
                "news_signal",
                "tomorrow_setup",
            ]
            for key in required_keys:
                if key not in brief_dict:
                    brief_dict[key] = ""
            return brief_dict
        print("ERROR: Could not parse JSON from AI recap response")
        return _fallback_recap_brief(data)
    except Exception as e:
        print(f"ERROR in AI recap generation: {e}")
        return _fallback_recap_brief(data)


def _build_recap_ai_payload(data: dict[str, Any]) -> str:
    """Construct detailed text payload for Claude from structured post-close data."""
    market_close = data.get("market_close", {}) or {}
    portfolio_perf = data.get("portfolio_perf", []) or []
    filtered_news = data.get("filtered_news", []) or []
    ah_earnings = data.get("ah_earnings", []) or []
    rsi_alerts = data.get("rsi_alerts", []) or []
    data_quality = data.get("data_quality", {}) or {}

    # Market close block
    mc_lines = []
    fields = [
        ("S&P 500", "sp500", "sp500_change"),
        ("NASDAQ", "nasdaq", "nasdaq_change"),
        ("Dow Jones", "dow", "dow_change"),
        ("VIX", "vix", None),
        ("10Y Treasury Yield", "treasury_10y", None),
    ]
    for label, val_key, chg_key in fields:
        val = market_close.get(val_key)
        if val is None:
            continue
        chg = market_close.get(chg_key) if chg_key else None
        drift_note = ""
        vs = market_close.get(f"{val_key}_verified_source")
        if vs == "drift":
            d = market_close.get(f"{val_key}_drift_pct")
            drift_note = f" [DRIFT {d:.2f}pp vs Finnhub]" if d else " [DRIFT]"
        if chg is not None:
            mc_lines.append(f"- {label}: {val:,.2f} ({'+' if chg >= 0 else ''}{chg:.2f}%){drift_note}")
        else:
            mc_lines.append(f"- {label}: {val:,.2f}{drift_note}")
    mc_block = "\n".join(mc_lines) if mc_lines else "- Market close data unavailable"

    # Top gainers / losers with verification
    sorted_perf = sorted(portfolio_perf, key=lambda x: x.get("change_pct", 0) or 0, reverse=True)
    top_gainers = [p for p in sorted_perf if (p.get("change_pct") or 0) > 0][:8]
    top_losers_raw = [p for p in sorted_perf if (p.get("change_pct") or 0) < 0][-8:]
    top_losers = list(reversed(top_losers_raw))

    def _fmt_mover(p):
        s = p.get("symbol", "?")
        price = p.get("price")
        chg = p.get("change_pct")
        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "?"
        chg_str = f"{'+' if isinstance(chg,(int,float)) and chg>=0 else ''}{chg:.2f}%" if isinstance(chg,(int,float)) else "?"
        drift_tag = ""
        vs = p.get("verified_source")
        if vs == "finnhub_preferred":
            drift_tag = " [corrected — yfinance disagreed]"
        elif vs == "drift" and p.get("drift_pct"):
            drift_tag = f" [drift {p['drift_pct']:.2f}%]"
        elif vs == "yfinance_only":
            drift_tag = " [single-source]"
        return f"- {s}: {price_str} ({chg_str}){drift_tag}"

    gainers_block = "\n".join(_fmt_mover(p) for p in top_gainers) if top_gainers else "- None"
    losers_block = "\n".join(_fmt_mover(p) for p in top_losers) if top_losers else "- None"

    # Summary stats
    up = len([p for p in portfolio_perf if (p.get("change_pct") or 0) > 0])
    down = len([p for p in portfolio_perf if (p.get("change_pct") or 0) < 0])
    avg = sum((p.get("change_pct") or 0) for p in portfolio_perf) / len(portfolio_perf) if portfolio_perf else 0

    # After-hours earnings
    ah_lines = []
    reported = [e for e in ah_earnings if e.get("reported")]
    pending = [e for e in ah_earnings if not e.get("reported")]
    if reported:
        ah_lines.append("Reported after close:")
        for e in reported:
            beat_tag = "BEAT" if e.get("beat") else "MISS"
            eps_a = e.get("eps_actual")
            eps_e = e.get("eps_estimate")
            surp = e.get("surprise_pct")
            eps_str = f"${eps_a:.2f} vs ${eps_e:.2f}" if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)) else "—"
            surp_str = f" ({'+' if isinstance(surp,(int,float)) and surp>=0 else ''}{surp:.1f}%)" if isinstance(surp, (int, float)) else ""
            ah_lines.append(f"- {e.get('symbol')}: {beat_tag} | EPS {eps_str}{surp_str}")
    if pending:
        ah_lines.append("Pending (scheduled AMC, not yet reported):")
        for e in pending:
            eps_e = e.get("eps_estimate")
            est_str = f"est EPS ${eps_e:.2f}" if isinstance(eps_e, (int, float)) else "est EPS n/a"
            ah_lines.append(f"- {e.get('symbol')}: {est_str}")
    ah_block = "\n".join(ah_lines) if ah_lines else "- No after-hours reporters today"

    # RSI
    rsi_block = ""
    if rsi_alerts:
        rsi_lines = []
        for a in rsi_alerts[:8]:
            flags = []
            if a.get("is_oversold"):
                flags.append("oversold")
            if a.get("is_52w_low"):
                flags.append("52w RSI low")
            rsi_lines.append(f"- {a.get('symbol')}: RSI {a.get('current_rsi', 0):.1f} ({' · '.join(flags) if flags else 'flat'})")
        rsi_block = "\n".join(rsi_lines)

    # News
    news_lines = []
    important = [n for n in filtered_news if n.get("category") in ("URGENT", "IMPORTANT")]
    for item in important[:8]:
        news_lines.append(f"- [{item.get('ticker', '?')}] {item.get('title', '')[:140]} ({item.get('category', '')})")
        summary = item.get('summary', '')
        if summary:
            news_lines.append(f"  Summary: {summary[:200]}")
    news_block = "\n".join(news_lines) if news_lines else "- No material news today"

    # Data quality summary — numbers above ALREADY reflect Finnhub corrections when yfinance
    # disagreed materially. No hedging needed in prose.
    dq_line = ""
    if data_quality:
        dq_parts = []
        if data_quality.get("checked", 0) > 0:
            dq_parts.append(f"checked={data_quality['checked']}")
            dq_parts.append(f"consensus={data_quality.get('consensus', 0)}")
            dq_parts.append(f"drift>{DRIFT_TOLERANCE_PCT}%={data_quality.get('drift', 0)}")
            dq_parts.append(f"material(>{MATERIAL_DRIFT_PCT}%)={data_quality.get('material_drift', 0)}")
        if dq_parts:
            dq_line = (f"\nPRICE VERIFICATION (yfinance vs Finnhub cross-check): {' · '.join(dq_parts)}\n"
                       "NOTE: Prices and % changes above have ALREADY been corrected to Finnhub's "
                       "settlement close for any holding where yfinance disagreed materially. Treat the "
                       "numbers as authoritative; do not hedge magnitudes in your prose.\n")
        flagged = data_quality.get("flagged_symbols") or []
        if flagged:
            dq_line += "Corrected holdings (yfinance raw → Finnhub used):\n"
            for sym, drift, yf_p, fh_p in flagged[:8]:
                dq_line += f"- {sym}: raw yfinance ${yf_p:.2f} → using Finnhub ${fh_p:.2f} ({drift:.2f}% price gap)\n"

    # Strategy reads — long-form analysts (Stratechery, Asianometry) covered today.
    # Provided as awareness only; the email surfaces these to the reader directly.
    # Do NOT summarize their prose — the prose is the value.
    strategy_reads = data.get("strategy_reads", []) or []
    strategy_block = ""
    if strategy_reads:
        sr_lines = []
        for p in strategy_reads[:6]:
            sr_lines.append(f"- [{p.get('source')}] {p.get('title', '')}")
            ex = p.get("excerpt", "")
            if ex:
                sr_lines.append(f"  {ex[:220]}")
        strategy_block = (
            "\nSTRATEGY READS (long-form analysts published in last 48h — DO NOT summarize their prose; "
            "they're surfaced separately in the email. Use only as context: if a piece overlaps with today's "
            "tape or tomorrow's setup, you may reference it briefly by author, e.g. \"Thompson notes …\".):\n"
            + "\n".join(sr_lines) + "\n"
        )

    payload = f"""MARKET CLOSE (today, {datetime.now().strftime('%A %b %d')}):
{mc_block}

PORTFOLIO — TOP GAINERS:
{gainers_block}

PORTFOLIO — TOP LOSERS:
{losers_block}

PORTFOLIO SUMMARY:
- Holdings with positive return today: {up}
- Holdings with negative return today: {down}
- Average move: {'+' if avg >= 0 else ''}{avg:.2f}%

AFTER-HOURS EARNINGS:
{ah_block}

RSI EXTREMES (oversold/52w low):
{rsi_block if rsi_block else '- None today'}

MATERIAL NEWS (filtered for portfolio relevance):
{news_block}
{dq_line}{strategy_block}
BRIEFING CONTEXT:
- This is the post-close intelligence brief (2:00 PM PT / 5:00 PM ET)
- Morning brief fired at 5:00 AM today with that day's hypothesis — use it implicitly: did the tape confirm or break it?
- CEO priority: actionable post-close signal, not noise. Grade the day. Frame tomorrow.
"""
    return payload


def _fallback_recap_brief(data: dict[str, Any]) -> dict[str, str]:
    """Fallback structure if AI recap generation fails. Keeps HTML rendering safe."""
    market_close = data.get("market_close", {}) or {}
    portfolio_perf = data.get("portfolio_perf", []) or []
    sp_chg = market_close.get("sp500_change")
    nq_chg = market_close.get("nasdaq_change")
    up = len([p for p in portfolio_perf if (p.get("change_pct") or 0) > 0])
    down = len([p for p in portfolio_perf if (p.get("change_pct") or 0) < 0])

    return {
        "closing_pulse": f"Market closed with S&P {sp_chg if sp_chg is not None else 'n/a'}% and NASDAQ {nq_chg if nq_chg is not None else 'n/a'}%. See detailed data below — AI editorial generation was unavailable for this run.",
        "macro_read": "See index levels in the Market Close table below.",
        "portfolio_movers": f"{up} holdings advanced, {down} declined today. See Portfolio Movers tables below for the full top 10 gainers and top 10 losers.",
        "after_hours_watch": "See After-Hours Earnings section for today's AMC reporters.",
        "news_signal": "See News on Holdings section.",
        "tomorrow_setup": "Monitor pre-market movers and earnings pre-reports for tomorrow's session.",
    }


# Need DRIFT_TOLERANCE_PCT / MATERIAL_DRIFT_PCT for the AI payload — import lazily
# to avoid circular imports. These are defined in morning_briefing.py as the
# verification thresholds.
try:
    from morning_briefing import DRIFT_TOLERANCE_PCT, MATERIAL_DRIFT_PCT
except Exception:
    DRIFT_TOLERANCE_PCT = 0.10
    MATERIAL_DRIFT_PCT = 0.50


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

{_format_analyst_actions_table(data.get("analyst_actions", {}))}

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


def _format_rev(value) -> str:
    """Format revenue as human-readable: $98.2B, $4.3B, $450M, etc."""
    if value is None or not isinstance(value, (int, float)):
        return ""
    abs_val = abs(value)
    if abs_val >= 1e9:
        return f"${value / 1e9:.1f}B"
    elif abs_val >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


def _format_scorecard_table(scorecard: list[dict[str, Any]]) -> str:
    """Format recent earnings scorecard with revenue and guidance."""
    if not scorecard:
        return ""

    rows = ""
    for item in scorecard[:10]:
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

        # Revenue column
        rev_a = _format_rev(item.get("rev_actual"))
        rev_e = _format_rev(item.get("rev_estimate"))
        if rev_a and rev_e:
            rev_color = "#27ae60" if item.get("rev_beat") else "#c0392b"
            rev_str = f'<span style="color: {rev_color};">{rev_a}</span> / {rev_e}'
        else:
            rev_str = "—"

        # Guidance column
        guidance = item.get("guidance_signal", "")
        if "raised" in guidance:
            guide_color = "#27ae60"
            guide_str = "&#x25B2; Raised"
        elif "lowered" in guidance:
            guide_color = "#c0392b"
            guide_str = "&#x25BC; Lowered"
        elif "in-line" in guidance:
            guide_color = "#999"
            guide_str = "&#x25C6; In-line"
        else:
            guide_color = "#ccc"
            guide_str = "—"

        rpt_date = item.get("date", "")

        rows += f"""
<tr style="border-bottom: 1px solid #e8e3de;">
    <td style="font-weight: 700;">{symbol}</td>
    <td style="color: #999; font-size: 12px;">{rpt_date}</td>
    <td style="color: {badge_color}; font-weight: 600; text-align: center;">{beat_status}</td>
    <td style="text-align: right;">{eps_a_str}</td>
    <td style="text-align: right; color: #999;">{eps_e_str}</td>
    <td style="text-align: right; color: {surp_color}; font-weight: 600;">{surp_str}</td>
    <td style="text-align: right;">{rev_str}</td>
    <td style="text-align: center; color: {guide_color}; font-weight: 600;">{guide_str}</td>
</tr>
"""

    return f"""
<table width="100%" cellpadding="10" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;">
    <td style="font-weight: 700; color: #1a1a1a;">Ticker</td>
    <td style="font-weight: 700; color: #1a1a1a;">Date</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: center;">Result</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Actual EPS</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Est. EPS</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Surprise</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: right;">Revenue</td>
    <td style="font-weight: 700; color: #1a1a1a; text-align: center;">Guidance</td>
</tr>
{rows}
</table>
"""


def _format_full_earnings_table(scorecard: list[dict[str, Any]], earnings: list[dict[str, Any]]) -> str:
    """Format full earnings scorecard and calendar in appendix."""
    html = ""

    if scorecard:
        html += '<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Recent Earnings (4-Week Lookback)</h4>'
        html += '<table width="100%" cellpadding="8" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px;">'
        html += '<tr style="background-color: #ebe7e1;"><td style="font-weight: 700;">Ticker</td><td>Date</td><td>Result</td><td>EPS Act./Est.</td><td>Revenue</td><td>Guidance</td></tr>'

        for item in scorecard[:15]:
            symbol = item.get("symbol", "N/A")
            date = item.get("date", "N/A")
            beat = "BEAT" if item.get("beat") else "MISS"
            beat_color = "#27ae60" if item.get("beat") else "#c0392b"
            eps_a = item.get("eps_actual", "N/A")
            eps_e = item.get("eps_estimate", "N/A")
            eps_str = f"${eps_a:.2f} / ${eps_e:.2f}" if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)) else f"{eps_a} / {eps_e}"
            rev_a = _format_rev(item.get("rev_actual"))
            rev_e = _format_rev(item.get("rev_estimate"))
            rev_str = f"{rev_a} / {rev_e}" if rev_a and rev_e else "—"
            guidance = item.get("guidance_signal", "—") or "—"

            html += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="font-weight: 700;">{symbol}</td><td>{date}</td><td style="color: {beat_color}; font-weight: 600;">{beat}</td><td>{eps_str}</td><td>{rev_str}</td><td>{guidance}</td></tr>'

        html += '</table>'

    if earnings:
        html += '<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Upcoming Earnings Calendar</h4>'
        html += '<table width="100%" cellpadding="8" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px;">'
        html += '<tr style="background-color: #ebe7e1;"><td style="font-weight: 700;">Ticker</td><td>Date</td><td>Hour</td><td>Est. EPS</td><td>Est. Revenue</td></tr>'

        for item in earnings[:10]:
            symbol = item.get("symbol", "N/A")
            date = item.get("date", "N/A")
            hour = item.get("hour", "N/A")
            eps_est = item.get("eps_estimate", "N/A")
            rev_est = item.get("revenue_estimate")
            rev_str = _format_rev(rev_est) if rev_est else "—"

            html += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="font-weight: 700;">{symbol}</td><td>{date}</td><td>{hour}</td><td>{eps_est}</td><td>{rev_str}</td></tr>'

        html += '</table>'

    return html


def _format_analyst_actions_table(analyst_actions: dict) -> str:
    """Format analyst upgrades/downgrades/price target changes for HTML email."""
    if not analyst_actions:
        return ""

    rows = ""
    for symbol in sorted(analyst_actions.keys()):
        for a in analyst_actions[symbol][:3]:
            analyst = a.get("analyst", "?")
            action = a.get("action", "")
            prior = a.get("prior_rating", "")
            pt = a.get("price_target")
            prior_pt = a.get("prior_target")
            date = a.get("date", "")

            rating_str = f"{prior} &rarr; {action}" if prior else action
            if pt and prior_pt:
                direction_color = "#27ae60" if pt > prior_pt else "#c0392b"
                arrow = "&uarr;" if pt > prior_pt else "&darr;"
                pt_str = f'<span style="color: {direction_color};">${prior_pt:.0f} &rarr; ${pt:.0f} {arrow}</span>'
            elif pt:
                pt_str = f"${pt:.0f}"
            else:
                pt_str = "—"

            rows += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="font-weight: 700;">{symbol}</td><td>{analyst}</td><td>{rating_str}</td><td style="text-align: right;">{pt_str}</td><td style="color: #999;">{date}</td></tr>'

    return f"""
<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #1a1a1a; margin: 24px 0 12px 0; text-transform: uppercase;">Analyst Actions (7 Days)</h4>
<table width="100%" cellpadding="8" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px;">
<tr style="background-color: #ebe7e1;"><td style="font-weight: 700;">Ticker</td><td>Analyst</td><td>Rating</td><td style="text-align: right;">Price Target</td><td>Date</td></tr>
{rows}
</table>
"""


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
# 2b. HTML FORMATTING — MARKET RECAP (afternoon / post-close)
# ============================================================================

def format_market_recap_html(data, ai_brief=None):
    """
    Format the afternoon market recap as a styled HTML email.

    Same MoMA/Penguin Books aesthetic as format_morning_html: black header with
    red accent, Georgia serif for prose, Arial for data tables, 640px single-column
    table layout, warm paper background.

    When `ai_brief` is provided (preferred), the brief's editorial sections are
    woven into the page in parallel to format_morning_html:
      1. CLOSING PULSE      (editorial)
      2. MACRO READ         (editorial) + MARKET CLOSE table
      3. PORTFOLIO MOVERS   (editorial) + top 10 gainers/losers + summary
      4. AFTER-HOURS WATCH  (editorial) + reported/pending tables
      5. NEWS SIGNAL        (editorial) + news items
      6. TOMORROW'S SETUP   (editorial)
    Followed by an appendix with 52-Week Extremes, RSI Watch, and a Data Quality
    note when the verify_portfolio_closes cross-check flagged material drift.

    When `ai_brief` is None the function still renders cleanly with data tables
    only (backward-compatible with pre-v2 callers).

    Expected keys in `data`:
        market_close     : dict
        portfolio_perf   : list[dict]
        filtered_news    : list[dict]
        ah_earnings      : list[dict]
        rsi_alerts       : list[dict]  (optional)
        data_quality     : dict        (optional — from verify_portfolio_closes)
        holdings_count   : int
    """
    market_close = data.get("market_close", {}) or {}
    portfolio_perf = data.get("portfolio_perf", []) or []
    filtered_news = data.get("filtered_news", []) or []
    ah_earnings = data.get("ah_earnings", []) or []
    rsi_alerts = data.get("rsi_alerts", []) or []
    data_quality = data.get("data_quality", {}) or {}
    holdings_count = data.get("holdings_count", 0)
    ai = ai_brief or {}

    now = datetime.now()
    date_str = now.strftime("%A, %B %d")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    def _section_header(num, title):
        return (
            f'<h2 style="font-family: Arial, sans-serif; font-size: 14px; '
            f'font-weight: 700; color: #1a1a1a; margin: 0 0 16px 0; '
            f'padding-bottom: 8px; border-bottom: 1px solid #c0392b;">'
            f'{num}. {title}</h2>'
        )

    def _editorial_prose(text, margin_bottom=32):
        if not text:
            return ""
        return (
            f'<div style="font-family: Georgia, serif; font-size: 15px; '
            f'color: #1a1a1a; margin-bottom: {margin_bottom}px; line-height: 1.7;">'
            f'{text}</div>'
        )

    # ---- 1. CLOSING PULSE (AI editorial only) -------------------------------
    section_1 = ""
    if ai.get("closing_pulse"):
        section_1 = _section_header(1, "CLOSING PULSE") + _editorial_prose(ai["closing_pulse"])

    # ---- 2. MACRO READ + MARKET CLOSE table ---------------------------------
    def _index_row(label, value, change, verified_source=None, drift_pct=None):
        if value is None:
            return ""
        val_str = f"{value:,.2f}"
        chg_html = ""
        if change is not None:
            sign = "+" if change >= 0 else ""
            color = "#27ae60" if change >= 0 else "#c0392b"
            arrow = "&#x25B2;" if change >= 0 else "&#x25BC;"
            drift_tag = ""
            if verified_source == "drift" and drift_pct is not None:
                drift_tag = f' <span title="Drift vs Finnhub" style="font-size:10px; color:#b7950b; margin-left:4px;">&#x26A0; drift {drift_pct:.2f}pp</span>'
            chg_html = f'<span style="color: {color}; font-weight: 600;">{arrow} {sign}{change:.2f}%</span>{drift_tag}'
        return f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px;">{label}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{val_str}</td><td style="padding: 10px; text-align: right;">{chg_html}</td></tr>'

    def _plain_row(label, value, suffix=""):
        if value is None:
            return ""
        return f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px;">{label}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{value:.2f}{suffix}</td><td style="padding: 10px;"></td></tr>'

    close_rows = ""
    close_rows += _index_row("S&amp;P 500", market_close.get("sp500"), market_close.get("sp500_change"),
                             market_close.get("sp500_verified_source"), market_close.get("sp500_drift_pct"))
    close_rows += _index_row("NASDAQ", market_close.get("nasdaq"), market_close.get("nasdaq_change"),
                             market_close.get("nasdaq_verified_source"), market_close.get("nasdaq_drift_pct"))
    close_rows += _index_row("Dow Jones", market_close.get("dow"), market_close.get("dow_change"),
                             market_close.get("dow_verified_source"), market_close.get("dow_drift_pct"))
    close_rows += _plain_row("VIX", market_close.get("vix"))
    close_rows += _plain_row("10-Year Yield", market_close.get("treasury_10y"), "%")

    close_table = ""
    if close_rows:
        close_table = f'''<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700; color: #1a1a1a;">Index</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Level</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Change</td></tr>
{close_rows}</table>'''

    section_2 = ""
    if ai.get("macro_read") or close_table:
        section_2 = _section_header(2, "MACRO READ")
        if ai.get("macro_read"):
            section_2 += _editorial_prose(ai["macro_read"], margin_bottom=24)
        section_2 += close_table

    # ---- 3. PORTFOLIO MOVERS (editorial + tables) ---------------------------
    sorted_perf = sorted(portfolio_perf, key=lambda x: x.get("change_pct", 0) or 0, reverse=True)
    gainers = [p for p in sorted_perf if (p.get("change_pct") or 0) > 0][:10]
    losers_raw = [p for p in sorted_perf if (p.get("change_pct") or 0) < 0][-10:]
    losers = list(reversed(losers_raw))

    def _movers_table(rows, title, color):
        if not rows:
            return ""
        body = ""
        for p in rows:
            symbol = p.get("symbol", "")
            price = p.get("price", 0) or 0
            chg = p.get("change_pct", 0) or 0
            sign = "+" if chg >= 0 else ""
            drift_tag = ""
            vs = p.get("verified_source")
            if vs == "finnhub_preferred":
                _d = p.get("drift_pct") or 0
                drift_tag = f' <span style="color:#27ae60; font-size: 10px;" title="yfinance disagreed by {_d:.2f}% — using Finnhub settlement close">&#x2713;</span>'
            elif vs == "drift" and p.get("drift_pct"):
                _d = p.get("drift_pct") or 0
                drift_tag = f' <span style="color:#b7950b; font-size: 10px;" title="{_d:.2f}% drift vs Finnhub">&#x26A0;</span>'
            elif vs == "yfinance_only":
                drift_tag = ' <span style="color:#999; font-size: 10px;" title="Single-source (Finnhub not available for this ticker)">&middot;</span>'
            body += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px; font-weight: 700;">{symbol}{drift_tag}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">${price:,.2f}</td><td style="padding: 10px; text-align: right; color: {color}; font-weight: 600;">{sign}{chg:.2f}%</td></tr>'
        return f'''<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #1a1a1a; margin: 16px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">{title}</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 24px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700; color: #1a1a1a;">Ticker</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Price</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Change</td></tr>
{body}</table>'''

    summary_block = ""
    if portfolio_perf:
        avg_change = sum(p.get("change_pct", 0) or 0 for p in portfolio_perf) / len(portfolio_perf)
        up_count = len([p for p in portfolio_perf if (p.get("change_pct") or 0) > 0])
        down_count = len([p for p in portfolio_perf if (p.get("change_pct") or 0) < 0])
        avg_sign = "+" if avg_change >= 0 else ""
        avg_color = "#27ae60" if avg_change >= 0 else "#c0392b"
        summary_block = f'''<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 32px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px;">Average move</td><td style="padding: 10px; text-align: right; color: {avg_color}; font-weight: 600;">{avg_sign}{avg_change:.2f}%</td></tr>
<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px;">Advancers</td><td style="padding: 10px; text-align: right; font-weight: 600;">{up_count}</td></tr>
<tr><td style="padding: 10px;">Decliners</td><td style="padding: 10px; text-align: right; font-weight: 600;">{down_count}</td></tr>
</table>'''

    section_3 = ""
    if ai.get("portfolio_movers") or gainers or losers:
        section_3 = _section_header(3, "PORTFOLIO MOVERS")
        if ai.get("portfolio_movers"):
            section_3 += _editorial_prose(ai["portfolio_movers"], margin_bottom=24)
        section_3 += _movers_table(gainers, "Top 10 Gainers", "#27ae60")
        section_3 += _movers_table(losers, "Top 10 Losers", "#c0392b")
        section_3 += summary_block

    # ---- 4. AFTER-HOURS WATCH (editorial + tables) --------------------------
    ah_reported = [e for e in ah_earnings if e.get("reported")]
    ah_pending = [e for e in ah_earnings if not e.get("reported")]

    def _rev_fmt(v):
        if v is None or not isinstance(v, (int, float)):
            return ""
        av = abs(v)
        if av >= 1e9:
            return f"${v/1e9:.1f}B"
        if av >= 1e6:
            return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"

    ah_reported_block = ""
    if ah_reported:
        rows = ""
        for e in ah_reported:
            sym = e.get("symbol", "")
            beat = e.get("beat")
            status_txt = "BEAT" if beat else "MISS"
            status_color = "#27ae60" if beat else "#c0392b"
            eps_a = e.get("eps_actual")
            eps_e = e.get("eps_estimate")
            eps_str = f"${eps_a:.2f} / ${eps_e:.2f}" if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)) else "—"
            surp = e.get("surprise_pct")
            if isinstance(surp, (int, float)):
                s_sign = "+" if surp >= 0 else ""
                s_col = "#27ae60" if surp >= 0 else "#c0392b"
                surp_html = f'<span style="color: {s_col}; font-weight: 600;">{s_sign}{surp:.1f}%</span>'
            else:
                surp_html = "—"
            rev_a = _rev_fmt(e.get("rev_actual"))
            rev_e = _rev_fmt(e.get("rev_estimate"))
            rev_str = f"{rev_a} / {rev_e}" if rev_a and rev_e else "—"
            rows += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px; font-weight: 700;">{sym}</td><td style="padding: 10px; text-align: center; color: {status_color}; font-weight: 600;">{status_txt}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{eps_str}</td><td style="padding: 10px; text-align: right;">{surp_html}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{rev_str}</td></tr>'
        ah_reported_block = f'''<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #1a1a1a; margin: 16px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">Reported After Close</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 24px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700; color: #1a1a1a;">Ticker</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: center;">Result</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">EPS Act/Est</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Surprise</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Revenue Act/Est</td></tr>
{rows}</table>'''

    ah_pending_block = ""
    if ah_pending:
        rows = ""
        for e in ah_pending:
            sym = e.get("symbol", "")
            eps_e = e.get("eps_estimate")
            est_str = f"${eps_e:.2f}" if isinstance(eps_e, (int, float)) else "n/a"
            rev_e = _rev_fmt(e.get("rev_estimate")) or "—"
            rows += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px; font-weight: 700;">{sym}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{est_str}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{rev_e}</td></tr>'
        ah_pending_block = f'''<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #999; margin: 16px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">Pending (Scheduled AMC, Not Yet Reported)</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 24px; font-family: Arial, sans-serif; font-size: 13px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700; color: #1a1a1a;">Ticker</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Est. EPS</td><td style="padding: 10px; font-weight: 700; color: #1a1a1a; text-align: right;">Est. Revenue</td></tr>
{rows}</table>'''

    section_4 = ""
    if ai.get("after_hours_watch") or ah_reported_block or ah_pending_block:
        section_4 = _section_header(4, "AFTER-HOURS WATCH")
        if ai.get("after_hours_watch"):
            section_4 += _editorial_prose(ai["after_hours_watch"], margin_bottom=16)
        section_4 += ah_reported_block + ah_pending_block

    # ---- 5. NEWS SIGNAL (editorial + items) ---------------------------------
    important_news = [n for n in filtered_news if n.get("category") in ("URGENT", "IMPORTANT")]
    news_items_html = ""
    for n in important_news[:10]:
        ticker = n.get("ticker", "—")
        title = n.get("title", "")
        summary = n.get("summary", "") or ""
        link = n.get("link", "#")
        category = n.get("category", "")
        news_items_html += f'''<div style="margin-bottom: 18px; padding: 14px 16px; background-color: #f9f7f5; border-left: 3px solid #c0392b;">
<div style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: #999; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;">[{ticker}] &middot; {category}</div>
<div style="font-family: Georgia, serif; font-size: 14px; color: #1a1a1a; line-height: 1.5; margin-bottom: 6px;">{title}</div>
<div style="font-family: Georgia, serif; font-size: 13px; color: #555; line-height: 1.55; margin-bottom: 10px;">{summary}</div>
<a href="{link}" style="font-family: Arial, sans-serif; font-size: 11px; color: #c0392b; text-decoration: none; font-weight: 600;">Read the story &rarr;</a></div>'''

    section_5 = ""
    if ai.get("news_signal") or news_items_html:
        section_5 = _section_header(5, "NEWS SIGNAL")
        if ai.get("news_signal"):
            section_5 += _editorial_prose(ai["news_signal"], margin_bottom=20)
        section_5 += news_items_html

    # ---- 6. TOMORROW'S SETUP (editorial only) -------------------------------
    section_6 = ""
    if ai.get("tomorrow_setup"):
        section_6 = _section_header(6, "TOMORROW'S SETUP") + _editorial_prose(ai["tomorrow_setup"])

    # ---- 7. STRATEGY & ANALYSIS (Stratechery + Asianometry, 48h window) -----
    # Section is omitted entirely on days with no new posts.
    strategy_reads = data.get("strategy_reads", []) or []
    section_7 = ""
    if strategy_reads:
        # Group by source, preserving newest-first order within each source
        by_source = {}
        for p in strategy_reads:
            by_source.setdefault(p["source"], []).append(p)

        items_html = ""
        # Stable display order: Stratechery first, then Asianometry, then anything else
        source_order = [s for s in ("Stratechery", "Asianometry") if s in by_source]
        source_order += [s for s in by_source if s not in source_order]

        for source in source_order:
            for p in by_source[source]:
                pub_iso = p.get("published_iso", "")
                pub_label = ""
                if pub_iso:
                    try:
                        pub_dt = datetime.fromisoformat(pub_iso)
                        pub_label = pub_dt.strftime("%a %b %d")
                    except (ValueError, TypeError):
                        pub_label = pub_iso[:10]
                title = (p.get("title") or "(untitled)").replace("<", "&lt;").replace(">", "&gt;")
                excerpt = (p.get("excerpt") or "").replace("<", "&lt;").replace(">", "&gt;")
                link = p.get("link") or "#"
                source_color = "#c0392b" if source == "Stratechery" else "#1f6390"
                items_html += f'''<div style="margin-bottom: 22px; padding-left: 14px; border-left: 3px solid {source_color};">
    <div style="font-family: Arial, sans-serif; font-size: 10px; font-weight: 700; color: {source_color}; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 4px;">
        {source} &middot; {pub_label}
    </div>
    <div style="font-family: Georgia, serif; font-size: 16px; font-weight: 600; line-height: 1.35; margin-bottom: 6px;">
        <a href="{link}" style="color: #1a1a1a; text-decoration: none;">{title}</a>
    </div>
    <div style="font-family: Georgia, serif; font-size: 14px; color: #444; line-height: 1.55;">
        {excerpt}
    </div>
</div>
'''
        section_7 = _section_header(7, "STRATEGY &amp; ANALYSIS") + items_html

    # ---- APPENDIX: 52-Week extremes + RSI Watch -----------------------------
    highs_52w = [p for p in portfolio_perf if p.get("at_52w_high")]
    lows_52w = [p for p in portfolio_perf if p.get("at_52w_low")]

    def _52w_table(rows, label, marker, color):
        if not rows:
            return ""
        body = ""
        for p in rows:
            symbol = p.get("symbol", "")
            price = p.get("price", 0) or 0
            extreme = p.get("year_high") if "High" in label else p.get("year_low")
            ext_str = f"${extreme:,.2f}" if extreme else "—"
            body += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px; font-weight: 700;">{marker} {symbol}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">${price:,.2f}</td><td style="padding: 10px; text-align: right; color: #999; font-variant-numeric: tabular-nums;">{ext_str}</td></tr>'
        return f'''<h4 style="font-family: Arial, sans-serif; font-size: 11px; font-weight: 700; color: {color}; margin: 16px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">{label}</h4>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 24px; font-family: Arial, sans-serif; font-size: 12px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700;">Ticker</td><td style="padding: 10px; font-weight: 700; text-align: right;">Price</td><td style="padding: 10px; font-weight: 700; text-align: right;">52-Week Level</td></tr>
{body}</table>'''

    appendix_52w = ""
    if highs_52w or lows_52w:
        appendix_52w = '<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #666; margin: 24px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">52-WEEK EXTREMES</h3>'
        appendix_52w += _52w_table(highs_52w, "52-Week Highs", "&#x2605;", "#27ae60")
        appendix_52w += _52w_table(lows_52w, "52-Week Lows", "&#x26A0;", "#c0392b")

    appendix_rsi = ""
    if rsi_alerts:
        rsi_rows = ""
        for a in rsi_alerts[:10]:
            sym = a.get("symbol", "")
            rsi_val = a.get("current_rsi", 0) or 0
            min_rsi = a.get("min_rsi_52w", 0) or 0
            flags = []
            if a.get("is_oversold"): flags.append("oversold")
            if a.get("is_52w_low"): flags.append("52w RSI low")
            flag_str = " &middot; ".join(flags)
            rsi_rows += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 10px; font-weight: 700;">{sym}</td><td style="padding: 10px; text-align: right; font-variant-numeric: tabular-nums;">{rsi_val:.1f}</td><td style="padding: 10px; text-align: right; color: #999; font-variant-numeric: tabular-nums;">{min_rsi:.1f}</td><td style="padding: 10px; color: #c0392b; font-size: 12px;">{flag_str}</td></tr>'
        appendix_rsi = f'''<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #666; margin: 24px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">RSI WATCH</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f7f5; border: 1px solid #e8e3de; margin-bottom: 24px; font-family: Arial, sans-serif; font-size: 12px;">
<tr style="background-color: #ebe7e1;"><td style="padding: 10px; font-weight: 700;">Ticker</td><td style="padding: 10px; font-weight: 700; text-align: right;">RSI</td><td style="padding: 10px; font-weight: 700; text-align: right;">52w Min</td><td style="padding: 10px; font-weight: 700;">Flag</td></tr>
{rsi_rows}</table>'''

    # ---- Data Quality footer ------------------------------------------------
    dq_footer = ""
    checked = data_quality.get("checked", 0) if data_quality else 0
    drift_count = data_quality.get("drift", 0) if data_quality else 0
    material_count = data_quality.get("material_drift", 0) if data_quality else 0
    flagged = data_quality.get("flagged_symbols") or [] if data_quality else []

    if checked > 0:
        dq_status_color = "#27ae60" if material_count == 0 else "#b7950b" if material_count < 3 else "#c0392b"
        dq_body = (f"<strong>{checked}</strong> holdings cross-checked against Finnhub. "
                   f"<strong>{data_quality.get('consensus', 0)}</strong> consensus, "
                   f"<strong>{drift_count}</strong> drift &gt; {DRIFT_TOLERANCE_PCT if 'DRIFT_TOLERANCE_PCT' in globals() else 0.10:.2f}%, "
                   f"<strong>{material_count}</strong> material drift &gt; {MATERIAL_DRIFT_PCT if 'MATERIAL_DRIFT_PCT' in globals() else 0.50:.2f}%.")
        flagged_html = ""
        if flagged:
            rows = ""
            for sym, d, yf_p, fh_p in flagged[:8]:
                rows += f'<tr style="border-bottom: 1px solid #e8e3de;"><td style="padding: 8px; font-weight: 700;">{sym}</td><td style="padding: 8px; text-align: right; font-variant-numeric: tabular-nums;">${yf_p:.2f}</td><td style="padding: 8px; text-align: right; font-variant-numeric: tabular-nums;">${fh_p:.2f}</td><td style="padding: 8px; text-align: right; color:#b7950b; font-weight: 600;">{d:.2f}%</td></tr>'
            flagged_html = f'''<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #fefaf0; border: 1px solid #e8d9b0; margin-top: 12px; font-family: Arial, sans-serif; font-size: 12px;">
<tr style="background-color: #f7ecd0;"><td style="padding: 8px; font-weight: 700;">Ticker</td><td style="padding: 8px; font-weight: 700; text-align: right;">yfinance (raw)</td><td style="padding: 8px; font-weight: 700; text-align: right;">Finnhub (used)</td><td style="padding: 8px; font-weight: 700; text-align: right;">Drift</td></tr>
{rows}</table>
<div style="font-family: Arial, sans-serif; font-size: 11px; color: #999; margin-top: 6px;">Flagged rows were corrected to Finnhub's settlement close before the brief was written. yfinance figures shown for audit only.</div>'''
        dq_footer = f'''<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #666; margin: 32px 0 12px 0; text-transform: uppercase; letter-spacing: 1px;">Data Quality</h3>
<div style="font-family: Arial, sans-serif; font-size: 12px; color: #444; line-height: 1.55; padding: 12px 14px; background-color: #fefaf0; border-left: 3px solid {dq_status_color};">{dq_body}</div>
{flagged_html}'''

    appendix_block = ""
    if appendix_52w or appendix_rsi or dq_footer:
        appendix_block = f'<hr style="border: none; border-bottom: 2px solid #e8e3de; margin: 40px 0;">\n<h3 style="font-family: Arial, sans-serif; font-size: 12px; font-weight: 700; color: #666; margin: 0 0 16px 0; text-transform: uppercase; letter-spacing: 1px;">APPENDIX</h3>\n{appendix_52w}\n{appendix_rsi}\n{dq_footer}'

    # ---- Assemble document --------------------------------------------------
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Recap</title>
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
        Afternoon Intelligence
    </div>
    <h1 style="font-family: Georgia, serif; font-size: 32px; font-weight: 400; color: #ffffff; margin: 0 0 8px 0; line-height: 1.2;">
        Market Recap
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

{section_1}
{section_2}
{section_3}
{section_4}
{section_5}
{section_6}
{section_7}
{appendix_block}

<!-- FOOTER -->
<div style="margin-top: 40px; padding-top: 24px; border-top: 1px solid #e8e3de; font-family: Arial, sans-serif; font-size: 12px; color: #999; line-height: 1.6;">
    <div style="margin-bottom: 12px;">{holdings_count} holdings &middot; {time_str}</div>
    <div style="color: #bbb;">Market recap complete. Next update: 5:00 AM PT (Morning Brief)</div>
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


# ============================================================================
# 3. EMAIL SENDING VIA APPLE MAIL APPLESCRIPT
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


# ============================================================================
# 3b. PLAIN TEXT FORMATTING — MARKET RECAP (afternoon / post-close)
# ============================================================================

def format_recap_text(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """
    Format the post-close market recap as plain text (email fallback).
    Parallel to format_morning_text — editorial voice at the top, key data
    below.  Used as the email body when HTML rendering fails.
    """
    market_close = data.get("market_close", {}) or {}
    portfolio_perf = data.get("portfolio_perf", []) or []
    ah_earnings = data.get("ah_earnings", []) or []
    data_quality = data.get("data_quality", {}) or {}
    ai = ai_brief or {}

    now = datetime.now()
    date_str = now.strftime("%A, %B %d")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    # Header
    text = f"""
┌─────────────────────────────────────────┐
│   MARKET RECAP                          │
│   {date_str:<37} │
└─────────────────────────────────────────┘

▸ CLOSING PULSE

{ai.get('closing_pulse', 'See detailed data in email.')}

▸ MACRO READ

{ai.get('macro_read', '')}
"""

    # Index data
    idx_lines = []
    for label, val_key, chg_key in [
        ("S&P 500", "sp500", "sp500_change"),
        ("NASDAQ", "nasdaq", "nasdaq_change"),
        ("Dow Jones", "dow", "dow_change"),
        ("VIX", "vix", None),
        ("10Y Yield", "treasury_10y", None),
    ]:
        val = market_close.get(val_key)
        if val is None:
            continue
        chg = market_close.get(chg_key) if chg_key else None
        suffix = "%" if val_key in ("treasury_10y", "vix") else ""
        val_str = f"{val:,.2f}{suffix}"
        chg_str = ""
        if isinstance(chg, (int, float)):
            arrow = "▲" if chg >= 0 else "▼"
            sign = "+" if chg >= 0 else ""
            chg_str = f"  {arrow} {sign}{chg:.2f}%"
        # Drift tag
        if market_close.get(f"{val_key}_verified_source") == "drift":
            chg_str += " [drift]"
        idx_lines.append(f"  {label:<12} {val_str:>12}{chg_str}")
    if idx_lines:
        text += "\n" + "\n".join(idx_lines) + "\n"

    text += f"""
▸ PORTFOLIO MOVERS

{ai.get('portfolio_movers', '')}
"""

    # Top movers compact
    sorted_perf = sorted(portfolio_perf, key=lambda x: x.get("change_pct", 0) or 0, reverse=True)
    gainers = [p for p in sorted_perf if (p.get("change_pct") or 0) > 0][:5]
    losers = list(reversed([p for p in sorted_perf if (p.get("change_pct") or 0) < 0][-5:]))
    if gainers:
        text += "\nTOP GAINERS:\n"
        for p in gainers:
            sym = p.get("symbol", "")
            price = p.get("price", 0) or 0
            chg = p.get("change_pct", 0) or 0
            vs = p.get("verified_source")
            drift = " ✓" if vs == "finnhub_preferred" else (" ⚠" if vs == "drift" else "")
            text += f"  ▲ {sym:<6} ${price:>8,.2f}  +{chg:.2f}%{drift}\n"
    if losers:
        text += "\nTOP LOSERS:\n"
        for p in losers:
            sym = p.get("symbol", "")
            price = p.get("price", 0) or 0
            chg = p.get("change_pct", 0) or 0
            vs = p.get("verified_source")
            drift = " ✓" if vs == "finnhub_preferred" else (" ⚠" if vs == "drift" else "")
            text += f"  ▼ {sym:<6} ${price:>8,.2f}  {chg:.2f}%{drift}\n"

    # Summary
    if portfolio_perf:
        up = len([p for p in portfolio_perf if (p.get("change_pct") or 0) > 0])
        down = len([p for p in portfolio_perf if (p.get("change_pct") or 0) < 0])
        avg = sum((p.get("change_pct") or 0) for p in portfolio_perf) / len(portfolio_perf)
        arrow = "▲" if avg >= 0 else "▼"
        sign = "+" if avg >= 0 else ""
        text += f"\n  Avg: {arrow} {sign}{avg:.2f}%  |  Up: {up}  Down: {down}\n"

    # After-hours
    if ah_earnings:
        text += f"""
▸ AFTER-HOURS WATCH

{ai.get('after_hours_watch', '')}
"""
        reported = [e for e in ah_earnings if e.get("reported")]
        pending = [e for e in ah_earnings if not e.get("reported")]
        if reported:
            text += "\nREPORTED:\n"
            for e in reported:
                sym = e.get("symbol", "")
                beat = "✓ BEAT" if e.get("beat") else "✗ MISS"
                surp = e.get("surprise_pct")
                surp_str = f" {'+' if isinstance(surp, (int, float)) and surp >= 0 else ''}{surp:.1f}%" if isinstance(surp, (int, float)) else ""
                text += f"  {sym:<6} {beat}{surp_str}\n"
        if pending:
            text += "\nPENDING:\n"
            for e in pending:
                text += f"  {e.get('symbol', ''):<6} (scheduled AMC)\n"

    # News + Tomorrow
    if ai.get("news_signal"):
        text += f"""
▸ NEWS SIGNAL

{ai.get('news_signal', '')}
"""
    if ai.get("tomorrow_setup"):
        text += f"""
▸ TOMORROW'S SETUP

{ai.get('tomorrow_setup', '')}
"""

    # Data quality line (brief)
    checked = data_quality.get("checked", 0) if data_quality else 0
    material = data_quality.get("material_drift", 0) if data_quality else 0
    if checked > 0:
        if material > 0:
            text += f"\n⚠ Data quality: {material} holdings with material price drift vs Finnhub — see email for details.\n"
        else:
            text += f"\n✓ Prices verified — {checked} holdings cross-checked against Finnhub, all within {DRIFT_TOLERANCE_PCT:.2f}% tolerance.\n"

    # Footer
    holdings_count = data.get("holdings_count", 0)
    text += f"""
───────────────────────────────────────────
{holdings_count} holdings · {time_str}
Full brief + data → email
"""
    return text


# ============================================================================
# 6. PRE-MARKET UPDATE (6:20 AM) — AI EDITORIAL PIPELINE
# ============================================================================

PREMARKET_SYSTEM_PROMPT = """You are the senior portfolio analyst for a concentrated, high-conviction investment firm with ~$900M AUM. The market opens in 40 minutes. This is the final pre-open intelligence brief — the CEO is already awake, already read the 5:00 AM morning brief, and now needs a DELTA update: what changed since then, and what's the game plan for the open.

PORTFOLIO CONTEXT:
- PLTR is the anchor (~30%). Concentrated, high-conviction portfolio.
- Priority holdings: PLTR, NVDA, TSLA, META, AMZN, GOOGL, AMD, SOFI, UBER, MSFT, AAPL, JPM, COST, ABNB, AFRM, HIMS, NU, ASML
- CEO's principle: "Never be surprised by material events."

WRITING DISCIPLINE:
- This is a DELTA update, not a rehash. The morning brief already covered macro context and earnings history. Focus on what moved in the last 80 minutes and what's new.
- Be extremely concise. Max 400 words total. The CEO is reading this on his phone walking to the desk.
- Lead with the single most actionable signal for the open.
- Name specific levels, prices, percentages. No vague commentary.
- If nothing material changed since the 5 AM brief, say so in one sentence and focus on the open setup.

EXAMPLES IN THIS PROMPT ARE NOT DATA (hard rule): Any ticker, price, percentage, or EPS figure in the system prompt is illustrative — never parrot it as fact. Every concrete number you write must come from the user-message data bundle.

EARNINGS GROUNDING (hard rule): Beat/miss calls come ONLY from the JUST PRINTED or EARNINGS SCORECARD rows in the data bundle (each carries an explicit BEAT/MISS tag). Quote actual vs estimate when you grade. If a ticker isn't in those rows, do not call it a beat or miss — say "reported" or "pending." Never contradict the BEAT/MISS tag.

NARRATIVE-vs-TAPE CONSISTENCY (hard rule): If a ticker beat or raised but is trading down pre-market, the editorial must name and explain the gap (sell-the-news, guidance footnote, positioning unwind) — not lead with a bullish call while the tape is red. The bullish lead must survive the pre-market quote.

VOICE & REGISTER (hard rule): Sober buy-side voice. The reader is a 23-year PM who knows the names. Forbidden bullish hyperbole: "surge," "soar," "rocket," "crushed," "blowout," "stunning," "thesis validation," "AI demand surge," "vindicates the bulls." Forbidden bearish hyperbole: "catastrophic," "catastrophe," "collapse," "collapsed," "breakdown," "disaster," "carnage," "bloodbath," "implosion," "death spiral," "annihilated," "decimated." Also forbidden: exclamation points, rhetorical questions. Replace adjectives with magnitude + mechanism — numbers and the mechanism do the work, not adverbs, symmetrically on both sides. Register is a buy-side note, not financial media.

EARNINGS DEPTH (hard rule): When grading a JUST PRINTED report, do not just write "X beat." Decompose: EPS vs revenue separately (rev miss + EPS beat is a different print from a double beat — say which one), the bundle's guidance tag (raised / lowered / in-line) when present, and the segment color in any related headline. The pre-market reaction tells you what the Street thought of the guide. If the bundle has no guidance color for a name, say so — do not invent one. For pending BMO reporters in `bell_plan`, name the specific line item that matters in the release; never use a generic "watch the print."

OUTPUT STRUCTURE (return as valid JSON with these exact keys):
{
  "open_signal": "1-2 paragraphs. The single most important thing for the open. If any BMO earnings prints dropped between the 5 AM brief and now (see JUST PRINTED section), grade them first — actual vs. estimate on BOTH EPS and revenue, the bundle's guidance tag if present, and what the pre-market reaction says about the Street's read. That is the most important delta. Otherwise, what moved in futures/pre-market and what it means for positioning.",
  "movers_update": "Quick-hit read on the top pre-market movers. 2-3 sentences connecting the moves to portfolio themes. Skip anything already covered in the morning brief unless the magnitude changed materially.",
  "bell_plan": "2-3 specific things to do or watch at the open. Levels, catalysts, and tactical setups — name the actual breakout/support level if it's in the bundle, never invent one. Include any BMO earnings still pending and what specifically matters in the release."
}"""


def generate_ai_premarket_brief(data: dict[str, Any], api_key: str) -> dict[str, str]:
    """Generate a concise pre-market delta brief using Claude."""
    client = Anthropic(api_key=api_key)

    # Build a lighter payload than the morning brief
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])
    earnings = data.get("earnings", [])
    scorecard = data.get("scorecard", [])
    just_reported = data.get("just_reported", [])

    payload = "PRE-MARKET DATA (6:20 AM PT — bell in 40 min):\n\n"

    payload += "MARKET SNAPSHOT:\n"
    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")
    if sp:
        payload += f"- S&P Futures: {sp:,.0f} ({'+' if sp_chg and sp_chg >= 0 else ''}{sp_chg:.2f}%)\n"
    if nq:
        payload += f"- NASDAQ Futures: {nq:,.0f} ({'+' if nq_chg and nq_chg >= 0 else ''}{nq_chg:.2f}%)\n"
    if treas:
        payload += f"- 10Y Treasury: {treas:.3f}%\n"

    if just_reported:
        payload += "\n*** JUST PRINTED (BMO actuals, out since the 5 AM brief) — grade these first: ***\n"
        for r in just_reported:
            sym = r.get("symbol", "?")
            eps_a = r.get("eps_actual")
            eps_e = r.get("eps_estimate")
            surp = r.get("surprise_pct")
            rev_a = r.get("rev_actual")
            rev_e = r.get("rev_estimate")
            rev_surp = r.get("rev_surprise_pct")
            beat = "BEAT" if r.get("beat") else "MISS"
            line = f"- {sym}: {beat}"
            if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)):
                line += f" EPS ${eps_a:.2f} vs ${eps_e:.2f} est"
                if isinstance(surp, (int, float)):
                    line += f" ({surp:+.1f}%)"
            if isinstance(rev_a, (int, float)) and isinstance(rev_e, (int, float)) and rev_e > 0:
                rev_tag = "BEAT" if r.get("rev_beat") else "MISS"
                line += f" | Rev ${rev_a/1e9:.2f}B vs ${rev_e/1e9:.2f}B ({rev_tag}"
                if isinstance(rev_surp, (int, float)):
                    line += f", {rev_surp:+.1f}%"
                line += ")"
            payload += line + "\n"

    payload += "\nPRE-MARKET MOVERS (portfolio holdings):\n"
    if movers:
        for m in movers[:15]:
            payload += f"- {m['symbol']}: ${m.get('price', 0):.2f} ({'+' if m.get('change_pct', 0) >= 0 else ''}{m.get('change_pct', 0):.1f}%)\n"
    else:
        payload += "- No holdings moving >2% pre-market\n"

    today_str = datetime.now().strftime("%Y-%m-%d")
    todays = [e for e in earnings if e.get("date") == today_str]
    if todays:
        payload += "\nSTILL TO REPORT TODAY:\n"
        for e in todays:
            timing = "pre (pending)" if e.get("hour") == "bmo" else "post" if e.get("hour") == "amc" else "?"
            eps = e.get("eps_estimate")
            rev = e.get("revenue_estimate")
            eps_str = f" EPS ${eps:.2f}" if eps else ""
            rev_str = f" Rev ${rev/1e9:.1f}B" if rev and isinstance(rev, (int, float)) and rev >= 1e9 else ""
            payload += f"- {e['symbol']} ({timing}){eps_str}{rev_str}\n"

    if scorecard:
        payload += "\nRECENT SCORECARD (for context):\n"
        for s in scorecard[:5]:
            beat = "BEAT" if s.get("beat") else "MISS"
            payload += f"- {s['symbol']}: {beat} EPS {s.get('surprise_pct', 0):+.1f}%\n"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=PREMARKET_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        response_text = message.content[0].text
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            brief = json.loads(json_match.group())
            for key in ["open_signal", "movers_update", "bell_plan"]:
                if key not in brief:
                    brief[key] = ""
            return brief
        print("ERROR: Could not parse JSON from premarket AI response")
        return _fallback_premarket_brief(data)
    except Exception as e:
        print(f"ERROR in premarket AI generation: {e}")
        return _fallback_premarket_brief(data)


def _fallback_premarket_brief(data: dict) -> dict:
    """Fallback if AI generation fails."""
    movers = data.get("premarket_movers", [])
    top = movers[0] if movers else {}
    return {
        "open_signal": f"Top mover: {top.get('symbol', 'N/A')} {top.get('change_pct', 0):+.1f}% pre-market." if top else "No significant pre-market moves.",
        "movers_update": "See movers table below.",
        "bell_plan": "Monitor market open. Full data in email.",
    }


def format_premarket_html(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """Format the 6:20 AM pre-market update as HTML email."""
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])
    earnings = data.get("earnings", [])
    scorecard = data.get("scorecard", [])
    just_reported = data.get("just_reported", [])

    now = datetime.now()
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    # Market snapshot line
    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")

    # Futures table
    futures_rows = ""
    if sp is not None:
        arrow = "&#x25B2;" if sp_chg and sp_chg >= 0 else "&#x25BC;"
        color = "#27ae60" if sp_chg and sp_chg >= 0 else "#c0392b"
        futures_rows += f'<tr><td style="font-weight:700;">S&P Futures</td><td style="text-align:right;">{sp:,.0f}</td><td style="text-align:right;color:{color};font-weight:600;">{arrow} {sp_chg:+.2f}%</td></tr>'
    if nq is not None:
        arrow = "&#x25B2;" if nq_chg and nq_chg >= 0 else "&#x25BC;"
        color = "#27ae60" if nq_chg and nq_chg >= 0 else "#c0392b"
        futures_rows += f'<tr><td style="font-weight:700;">NASDAQ Futures</td><td style="text-align:right;">{nq:,.0f}</td><td style="text-align:right;color:{color};font-weight:600;">{arrow} {nq_chg:+.2f}%</td></tr>'
    if treas is not None:
        futures_rows += f'<tr><td style="font-weight:700;">10Y Treasury</td><td style="text-align:right;">{treas:.2f}%</td><td></td></tr>'

    # Movers table
    movers_rows = ""
    for m in movers[:10]:
        chg = m.get("change_pct", 0)
        color = "#27ae60" if chg >= 0 else "#c0392b"
        arrow = "&#x25B2;" if chg >= 0 else "&#x25BC;"
        movers_rows += f'<tr style="border-bottom:1px solid #e8e3de;"><td style="font-weight:700;">{m["symbol"]}</td><td style="text-align:right;">${m.get("price", 0):.2f}</td><td style="text-align:right;color:{color};font-weight:600;">{arrow} {chg:+.1f}%</td></tr>'

    # Today's earnings table
    today_str = now.strftime("%Y-%m-%d")
    todays = [e for e in earnings if e.get("date") == today_str]
    earnings_rows = ""
    if todays:
        for e in sorted(todays, key=lambda x: 0 if x.get("hour") == "bmo" else 1):
            timing = "Pre" if e.get("hour") == "bmo" else "Post" if e.get("hour") == "amc" else "TBD"
            eps = e.get("eps_estimate")
            eps_str = f"${eps:.2f}" if eps else "—"
            rev = e.get("revenue_estimate")
            rev_str = f"${rev/1e9:.1f}B" if rev and isinstance(rev, (int, float)) and rev >= 1e9 else "—"
            earnings_rows += f'<tr style="border-bottom:1px solid #e8e3de;"><td style="font-weight:700;">{e["symbol"]}</td><td>{timing}</td><td style="text-align:right;">{eps_str}</td><td style="text-align:right;">{rev_str}</td></tr>'

    earnings_table = ""
    if earnings_rows:
        earnings_table = f"""
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:32px 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Still to Report Today
</h2>
<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:24px;font-family:Arial,sans-serif;font-size:13px;">
<tr style="background-color:#ebe7e1;"><td style="font-weight:700;">Ticker</td><td>Timing</td><td style="text-align:right;">Est. EPS</td><td style="text-align:right;">Est. Rev</td></tr>
{earnings_rows}
</table>
"""

    # Just-printed BMO actuals (dropped between 5 AM brief and this 6:20 AM update)
    just_reported_table = ""
    if just_reported:
        jr_rows = ""
        for r in just_reported:
            sym = r.get("symbol", "?")
            beat = r.get("beat")
            beat_tag = "BEAT" if beat else "MISS"
            beat_color = "#27ae60" if beat else "#c0392b"
            eps_a = r.get("eps_actual")
            eps_e = r.get("eps_estimate")
            surp = r.get("surprise_pct")
            eps_cell = "—"
            if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)):
                eps_cell = f"${eps_a:.2f} vs ${eps_e:.2f}"
                if isinstance(surp, (int, float)):
                    eps_cell += f" ({surp:+.1f}%)"
            rev_a = r.get("rev_actual")
            rev_e = r.get("rev_estimate")
            rev_surp = r.get("rev_surprise_pct")
            rev_cell = "—"
            if isinstance(rev_a, (int, float)) and isinstance(rev_e, (int, float)) and rev_e > 0:
                rev_cell = f"${rev_a/1e9:.2f}B vs ${rev_e/1e9:.2f}B"
                if isinstance(rev_surp, (int, float)):
                    rev_cell += f" ({rev_surp:+.1f}%)"
            jr_rows += (
                f'<tr style="border-bottom:1px solid #e8e3de;">'
                f'<td style="font-weight:700;">{sym}</td>'
                f'<td style="color:{beat_color};font-weight:700;">{beat_tag}</td>'
                f'<td style="text-align:right;">{eps_cell}</td>'
                f'<td style="text-align:right;">{rev_cell}</td>'
                f'</tr>'
            )
        just_reported_table = f"""
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:32px 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Just Printed (BMO)
</h2>
<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:24px;font-family:Arial,sans-serif;font-size:13px;">
<tr style="background-color:#ebe7e1;"><td style="font-weight:700;">Ticker</td><td>EPS</td><td style="text-align:right;">EPS Actual vs Est.</td><td style="text-align:right;">Revenue Actual vs Est.</td></tr>
{jr_rows}
</table>
"""

    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;background-color:#f5f0eb;">
<tr><td style="padding:40px 32px;">

<!-- HEADER -->
<div style="background-color:#1a1a1a;padding:24px 32px;margin-bottom:4px;">
    <h1 style="font-family:Georgia,serif;font-size:22px;font-weight:400;color:#ffffff;margin:0;letter-spacing:2px;">PRE-MARKET UPDATE</h1>
    <div style="font-family:Arial,sans-serif;font-size:12px;color:#999;margin-top:6px;">{date_str} · {time_str} · Bell in 40 min</div>
</div>
<div style="height:3px;background-color:#c0392b;margin-bottom:32px;"></div>

<!-- OPEN SIGNAL -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Open Signal
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:32px;line-height:1.7;">
{ai_brief.get('open_signal', 'No significant changes since morning brief.')}
</div>

<!-- FUTURES -->
<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:24px;font-family:Arial,sans-serif;font-size:13px;">
{futures_rows}
</table>

<!-- MOVERS UPDATE -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Pre-Market Movers
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:16px;line-height:1.7;">
{ai_brief.get('movers_update', 'No significant movers.')}
</div>

<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:32px;font-family:Arial,sans-serif;font-size:13px;">
<tr style="background-color:#ebe7e1;"><td style="font-weight:700;">Ticker</td><td style="text-align:right;">Price</td><td style="text-align:right;">Change</td></tr>
{movers_rows}
</table>

{just_reported_table}

{earnings_table}

<!-- BELL PLAN -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Bell Plan
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:32px;line-height:1.7;">
{ai_brief.get('bell_plan', 'Monitor market open.')}
</div>

<!-- FOOTER -->
<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e8e3de;font-family:Arial,sans-serif;font-size:12px;color:#999;">
    {data.get('holdings_count', 84)} holdings · {time_str} · Bell in ~40 min
</div>

</td></tr></table>
"""
    return html


def format_premarket_text(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """Concise plain-text version of the pre-market brief — used as the email body when
    HTML rendering is unavailable, and as the console summary for ops visibility."""
    snapshot = data.get("market_snapshot", {})
    movers = data.get("premarket_movers", [])

    now = datetime.now()
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")
    sp_str = f"S&P {sp:,.0f} ({sp_chg:+.1f}%)" if sp and sp_chg is not None else ""
    nq_str = f"NQ {nq:,.0f} ({nq_chg:+.1f}%)" if nq and nq_chg is not None else ""
    tr_str = f"10Y {treas:.2f}%" if treas else ""
    mkt_line = " · ".join(x for x in [sp_str, nq_str, tr_str] if x)

    mover_lines = ""
    for m in movers[:3]:
        sym = m.get("symbol", "?")
        chg = m.get("change_pct", 0)
        mover_lines += f"  {sym:<6} {chg:+.1f}%\n"

    text = f"""PRE-MARKET · Bell in 40 min

{mkt_line}

▸ OPEN SIGNAL

{ai_brief.get('open_signal', 'No significant changes since morning brief.')}

TOP MOVERS:
{mover_lines}
───────────────────────────────
{time_str} · Full brief → email
"""
    return text


# ============================================================================
# SUNDAY-NIGHT WEEKEND PREVIEW (mode: weekend_preview)
# ============================================================================

WEEKEND_SYSTEM_PROMPT = """You are the senior portfolio analyst for a concentrated, high-conviction investment firm with ~$900M AUM. It is Sunday evening. The market reopens tomorrow morning. The CEO wants ONE brief that synthesizes the weekend — what happened, what Sunday futures are signaling, and the setup heading into Monday.

PORTFOLIO CONTEXT:
- PLTR is the anchor (~30%). Concentrated, high-conviction.
- Priority holdings: PLTR, NVDA, TSLA, META, AMZN, GOOGL, AMD, SOFI, UBER, MSFT, AAPL, JPM, COST, ABNB, AFRM, HIMS, NU, ASML
- CEO's principle: "Never be surprised by material events."

WRITING DISCIPLINE:
- This is NOT a pre-market brief. The market is closed. Do not pretend it opens in 40 minutes. The next session is Monday morning.
- Lead with what genuinely moved over the weekend — geopolitics, regulatory action, M&A, preannouncements, macro data. If nothing material happened, say so plainly in one sentence and pivot to the Monday setup.
- Sunday futures (open ~3 PM PT) are a sentiment gauge, not gospel. Use them as a directional signal, not a price prediction.
- Be concise. Max 500 words across all sections. The CEO is reading this Sunday evening.
- Connect weekend news to specific holdings when there is a real link. Don't manufacture connections.

EXAMPLES IN THIS PROMPT ARE NOT DATA (hard rule): Any ticker, price, or figure in the system prompt is illustrative — never parrot it as fact. Every concrete number you write must come from the user-message data bundle.

EARNINGS GROUNDING (hard rule): If you reference last week's prints, beat/miss calls must come ONLY from the EARNINGS SCORECARD rows in the data bundle (each carries an explicit BEAT/MISS tag). Quote actual vs estimate. If a ticker isn't in the scorecard, do not call it a beat or miss. Never contradict the BEAT/MISS tag.

NARRATIVE-vs-TAPE CONSISTENCY (hard rule): If a holding's print was bullish but its Friday close was red (or vice versa), name the gap — don't write a positive editorial against a tape that contradicts it.

VOICE & REGISTER (hard rule): Sober buy-side voice. The reader is a 23-year PM who knows the names. Forbidden bullish hyperbole: "surge," "soar," "rocket," "crushed," "blowout," "stunning," "thesis validation," "AI demand surge," "vindicates the bulls." Forbidden bearish hyperbole: "catastrophic," "catastrophe," "collapse," "collapsed," "breakdown," "disaster," "carnage," "bloodbath," "implosion," "death spiral," "annihilated," "decimated." Also forbidden: exclamation points, rhetorical questions. Replace adjectives with magnitude + mechanism — numbers and the mechanism do the work, not adverbs, symmetrically on both sides. Register is a Sunday-evening buy-side note, not a financial-media weekend wrap.

EARNINGS DEPTH (hard rule): If you reference last week's prints, do not just write "X beat." Decompose: EPS vs revenue separately (rev miss + EPS beat ≠ double beat — say which one), the scorecard's `Guidance:` tag (raised / lowered / in-line) when present, and any segment- or product-level color from the weekend headlines. The Friday tape after the print tells you what the Street thought of the guide. If the bundle has no guidance color for a name, say so — do not invent one. For Monday-morning pending reporters, name the specific KPI that matters; never use generic "watch the print" framing.

OUTPUT STRUCTURE (return as valid JSON with these exact keys):
{
  "weekend_takeaway": "1-2 paragraphs. The single most important thing from the weekend that affects positioning Monday. If genuinely quiet, say so and explain what that means (e.g., 'no catalysts, market will trade off Friday's setup and Monday's economic releases').",
  "monday_setup": "2-3 sentences on how Sunday futures are positioning Monday's open and which holdings are most exposed to weekend news flow. Reference specific tickers when warranted.",
  "watch_list": "2-3 specific things to monitor heading into Monday. Could be a holding with weekend news, a Monday-morning catalyst (earnings, econ data), or a macro datapoint due early in the week. Be concrete."
}"""


def generate_ai_weekend_brief(data: dict[str, Any], api_key: str) -> dict[str, str]:
    """Generate the Sunday-night weekend preview using Claude."""
    client = Anthropic(api_key=api_key)

    snapshot = data.get("market_snapshot", {})
    news = data.get("filtered_news", [])
    strategy_reads = data.get("strategy_reads", [])

    payload = "WEEKEND PREVIEW DATA (Sunday evening, market reopens tomorrow):\n\n"

    payload += "SUNDAY FUTURES (open ~3 PM PT Sunday):\n"
    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")
    if sp:
        payload += f"- S&P Futures: {sp:,.0f} ({'+' if sp_chg and sp_chg >= 0 else ''}{sp_chg:.2f}%)\n"
    if nq:
        payload += f"- NASDAQ Futures: {nq:,.0f} ({'+' if nq_chg and nq_chg >= 0 else ''}{nq_chg:.2f}%)\n"
    if treas:
        payload += f"- 10Y Treasury: {treas:.3f}%\n"

    if news:
        payload += "\nWEEKEND HEADLINES (portfolio holdings, AI-filtered):\n"
        for n in news[:15]:
            sym = n.get("ticker") or n.get("symbol") or ""
            sym_str = f"[{sym}] " if sym else ""
            payload += f"- {sym_str}{n.get('title', '')}\n"

    if strategy_reads:
        payload += "\nSTRATEGY READS (raw context — do not summarize, the email shows these in full):\n"
        for p in strategy_reads[:6]:
            payload += f"- ({p.get('source', '?')}) {p.get('title', '')}\n"

    if not news and not strategy_reads:
        payload += "\n(No new portfolio-relevant headlines or strategy reads in the weekend window.)\n"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=WEEKEND_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        response_text = message.content[0].text
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            brief = json.loads(json_match.group())
            for key in ["weekend_takeaway", "monday_setup", "watch_list"]:
                if key not in brief:
                    brief[key] = ""
            return brief
        print("ERROR: Could not parse JSON from weekend AI response")
        return _fallback_weekend_brief(data)
    except Exception as e:
        print(f"ERROR in weekend AI generation: {e}")
        return _fallback_weekend_brief(data)


def _fallback_weekend_brief(data: dict) -> dict:
    snapshot = data.get("market_snapshot", {})
    sp_chg = snapshot.get("sp500_change")
    direction = "higher" if (sp_chg or 0) >= 0 else "lower"
    return {
        "weekend_takeaway": f"Sunday futures are pointing {direction}. See email for weekend headlines and strategy reads.",
        "monday_setup": "Monitor pre-market action for portfolio-specific moves before the open.",
        "watch_list": "Watch the open for follow-through on Sunday futures direction.",
    }


def format_weekend_html(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """Format the Sunday-night weekend preview as HTML email."""
    snapshot = data.get("market_snapshot", {})
    news = data.get("filtered_news", [])
    strategy_reads = data.get("strategy_reads", [])

    now = datetime.now()
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")

    futures_rows = ""
    if sp is not None:
        arrow = "&#x25B2;" if sp_chg and sp_chg >= 0 else "&#x25BC;"
        color = "#27ae60" if sp_chg and sp_chg >= 0 else "#c0392b"
        futures_rows += f'<tr><td style="font-weight:700;">S&P Futures</td><td style="text-align:right;">{sp:,.0f}</td><td style="text-align:right;color:{color};font-weight:600;">{arrow} {sp_chg:+.2f}%</td></tr>'
    if nq is not None:
        arrow = "&#x25B2;" if nq_chg and nq_chg >= 0 else "&#x25BC;"
        color = "#27ae60" if nq_chg and nq_chg >= 0 else "#c0392b"
        futures_rows += f'<tr><td style="font-weight:700;">NASDAQ Futures</td><td style="text-align:right;">{nq:,.0f}</td><td style="text-align:right;color:{color};font-weight:600;">{arrow} {nq_chg:+.2f}%</td></tr>'
    if treas is not None:
        futures_rows += f'<tr><td style="font-weight:700;">10Y Treasury</td><td style="text-align:right;">{treas:.2f}%</td><td></td></tr>'

    news_rows = ""
    for n in news[:12]:
        sym = n.get("ticker") or n.get("symbol") or ""
        sym_cell = f'<td style="font-weight:700;width:70px;">{sym}</td>' if sym else '<td style="width:70px;"></td>'
        title = n.get("title", "").replace("<", "&lt;").replace(">", "&gt;")
        link = n.get("link", "") or n.get("url", "")
        title_cell = f'<a href="{link}" style="color:#1a1a1a;text-decoration:none;">{title}</a>' if link else title
        news_rows += f'<tr style="border-bottom:1px solid #e8e3de;">{sym_cell}<td>{title_cell}</td></tr>'

    news_table = ""
    if news_rows:
        news_table = f"""
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:32px 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Weekend Headlines
</h2>
<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:24px;font-family:Arial,sans-serif;font-size:13px;">
{news_rows}
</table>
"""

    strategy_html = ""
    if strategy_reads:
        items = ""
        for p in strategy_reads[:6]:
            source = p.get("source", "?")
            badge_color = "#c0392b" if source == "Stratechery" else "#1a4480"
            title = p.get("title", "").replace("<", "&lt;").replace(">", "&gt;")
            link = p.get("link", "")
            excerpt = p.get("excerpt", "")
            published = p.get("published_iso", "")[:10]
            items += f"""
<div style="margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid #e8e3de;">
    <div style="margin-bottom:6px;">
        <span style="background-color:{badge_color};color:#fff;padding:2px 8px;font-size:11px;font-weight:700;letter-spacing:1px;">{source.upper()}</span>
        <span style="color:#999;font-size:12px;margin-left:8px;">{published}</span>
    </div>
    <a href="{link}" style="color:#1a1a1a;text-decoration:none;font-family:Georgia,serif;font-size:15px;font-weight:700;">{title}</a>
    <div style="font-family:Georgia,serif;font-size:13px;color:#555;margin-top:6px;line-height:1.6;">{excerpt}</div>
</div>"""
        strategy_html = f"""
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:32px 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Strategy &amp; Analysis
</h2>
{items}
"""

    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;background-color:#f5f0eb;">
<tr><td style="padding:40px 32px;">

<!-- HEADER -->
<div style="background-color:#1a1a1a;padding:24px 32px;margin-bottom:4px;">
    <h1 style="font-family:Georgia,serif;font-size:22px;font-weight:400;color:#ffffff;margin:0;letter-spacing:2px;">WEEKEND PREVIEW</h1>
    <div style="font-family:Arial,sans-serif;font-size:12px;color:#999;margin-top:6px;">{date_str} · {time_str} · Setup heading into Monday</div>
</div>
<div style="height:3px;background-color:#c0392b;margin-bottom:32px;"></div>

<!-- WEEKEND TAKEAWAY -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Weekend Takeaway
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:32px;line-height:1.7;">
{ai_brief.get('weekend_takeaway', 'Quiet weekend.')}
</div>

<!-- SUNDAY FUTURES -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Sunday Futures
</h2>
<table width="100%" cellpadding="8" cellspacing="0" style="background-color:#f9f7f5;border:1px solid #e8e3de;margin-bottom:24px;font-family:Arial,sans-serif;font-size:13px;">
{futures_rows or '<tr><td>Futures data unavailable.</td></tr>'}
</table>

<!-- MONDAY SETUP -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Monday Setup
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:32px;line-height:1.7;">
{ai_brief.get('monday_setup', 'Watch the open.')}
</div>

{news_table}

{strategy_html}

<!-- WATCH LIST -->
<h2 style="font-family:Arial,sans-serif;font-size:14px;font-weight:700;color:#1a1a1a;margin:0 0 12px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #c0392b;padding-bottom:8px;">
Watch List
</h2>
<div style="font-family:Georgia,serif;font-size:15px;color:#1a1a1a;margin-bottom:32px;line-height:1.7;">
{ai_brief.get('watch_list', 'Watch the open.')}
</div>

<!-- FOOTER -->
<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e8e3de;font-family:Arial,sans-serif;font-size:12px;color:#999;">
    {data.get('holdings_count', 84)} holdings · Sunday {time_str} · Setup for Monday
</div>

</td></tr></table>
"""
    return html


def format_weekend_text(ai_brief: dict[str, str], data: dict[str, Any]) -> str:
    """Concise plain-text version of the Sunday-night weekend preview — used as the email
    body when HTML rendering is unavailable, and as the console summary for ops visibility."""
    snapshot = data.get("market_snapshot", {})

    now = datetime.now()
    time_str = now.strftime("%I:%M %p PT").lstrip("0")

    sp = snapshot.get("sp500_futures")
    sp_chg = snapshot.get("sp500_change")
    nq = snapshot.get("nasdaq_futures")
    nq_chg = snapshot.get("nasdaq_change")
    treas = snapshot.get("treasury_10y")
    sp_str = f"S&P {sp:,.0f} ({sp_chg:+.1f}%)" if sp and sp_chg is not None else ""
    nq_str = f"NQ {nq:,.0f} ({nq_chg:+.1f}%)" if nq and nq_chg is not None else ""
    tr_str = f"10Y {treas:.2f}%" if treas else ""
    mkt_line = " · ".join(x for x in [sp_str, nq_str, tr_str] if x)

    text = f"""WEEKEND PREVIEW · Setup for Monday

{mkt_line}

▸ TAKEAWAY

{ai_brief.get('weekend_takeaway', 'Quiet weekend.')}

▸ MONDAY

{ai_brief.get('monday_setup', 'Watch the open.')}

───────────────────────────────
Sun {time_str} · Full brief → email
"""
    return text


# ============================================================================
# END OF FILE
# ============================================================================
