"""SEC EDGAR — built-in tool `sec_edgar_filings` (data.sec.gov; free, no key).

Input is a ticker (AAPL) or a CIK; the result is the company's latest filings with links to each
primary document. The SEC refuses requests without a descriptive User-Agent naming a contact
(e.g. "Acme Research ops@acme.com"), so ``user_agent`` is required.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[SEC EDGAR]"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

TOOL = ToolSpec(
    id="sec_edgar_filings",
    name="SEC EDGAR Filings",
    icon="🏛️",
    category="Research & Knowledge",
    description="Lists a US public company's latest SEC filings (10-K, 10-Q, 8-K, …) with links, from a ticker or CIK. Free; needs a contact User-Agent.",
    default_config={"user_agent": "", "form_type": "", "max_results": 10},
    order=150,
    required=("user_agent",),
    parameters=params(
        {"company": {"type": "string", "description": "Ticker symbol (e.g. AAPL) or SEC CIK number"}},
        {"form_type": {"type": "string", "description": "Only this form, e.g. 10-K, 10-Q, 8-K, DEF 14A; leave out for all"},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 40, "description": "Filings to return"}},
    ),
    input_param="company",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    ua = (cfg.get("user_agent") or "").strip()
    if not ua:
        return f'{LABEL} user_agent is required in config — the SEC asks for a name and contact email, e.g. "Acme Research ops@acme.com".'
    text = inp.strip().upper()
    if not text:
        return f"{LABEL} Provide a ticker (AAPL) or CIK."
    form = str(cfg.get("form_type") or "").strip().upper()
    limit = max(1, min(int(cfg.get("max_results") or 10), 40))
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": ua}) as client:
            if text.isdigit():
                cik = int(text)
            else:
                resp = await client.get(TICKERS)
                if resp.status_code == 403:
                    return f"{LABEL} The SEC refused the request — check user_agent names you and an email."
                resp.raise_for_status()
                cik = next((int(c["cik_str"]) for c in resp.json().values() if c.get("ticker", "").upper() == text), None)
                if cik is None:
                    return f"{LABEL} No company with ticker {text}."
            resp = await client.get(SUBMISSIONS.format(cik=cik))
            if resp.status_code == 404:
                return f"{LABEL} No company with CIK {cik}."
            if resp.status_code == 403:
                return f"{LABEL} The SEC refused the request — check user_agent names you and an email."
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach the SEC: {e}"
    except ValueError:
        return f"{LABEL} The SEC returned an unexpected response."

    recent = (data.get("filings") or {}).get("recent") or {}
    rows = zip(recent.get("form", []), recent.get("filingDate", []), recent.get("accessionNumber", []),
               recent.get("primaryDocument", []), recent.get("primaryDocDescription", []))
    filings = [r for r in rows if not form or r[0].upper() == form][:limit]
    name = data.get("name", text)
    head = f"{LABEL} {name} (CIK {cik}" + (f", {', '.join(data['tickers'])}" if data.get("tickers") else "") + ")"
    if not filings:
        return f"{head}\nNo recent {form or ''} filings.".replace("  ", " ")
    lines = [head, f"Latest {len(filings)} {form + ' ' if form else ''}filing(s):"]
    for f_type, date, acc, doc, desc in filings:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
        lines.append(f"- {date}  {f_type}" + (f" — {desc}" if desc and desc.upper() != f_type.upper() else "") + f"\n  {url}")
    return "\n".join(lines)
