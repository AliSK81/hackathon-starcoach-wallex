**System Description — Wallex Algorithmic Trading Challenge**

The system is an automated trading engine on Wallex that receives and analyzes market data, identifies opportunities via a defined strategy, decides buy/sell algorithmically without manual intervention, executes trades automatically, pursues positive returns through capital and risk management, and has fast, verifiable, reproducible performance reviewable and re-runnable by judges. Logic is clear; performance does not depend solely on one lucky trade or accidental conditions. UI/UX is not evaluated; judging covers engine performance, logic, and results.

**Infrastructure**
- Wallex MCP — connects AI agents to Wallex capabilities.
- Wallex API — market data, order placement, order checks, trade management.
AI models, Agentic AI frameworks, data analysis tools, and any strategy design are permitted; architecture, decision model, and risk method are the team's choice. All evaluated trades are algorithmic; manual trades are invalid.

**Hard Constraints (violation → performance removed from evaluation)**
- Only Wallex-approved markets; no trading outside the permitted list.
- No manual trades — all decisions and orders by the algorithm.
- No self-trading between same-person or commonly controlled accounts to influence results.
- No coordinated intra-team trades among team members or related accounts to create unreal performance.
- No wash trading / artificial volume / manipulation of evaluation metrics.

**Return Metric**
Return (%) = ((Final asset value − 5,000,000) ÷ 5,000,000) × 100
Final asset value = net value of the dedicated account at official end, including realized P&L, trading fees, remaining account assets, and unrealized P&L of open positions. P&L must be realized in Toman; no coin-denominated holdings at end, so value is not price-dependent. Return is measured in realized terms. Example: 6,250,000 → +25%; 4,500,000 → −10%. Higher positive return ranks higher.

**Testing**
- Backtesting — performance reviewed on historical data to assess strategy behavior and evaluable logic.
- Shadow Testing — run in live market conditions with no real orders, to review decisions without capital.
Both earn technical points; recommended before real trading.

**Reproducibility**
Positive return alone is insufficient. The algorithm must decide by defined rules and logic, have explainable trades, be re-runnable in similar conditions, and have results evaluable via trading data and technical tests — distinguishing reliable strategies from accidental or temporary profits.

**Deliverables**
- 5-min demo video (mandatory; absence → removed from judging; quality affects score). Shows output, not code; performance, impact, and demonstrable items matter; no special editing needed.
- GitHub source code — exact version used in trading.
- MD doc in the same repo covering: architecture and main logic; AI and Wallex tool usage; buy/sell decision conditions; capital and risk management; how to re-run and evaluate performance.
- Per-trade decision log: signal seen and reason for buy/sell; makes manual trades identifiable.
- Judges may request a run-through or re-demonstration. A P&L report or trade list without a reviewable algorithm is insufficient for technical approval.

**Judging — 300 pts, two stages**
- Stage One (financial): final account value and net return calculated; highest return ranks highest.
- Stage Two (technical): trading logic, Agentic AI use, risk management, reproducibility, backtest/shadow results. Winners need positive return, superior financial performance, and technical pass. High return without reviewable/reproducible logic may fail technical approval.

**Trading Performance (150)** — reviewed on dedicated account data; indicators: number of trades, trading volume, average trade volume, ratio of final account value to initial capital (net return %), speed of performance and trade execution. Relative return is the most important financial criterion; trade count/volume analyze quality and do not alone indicate success.
| Criterion | Pts | Basis |
|---|---|---|
| Final profit % | 90 | Ranked among teams; loss-making = 0 |
| Loss control | 30 | Smaller account drawdown = more points |
| Activity | 15 | Regular, reasonable trading over 3 days |
| Execution stability | 15 | Few errors, correct orders, no crashes |

**Technical Quality (150)** — reviewed for market analysis and decision logic, Agentic AI use, re-runnability, risk and capital management, result reviewability, and supplementary-test performance.
| Criterion | Pts | Basis |
|---|---|---|
| Strategy logic | 40 | Explainable why/on what basis it buys and sells |
| Real AI use | 35 | AI genuinely drives decisions, not if/else in disguise |
| Risk & capital mgmt | 30 | Order size cap, stop loss, no all-in entry |
| Reproducibility | 25 | Clean code, execution guide, judge can re-run |
| Backtest + shadow | 20 | Performed and results shown |