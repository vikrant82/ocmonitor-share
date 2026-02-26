# Remote Pricing Fallback Implementation Plan (`models.dev`)

## 1. Goal

Add an **optional remote pricing fallback** that pulls model pricing from [`https://models.dev/api.json`](https://models.dev/api.json) and only fills gaps not covered by local files, with a cache that is shared across all local projects.

## 2. Confirmed `models.dev` Fetch Strategy

Based on official `models.dev` docs:

- Primary endpoint: `GET https://models.dev/api.json`
- Useful filters (optional):
  - `?provider=<provider-id>`
  - `?model=<model-id>`
  - `?with_hidden=true`
- Response shape (relevant parts):
  - Top-level `providers` object
  - Per provider: `models`
  - Per model: `cost` and `limit`

Relevant fields to map:

- `cost.prompt` -> input token price
- `cost.completion` -> output token price
- `cost.input_cache_write` -> cache write token price
- `cost.input_cache_read` -> cache read token price
- `limit.context` -> context window

Fields to ignore for v1 fallback (not represented in current local schema):

- `cost.request`, `cost.image`, and non-context limits like `limit.output`

## 3. Target Behavior

Pricing precedence (highest -> lowest):

1. User override file (optional)
2. Project/local `models.json` (current behavior)
3. `models.dev` fallback (optional; fill-only)

Rules:

- Remote fallback is disabled by default.
- When enabled, remote data **must not overwrite** user/local values.
- `--no-remote` disables remote fetch for one CLI run, regardless of config.
- Failures in remote fetch must not break reports; fallback to local-only pricing.

## 4. Shared Cache Design (Cross-Project)

### 4.1 Cache location

Use a user-level cache path so all project clones share it:

- Default: `${XDG_CACHE_HOME:-~/.cache}/ocmonitor/models_dev_api.json`
- Lock file: `${cache_path}.lock`

This ensures one cache is reused by every `ocmonitor` repo in the same user account.

### 4.2 Cache metadata

Store envelope metadata alongside payload:

```json
{
  "schema_version": 1,
  "source_url": "https://models.dev/api.json",
  "fetched_at": "2026-02-17T10:00:00Z",
  "expires_at": "2026-02-18T10:00:00Z",
  "payload": { "...": "raw models.dev JSON" }
}
```

### 4.3 Cache policy

- If cache exists and `now < expires_at`: use cache; skip network.
- If stale/missing: fetch remote and atomically refresh cache.
- If fetch fails and stale cache exists: use stale cache (warn once).
- If fetch fails and no cache: continue local-only pricing.

### 4.4 Concurrency safety

- Acquire lock on `${cache_path}.lock` before refresh.
- Write cache to temp file in same directory, then `os.replace(...)`.
- Never leave partial JSON in final cache path.

## 5. Config Changes

Update `ModelsConfig` in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/config.py` and defaults in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/config.toml`:

- `remote_fallback: bool = false`
- `remote_url: str = "https://models.dev/api.json"`
- `remote_timeout_seconds: int = 8`
- `remote_cache_ttl_hours: int = 24`
- `remote_cache_path: str = "~/.cache/ocmonitor/models_dev_api.json"`
- `user_file: Optional[str] = "~/.config/ocmonitor/models.json"`
- `allow_stale_cache_on_error: bool = true`

Add path-expansion validation for `remote_cache_path` and `user_file`.

## 6. Code Changes by File

### 6.1 `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/services/price_fetcher.py` (new)

Responsibilities:

- Fetch `models.dev` JSON via standard library (`urllib.request`) to avoid new dependency.
- Read/write shared cache with TTL and locking.
- Convert remote response to local pricing dict format.

Key functions:

- `fetch_models_dev_json(url: str, timeout: int) -> dict`
- `load_cached_payload(cache_path: Path) -> Optional[dict]`
- `save_cached_payload_atomic(cache_path: Path, envelope: dict) -> None`
- `get_remote_payload(config) -> Optional[dict]`
- `map_models_dev_to_local(payload: dict) -> Dict[str, Dict[str, Any]]`

### 6.2 `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/config.py`

Refactor pricing load flow:

- Split loading into raw dictionaries first (local + user + remote), then validate with `ModelPricing`.
- Add merge function:
  - `merge_model_prices(local_raw, user_raw, remote_raw) -> raw_merged`
- Keep `load_pricing_data()` as public API, but support runtime remote override (from CLI flag).

### 6.3 `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/cli.py`

Add root option:

- `--no-remote` (bool)

Behavior:

- If `--no-remote` is set, bypass remote fallback even if enabled in config.
- Pass resolved setting into pricing loader before `SessionAnalyzer` initialization.

### 6.4 `/Users/shelli/Documents/apps/ocmonitor-share/README.md` and `/Users/shelli/Documents/apps/ocmonitor-share/DOCUMENTATION.md`

Document:

- New config keys
- Merge precedence
- Shared cache path
- `--no-remote` usage
- Offline behavior and stale-cache fallback

## 7. Mapping and Merge Rules

### 7.1 Remote -> local field mapping

For each `provider_id`, each `model_id`:

- `input` = `cost.prompt` or `0.0`
- `output` = `cost.completion` or `0.0`
- `cacheWrite` = `cost.input_cache_write` or `0.0`
- `cacheRead` = `cost.input_cache_read` or `0.0`
- `contextWindow` = `limit.context` or `0`
- `sessionQuota` = `0.0` (not provided by `models.dev`)

### 7.2 Model key strategy

Generate both keys for better compatibility:

- bare: `<model_id>` (lowercase)
- fully-qualified: `<provider_id>/<model_id>` (lowercase)

Do not overwrite any existing key from user/local sources.

### 7.3 Final precedence algorithm

1. Load local project pricing file.
2. Overlay user file (field-level merge when model exists).
3. If remote enabled, add only missing model keys and missing fields.
4. Validate each merged model into `ModelPricing`; skip invalid entries with warning.

## 8. Test Plan

### 8.1 Unit tests: remote fetcher + mapper

Add `/Users/shelli/Documents/apps/ocmonitor-share/tests/unit/test_price_fetcher.py`:

1. `test_fetch_models_dev_success_parses_json`
2. `test_fetch_models_dev_http_error_returns_none`
3. `test_fetch_models_dev_timeout_returns_none`
4. `test_cache_fresh_skips_network`
5. `test_cache_stale_refreshes`
6. `test_cache_stale_fetch_failure_uses_stale_when_allowed`
7. `test_cache_missing_and_fetch_failure_returns_none`
8. `test_cache_write_is_atomic`
9. `test_lock_file_prevents_concurrent_corruption` (threaded/process-level smoke)
10. `test_map_models_dev_fields_to_local_schema`
11. `test_map_missing_cost_fields_defaults_to_zero`
12. `test_map_creates_bare_and_provider_prefixed_keys`

### 8.2 Unit tests: config + merge logic

Extend `/Users/shelli/Documents/apps/ocmonitor-share/tests/unit/test_config.py`:

1. `test_models_config_defaults_include_remote_fields`
2. `test_models_paths_expand_user_and_env_vars`
3. `test_merge_precedence_user_over_local_over_remote`
4. `test_remote_fill_only_does_not_override_local_values`
5. `test_user_file_missing_is_non_fatal`
6. `test_invalid_remote_entries_are_skipped_not_fatal`
7. `test_load_pricing_data_respects_no_remote_override`

### 8.3 Integration tests: CLI behavior

Extend `/Users/shelli/Documents/apps/ocmonitor-share/tests/integration/test_cli.py`:

1. `test_cli_no_remote_flag_disables_remote_fetch`
2. `test_cli_remote_enabled_uses_remote_for_missing_model`
3. `test_cli_remote_failure_still_succeeds_with_local_pricing`
4. `test_cli_uses_shared_cache_path_across_runs`

Implementation note: monkeypatch network layer (`urllib.request.urlopen`) and cache paths to temp dirs to keep tests deterministic and offline.

### 8.4 Regression test for model ID matching

Add/extend tests around model keys:

- Session model ID `provider/model` resolves pricing from fully-qualified key.
- Existing non-prefixed model IDs still resolve exactly as before.

## 9. Rollout Plan

1. Ship behind `remote_fallback = false` default.
2. Add tests first for merge and cache behavior.
3. Implement fetcher + mapper.
4. Wire into config loader and CLI flag.
5. Update docs and changelog.
6. Run full suite (`pytest tests/`) and targeted manual checks.

## 10. Acceptance Criteria

- Remote fallback never breaks CLI in offline mode.
- Unknown models missing in local pricing are automatically priced when available remotely.
- Local/user prices are never overwritten by remote fallback.
- Cache file is shared across projects and reused within TTL.
- `--no-remote` always forces local-only behavior.
- Tests cover fetch, cache, mapping, merge precedence, and CLI flag behavior.

## References

- `models.dev` docs text: [`https://models.dev/llms-full.txt`](https://models.dev/llms-full.txt)
- API endpoint: [`https://models.dev/api.json`](https://models.dev/api.json)
- Project repo: [`https://github.com/anomalyco/models.dev`](https://github.com/anomalyco/models.dev)
