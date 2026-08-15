---
name: Decision Record
about: Log a trading decision for analysis
title: "[DECISION] SETUP_TYPE @ TIMESTAMP"
labels: decision-record
---

## Decision Details

<!-- 把 Claude 生成的 DecisionRecord JSON 貼在下方的 json 代碼塊內,
     必須是合法 JSON、且包含 market_snapshot / trader_state / action 三個欄位,
     否則 .github/workflows/parse-decision.yml 會解析失敗並讓這個 job 失敗。 -->

```json
{
  "id": "...",
  "ts": "...",
  "market_snapshot": {},
  "trader_state": {},
  "action": {}
}
```

## Prediction

<!-- 選填:給自己看的補充說明,例如為什麼有這個信心度、當下還在猶豫什麼 -->
