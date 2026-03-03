# Changelog

All notable changes to OpenCode Monitor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.4] - 2026-03-03

### 🔍 Model Detail Command

New `ocmonitor model <name>` command for drilling into a single AI model with rich statistics.

#### Added
- **`model` command** - Detailed breakdown for a single model, fuzzy-matched by name
- **ModelDetailStats Model** - Pydantic model with first/last used, sessions, days used, interactions, token breakdown, costs, output speed, and tool stats
- **Fuzzy Name Matching** - Substring match against all model names in the database
  - 0 matches: shows "No model found" + full list of available models
  - >1 matches: lists candidates with "Did you mean one of these?"
  - Exact match wins even when other substring matches exist
- **SQLite Queries** - Two new classmethods on `SQLiteProcessor`:
  - `find_matching_models(query)` - fuzzy substring search
  - `get_model_detail_stats(model_name, pricing_data)` - aggregate stats + output rates + tool stats

#### Files Modified
- `ocmonitor/models/analytics.py` - Added `ModelDetailStats` class
- `ocmonitor/utils/sqlite_utils.py` - Added `find_matching_models()` and `get_model_detail_stats()`
- `ocmonitor/utils/data_loader.py` - Added `find_matching_models()` and `get_model_detail()` delegation methods
- `ocmonitor/services/session_analyzer.py` - Added `find_matching_models()` and `get_model_detail()` methods
- `ocmonitor/services/report_generator.py` - Added `generate_model_detail_report()`, `_display_model_detail()`, JSON/CSV formatters
- `ocmonitor/ui/tables.py` - Added `create_model_detail_panel()` and `create_model_tool_table()`
- `ocmonitor/cli.py` - Added `model` command

#### Features
- 📋 **Key-Value Panel** - First Used, Last Used, Sessions, Days Used, Interactions, Input/Output/Cache tokens, Total Cost, Avg/Day, Avg/Session, Output Speed (p50)
- 🔧 **Tool Usage Table** - Per-tool Calls, Success, Failed, and color-coded Success Rate (green ≥90%, yellow ≥70%, red <70%)
- 📊 **Tool Summary** - Total calls, successes, failures, overall success rate
- 📤 **JSON/CSV Export** - Full stats available via `-f json` or `-f csv`

#### Usage
```bash
# Exact or fuzzy match
ocmonitor model claude-sonnet-4-5
ocmonitor model sonnet        # lists all sonnet variants
ocmonitor model nonexistent   # shows available models

# JSON output
ocmonitor model claude-opus-4-5 -f json
```

### 🎯 Live Workflow Picker & Session Pinning

Interactive workflow selection and switching during live monitoring.

#### Added
- **`--pick` flag** - Interactive picker to select workflow before starting live monitor
- **`--session-id` flag** - Pin live monitor to specific workflow/session ID
- **`--interactive-switch` flag** - Enable keyboard controls during live monitoring
- **Live switching controls** - Press n/p for next/previous, l to list, 1-9 to jump, q to quit

#### Usage
```bash
ocmonitor live --pick                    # Pick workflow, enable switching
ocmonitor live --session-id ses_abc123   # Pin to specific session
ocmonitor live --interactive-switch      # Enable keyboard controls
```

#### Files Modified
- `ocmonitor/cli.py` - Added `--pick`, `--session-id`, `--interactive-switch` options
- `ocmonitor/services/live_monitor.py` - Added picker, terminal input handling, workflow switching
- `ocmonitor/ui/dashboard.py` - Added controls panel to dashboard layout

#### Tests
- 197 unit tests for picker, command handling, session resolution
- 2 integration tests for CLI flag precedence

## [0.9.3] - 2026-02-20

### 🔧 Tool Usage Tracking

Real-time tool success/failure metrics in the live dashboard.

#### Added
- **Tool Usage Panel** - Shows success rates for tools (bash, read, edit, etc.) in live dashboard
- **ToolUsageStats Model** - Tracks tool_name, total_calls, success_count, failure_count, success_rate
- **SQLite Tool Aggregation** - Queries `part` table for tool entries with terminal statuses

#### Files Added
- `ocmonitor/models/tool_usage.py` - Tool usage statistics models
- `tests/unit/test_sqlite_tool_usage.py` - Unit tests for tool aggregation

#### Files Modified
- `ocmonitor/utils/sqlite_utils.py` - Added `load_tool_usage_for_sessions()` method
- `ocmonitor/utils/data_loader.py` - Added `load_tool_usage()` method
- `ocmonitor/services/live_monitor.py` - Integrated tool stats into dashboard generation
- `ocmonitor/ui/dashboard.py` - Added Tools panel, modified layout (Models + Tools side-by-side)

#### Features
- 📊 **Success Rate Tracking** - Shows completed vs error counts per tool
- 🎨 **Color-Coded Progress Bars** - Green (≥90%), yellow (70-89%), red (<70%)
- 📋 **Top 6 Tools** - Shows most-used tools by call count
- 🚫 **Status Filtering** - Only counts `completed` and `error` statuses; excludes `running`

#### Layout Change
- Bottom section changed from full-width Models panel to side-by-side: `Models (60%)` | `Tools (40%)`

#### Tests
- 9 unit tests for tool usage aggregation and model

## [0.9.2] - 2026-02-17

### 🌐 Remote Pricing Fallback

Optional integration with [models.dev](https://models.dev) for automatic model pricing updates, filling gaps not covered by local pricing files.

#### Added
- **Remote Pricing Fallback** - Fetch model pricing from `https://models.dev/api.json`
- **Shared Cache** - Cross-project cache at `~/.cache/ocmonitor/models_dev_api.json`
- **User Override File** - `~/.config/ocmonitor/models.json` with highest priority
- **`--no-remote` Flag** - Disable remote fetch for a single command
- **Stale Cache Fallback** - Use expired cache when network unavailable

#### Files Added
- `ocmonitor/services/price_fetcher.py` - Remote fetcher with caching and locking

#### Configuration
```toml
[models]
remote_fallback = false           # Opt-in (default: disabled)
remote_url = "https://models.dev/api.json"
remote_timeout_seconds = 8
remote_cache_ttl_hours = 24
remote_cache_path = "~/.cache/ocmonitor/models_dev_api.json"
user_file = "~/.config/ocmonitor/models.json"
allow_stale_cache_on_error = true
```

#### Pricing Precedence (highest → lowest)
1. User override file (`~/.config/ocmonitor/models.json`)
2. Project/local `models.json`
3. models.dev remote fallback (fill-only, never overwrites)

#### Features
- 🔒 **Atomic Cache Writes** - Safe concurrent access with file locking
- 📦 **Dual Model Keys** - Both `model-name` and `provider/model-name` supported
- 🔄 **TTL-based Caching** - 24-hour default, configurable
- 🛡️ **Graceful Degradation** - CLI works offline, uses stale cache if available
- ⚡ **Field-level Merge** - Remote only fills missing fields, never overwrites

#### Usage
```bash
# Enable in config, then use normally
ocmonitor sessions

# Force local-only pricing
ocmonitor --no-remote sessions
```

#### Tests
- 25 unit tests for price fetcher (cache, locking, mapping)
- 8 unit tests for config merge logic

## [0.9.1] - 2026-02-14

### ✨ SQLite Database Support

OpenCode v1.2.0+ migrated session storage from flat JSON files to SQLite. This release adds full support for the new database format while maintaining backwards compatibility.

#### Added
- **SQLite Database Support** - Read sessions from `~/.local/share/opencode/opencode.db`
- **Dual Storage Architecture** - Automatically prefers SQLite when available, falls back to legacy files
- **Hierarchical Session Display** - Parent sessions with sub-agents shown in tree view
- **Live Workflow Monitoring** - Tracks only current workflow (main + sub-agents) from SQLite
- **DataLoader Abstraction** - Unified interface with automatic source detection

#### Files Added
- `ocmonitor/utils/sqlite_utils.py` - SQLite database access layer
- `ocmonitor/utils/data_loader.py` - Unified data loading with automatic fallback

#### Modified Commands
```bash
# Auto-detect SQLite or files (default)
ocmonitor live
ocmonitor sessions

# Force specific source
ocmonitor live --source sqlite
ocmonitor live --source files
ocmonitor sessions --source sqlite
```

#### Features
- 🗄️ **SQLite Integration** - Reads from `opencode.db` session/message tables
- 🌳 **Hierarchical View** - Parent sessions grouped with sub-agents
- 🔄 **Auto Fallback** - Automatically uses legacy files if SQLite unavailable
- 📊 **Workflow Tracking** - Live dashboard monitors current workflow only
- 🔍 **Source Detection** - Verbose mode shows which data source is active

#### Database Schema Support
- **session table** → SessionData with parent_id relationships
- **message table** → InteractionFile (parsed from JSON data column)
- **project table** → Project paths via JOIN

#### Technical Changes
- SessionData model extended with `parent_id`, `is_sub_agent`, `source` fields
- LiveMonitor adds SQLite workflow monitoring methods
- DataLoader provides `sqlite_available`, `files_available` properties
- Backwards compatible with OpenCode < v1.2.0

## [0.9.0] - 2026-02-05

### 🎉 Initial Release

#### Added
- **Core CLI Application** - Complete command-line interface with Click framework
- **Rich Terminal UI** - Beautiful tables, progress bars, and colored output
- **Comprehensive Analytics** - Daily, weekly, monthly, and model-based breakdowns
- **Real-time Monitoring** - Live dashboard for active session monitoring
- **Data Export** - CSV and JSON export functionality with metadata
- **Multi-model Support** - Support for 6 AI models including Claude, Grok, Qwen, and Z-AI
- **Professional Documentation** - Complete setup guides and user documentation

#### Features
- 📊 **Session Analysis** - Analyze individual or batch sessions
- 💰 **Cost Tracking** - Accurate cost calculations with model-specific pricing
- 📈 **Usage Analytics** - Token usage, context utilization, and performance metrics
- 🎨 **Rich UI Components** - Color-coded tables with progress indicators
- ⚙️ **TOML Configuration** - User-friendly configuration management
- 🔄 **Live Dashboard** - Real-time session monitoring with auto-refresh
- 📤 **Export Capabilities** - Professional CSV and JSON exports

#### Supported Commands
```bash
ocmonitor config show      # Display configuration
ocmonitor session <path>   # Analyze single session
ocmonitor sessions <path>  # Analyze all sessions  
ocmonitor daily <path>     # Daily usage breakdown
ocmonitor weekly <path>    # Weekly usage breakdown
ocmonitor monthly <path>   # Monthly usage breakdown
ocmonitor models <path>    # Model usage analytics
ocmonitor live <path>      # Real-time monitoring
ocmonitor export <type>    # Data export functionality
```

#### Supported AI Models
- **Claude Sonnet 4** (2025-05-14) - $3/$15 per 1M tokens, 200k context
- **Claude Opus 4** - $15/$75 per 1M tokens, 200k context  
- **Claude Opus 4.1** - $15/$75 per 1M tokens, 200k context
- **Grok Code** - FREE, 256k context
- **Qwen3 Coder** (qwen/qwen3-coder) - FREE, 256k context
- **Z-AI GLM 4.5 Air** (z-ai/glm-4.5-air) - FREE, 128k context

#### Technical Improvements
- **Modular Architecture** - Clean separation of concerns with services, models, and UI
- **Error Handling** - Comprehensive error handling with user-friendly messages
- **Type Safety** - Full type hints and Pydantic models for data validation
- **Performance** - Memory-efficient processing of large session datasets
- **Extensibility** - Easy addition of new models and features

### 🛠️ Development Infrastructure

#### Added
- **Automated Installation** - `install.sh` script for easy setup
- **Comprehensive Testing** - Manual test suites and validation scripts
- **Documentation** - README, Quick Start, Manual Test Guide
- **Configuration Management** - TOML config with JSON model pricing
- **PATH Management** - Automatic PATH configuration handling

### 🐛 Bug Fixes

#### Fixed
- **JSON Serialization** - Fixed Decimal serialization for JSON exports
- **Model Name Parsing** - Proper handling of fully qualified model names (e.g., `qwen/qwen3-coder`)
- **Zero-token Filtering** - Filtered out empty interactions that caused confusion
- **Export Data Structure** - Fixed CLI export command data structure issues
- **Import Path Resolution** - Resolved Python module path issues
- **Installation Issues** - Created comprehensive installation guides and PATH configuration

### 📚 Documentation

#### Added
- **README.md** - Complete project overview and usage instructions
- **QUICK_START.md** - Fast setup and common usage patterns
- **MANUAL_TEST_GUIDE.md** - Comprehensive testing procedures
- **PROJECT_SUMMARY.md** - Detailed project documentation and achievements
- **Installation Guides** - Multiple installation methods with troubleshooting

### 🧪 Testing

#### Added
- **Basic Functionality Tests** - Core feature validation
- **Import Validation** - Module import and dependency checks
- **CLI Command Tests** - All command-line interfaces tested
- **Real Data Testing** - Validation with actual OpenCode session data
- **Error Scenario Testing** - Edge case and error handling validation

---

## Version History Summary

- **v0.9.4** - Model detail command with fuzzy matching; live workflow picker and session pinning
- **v0.9.3** - Tool usage tracking in live dashboard
- **v0.9.2** - Remote pricing fallback from models.dev
- **v0.9.1** - SQLite database support for OpenCode v1.2.0+
- **v0.9.0** - Pre-release version for community feedback and testing before stable v1.0.0
- **Pre-release** - Development phases transforming basic scripts into professional CLI tool

## Migration from Legacy Scripts

This release replaces the original three Python scripts:
- `session_summarizer.py` → `ocmonitor sessions`
- `token_summarizer.py` → `ocmonitor models` 
- `live_dashboard.py` → `ocmonitor live`

The new unified CLI provides all original functionality plus significant enhancements:
- Beautiful Rich terminal interface
- Comprehensive analytics and breakdowns
- Professional export capabilities  
- Real-time monitoring dashboard
- Robust error handling and validation
- Easy installation and configuration

---

*For detailed information about each feature, see the [README.md](README.md) and [documentation](QUICK_START.md).*
