# Architecture decision records

One file per decision that was actually taken here, in the format: context,
problem, options considered, decision, reasoning, trade-offs, consequences.
Records are append-only - a decision that gets reversed gets a new record that
supersedes the old one, and the old one stays.

| # | decision | status |
|---|---|---|
| [0001](0001-four-value-exit-code-contract.md) | A four-value exit-code contract, and analyzer failures that cannot hide | accepted |
| [0002](0002-sqlite-result-cache.md) | A SQLite result cache keyed on content, config and analyzer version | accepted |
| [0003](0003-agent-loop-is-opt-in.md) | The agent loop is a mode, not the execution path | accepted |
| [0004](0004-metrics-as-a-dump-not-an-endpoint.md) | Metrics are dumped at the end of a run, not scraped from an endpoint | accepted |
| [0005](0005-ship-a-cli-container-not-a-service.md) | Ship a CLI container and a GitHub Action, not a service | accepted |
| [0006](0006-measure-precision-on-an-adversarial-negative-corpus.md) | Measure precision on an adversarial negative corpus, not just recall | accepted |
