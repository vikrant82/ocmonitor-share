# Remote Pricing Fallback Plan

## Goals
- Keep local `models.json` as the default pricing source.
- Allow user overrides to take highest priority.
- Add an opt-in remote fallback (models.dev) with caching and explicit merge rules.
- Provide a `--no-remote` option to force local-only behavior.

## Proposed Behavior (Priority Order)
1. User override file (highest priority; optional).
2. Repo default `ocmonitor/models.json`.
3. Remote fallback (opt-in, only fills missing data; never overwrites user/local values).

## Config Additions
- `models.remote_fallback = false` (default)
- `models.remote_url = "https://models.dev"` (or a specific endpoint if needed)
- `models.remote_cache_ttl_hours = 24`
- `models.remote_cache_path = "~/.cache/ocmonitor/models.remote.json"`
- `models.user_file = "~/.config/ocmonitor/models.json"` (optional override)

## CLI Additions
- `--no-remote` flag to disable remote fetch for the current run (overrides config).

## Implementation Steps
1. **Add config fields** in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/config.py` and update default config in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/config.toml`.
2. **Create remote fetcher**  `services/price_fetcher.py`:
   - Fetch JSON from `models.remote_url`.
   - Validate schema (must include model name and required fields).
   - Store to cache path with timestamp metadata.
3. **Cache logic**:
   - If cache exists and is fresh (TTL), use cache.
   - If stale or missing, fetch and refresh cache.
   - If fetch fails, fall back to local sources and log a warning.
4. **Merge rules** in a single function (e.g. `merge_model_prices()`):
   - Start with repo defaults.
   - Overlay user override file (per-field override).
   - If remote enabled, only fill missing models or missing fields.
   - Do not overwrite fields already defined locally.
5. **Wire into pricing load path** in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/services/session_analyzer.py` or wherever pricing is loaded today.
6. **Add `--no-remote` flag** to CLI in `/Users/shelli/Documents/apps/ocmonitor-share/ocmonitor/cli.py` and pass through to pricing loader.
7. **Logging**:
   - Log when remote data is used.
   - Log warnings on fetch/parse failures, but do not fail commands.
8. **Tests** in `/Users/shelli/Documents/apps/ocmonitor-share/tests/`:
   - Merge precedence tests (user > local > remote).
   - Cache TTL behavior.
   - `--no-remote` disables fetch.
   - Remote failure fallback.
9. **Docs** updates:
   - `/Users/shelli/Documents/apps/ocmonitor-share/README.md`
   - `/Users/shelli/Documents/apps/ocmonitor-share/DOCUMENTATION.md`

