# claude-session-cost

See what each Claude Code session costs: a running per-session dollar figure in Claude Code's **statusline**, plus a **CLI report** of past sessions. One Python file, standard library only (Python 3.8+), no secrets, nothing sent anywhere.

![statusline and report rendered from fake fixture data](docs/screenshot.png)

*(The screenshot uses generated fake fixtures, not real usage.)*

## What it shows

**Statusline** (updates after every assistant message):

```
[Opus 5.5] │ $1.62 │ (cc $1.59) │ in 612 · out 32.0k · cw 84.4k · cr 1.5M
```

| Part | Meaning |
| --- | --- |
| `[Opus 5.5]` | current model (`model.display_name`) |
| `$1.62` | session cost **computed by this tool** from the transcript |
| `(cc $1.59)` | Claude Code's own `cost.total_cost_usd` estimate, shown as a cross-check |
| `in / out / cw / cr` | uncached input, output, cache-write (5m + 1h), cache-read tokens for the session |
| `?unpriced model` | (red) a model in the transcript isn't in the pricing table, so its tokens aren't counted |

**Report** (`claude-cost report`): one row per session (most recent first), with last activity (local time), short session id, project, main model, token columns and cost, plus a total row. Options:

```
claude_cost.py report            # last 10 sessions
claude_cost.py report -n 0       # all sessions
claude_cost.py report --today    # usage since local midnight
claude_cost.py report --days 7 -n 0
claude_cost.py report --json     # machine-readable (includes sidechain cost + per-model breakdown)
claude_cost.py pricing           # print the active pricing table
```

## Install (one command)

```bash
mkdir -p ~/.claude && curl -fsSL https://raw.githubusercontent.com/TangentialSolutions/claude-session-cost/main/claude_cost.py -o ~/.claude/claude_cost.py && chmod +x ~/.claude/claude_cost.py
```

(or clone the repo and `cp claude_cost.py ~/.claude/`). Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/claude_cost.py statusline"
  }
}
```

Claude Code reloads settings automatically. For the report, optionally `alias claude-cost='python3 ~/.claude/claude_cost.py'`. Windows: use forward slashes in the command path (e.g. `python C:/Users/you/.claude/claude_cost.py statusline`). Set `NO_COLOR=1` to disable ANSI colors.

## How cost is computed

**Data source.** Claude Code pipes a JSON object to the statusline command on stdin ([docs](https://code.claude.com/docs/en/statusline)); this tool uses `session_id`, `transcript_path`, `model.display_name` and `cost.total_cost_usd`. It then reads the session transcript, a JSONL file under `~/.claude/projects/<encoded-project-path>/<session_id>.jsonl` (plus any subagent transcripts in `<session_id>/subagents/*.jsonl`). The report scans every `*.jsonl` under `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`, or `--dir`).

Each `"type": "assistant"` line carries the raw API `message.usage`:

```json
{"type":"assistant","sessionId":"…","requestId":"req_…","timestamp":"…","isSidechain":false,
 "message":{"id":"msg_…","model":"claude-opus-4-5-20251101","usage":{
   "input_tokens":1000,"output_tokens":500,
   "cache_creation_input_tokens":20000,"cache_read_input_tokens":0,
   "cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":20000},
   "server_tool_use":{"web_search_requests":0}}}}
```

**Dedupe.** Claude Code writes one transcript line per content block (thinking, text, tool_use) of a streamed response, and each repeats the same `usage`. Lines are deduped by `(message.id, requestId)` (falling back to the line `uuid`), keeping the copy with the largest `output_tokens`. `<synthetic>` messages (local errors) are ignored, and malformed/partial lines are skipped.

**Pricing table.** `PRICING` at the top of `claude_cost.py`, in USD per million tokens, copied from **https://docs.claude.com/en/docs/about-claude/pricing on 2026-10-26**:

| Model | Input | 5m cache write | 1h cache write | Cache read | Output |
| --- | --- | --- | --- | --- | --- |
| Fable 5.1 / Mythos 5.1 | 10 | 12.50 | 20 | 0.25 | 50 |
| Fable 5 / Mythos 5 | 10 | 12.50 | 20 | 1.00 | 50 |
| Opus 5.5 | 4 | 5 | 8 | 0.20 | 20 |
| Opus 5 / 4.8 / 4.7 / 4.6 / 4.5 | 5 | 6.25 | 10 | 0.50 | 25 |
| Opus 4.1 / 4 | 15 | 18.75 | 30 | 1.50 | 75 |
| Sonnet 5.5 | 2 | 2.50 | 4 | 0.10 | 10 |
| Sonnet 5 | 2 | 2.50 | 4 | 0.20 | 10 |
| Sonnet 4.6 / 4.5 / 4 | 3 | 3.75 | 6 | 0.30 | 15 |
| Haiku 5.5 (prompt ≤ 100k / > 100k) | 0.10 / 0.50 | 0.125 / 0.625 | 0.20 / 1 | 0.01 / 0.05 | 0.50 / 2.50 |
| Haiku 4.5 | 1 | 1.25 | 2 | 0.10 | 5 |
| Haiku 3.5 | 0.80 | 1 | 1.60 | 0.08 | 4 |

Also applied: web search at $10 / 1,000 searches (`server_tool_use.web_search_requests`), Haiku 5.5's long-prompt tier per request, and Opus fast-mode input/output rates when `usage.speed == "fast"`.

Model ids are normalized (`claude-opus-4-5-20251101[1m]`, `us.anthropic.claude-sonnet-4-5-…-v1:0`, `claude-3-5-haiku-…` → `opus-4-5`, `sonnet-4-5`, `haiku-3-5`) and matched exactly or by longest prefix. **Unknown models** are not guessed: their tokens are still counted, but the cost is excluded and flagged (`?unpriced model` / `*`).

**Overriding prices.** Put a JSON file at `~/.claude/claude-cost-pricing.json`, or point `CLAUDE_COST_PRICING` at one. Entries are merged over the built-ins, and keys may be full model ids:

```json
{ "claude-opus-5-5": {"input": 4, "cache_write_5m": 5, "cache_write_1h": 8, "cache_read": 0.2, "output": 20},
  "my-proxy-model": {"input": 1, "cache_write_5m": 1.25, "cache_write_1h": 2, "cache_read": 0.1, "output": 5} }
```

**Cache tokens.** `input_tokens` is only the *uncached* input. Cache writes (`cache_creation_input_tokens`) are split into 5-minute and 1-hour writes using `usage.cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`. Any write not covered by that split (older transcripts) is priced as a 5-minute write, the API default, so if those writes were really 1-hour this **under**-estimates. Cache reads (`cache_read_input_tokens`) use the model's cache-hit rate.

**Cross-check.** Claude Code's `cost.total_cost_usd` is computed client-side at list price, and it resets on `/clear`. It's shown in parentheses so you can spot drift. Small differences are normal; large ones usually mean a pricing table is stale.

## Known accuracy limits

- **Subscription vs API billing.** On Claude Pro/Max/Team/Enterprise seats you don't pay per token. The number shown is the *API-equivalent list price*, not your bill. Negotiated discounts, Batch, Bedrock/Vertex/Foundry pricing, and the 1.1× US data-residency multiplier (`inference_geo: "us"`) aren't modeled. Override the table to approximate them.
- **Subagents and sidechains.** Task subagent usage is included when it's in the session transcript (`isSidechain: true`) or in `<session>/subagents/*.jsonl`. `report --json` breaks it out as `sidechain_cost_usd`. Subagent logs stored elsewhere by other Claude Code versions are missed. Claude Code's own figure may include or exclude these differently.
- **Pricing drift.** Prices are a snapshot from 2026-10-26. Check the source page and update `PRICING` (or use the override file) when Anthropic changes rates or ships new models.
- **Tokens missing from logs.** Only what Claude Code writes to the transcript is counted. Interrupted or failed requests, background calls (e.g. title generation, compaction summaries or classifier calls that aren't logged), and deleted or rotated transcripts (Claude Code prunes old transcripts after `cleanupPeriodDays`, 30 by default) aren't counted. `/clear` starts a new session id. A resumed session that forks into a new file is reported as a separate session.
- **Tool and other fees.** Web search is priced at $10/1k from `server_tool_use`. Code-execution container hours, Managed Agents runtime and any other non-token fees are not included.
- **Rounding.** Costs are computed per API response and summed. Your invoice may round differently.

## Development

```bash
python3 tests/make_fixtures.py        # regenerate fake fixtures
python3 -m unittest discover -s tests -v
python3 docs/render.py …              # screenshot helper (needs Pillow; dev only)
```

## License

MIT, see [LICENSE](LICENSE).
