# 📊 OpenCode Monitor

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**OpenCode Monitor is a CLI tool for monitoring and analyzing OpenCode AI coding sessions.**

Transform your OpenCode usage data into beautiful, actionable insights with comprehensive analytics, real-time monitoring, and professional reporting capabilities.

**⚠️ Disclaimer** - This application is not affiliated with OpenCode AI. It is an independent community tool for monitoring OpenCode usage.

[![Sessions Summary Screenshot](screenshots/sessions-summary.png)](screenshots/sessions-summary.png)

## 🌟 Features

### 💼 Professional Analytics
- **📈 Comprehensive Reports** - Daily, weekly, and monthly usage breakdowns
- **💰 Cost Tracking** - Accurate cost calculations for multiple AI models
- **📊 Model Analytics** - Detailed breakdown of usage per AI model with `--breakdown` flag
- **📋 Project Analytics** - Track costs and token usage by coding project
- **⏱️ Performance Metrics** - Session duration and processing time tracking
- **📅 Flexible Week Boundaries** - Customize weekly reports with 7 start day options (Monday-Sunday)
- **🚀 Output Speed Tracking** - Average output tokens per second for each model in reports
- **🔗 Workflow Grouping** - Automatically groups main sessions with their sub-agent sessions (explore, etc.)

### 🗄️ Storage Support
- **SQLite Database** - Native support for OpenCode v1.2.0+ SQLite format (`~/.local/share/opencode/opencode.db`)
- **Legacy File Support** - Backwards compatible with pre-v1.2.0 JSON file storage
- **Auto Detection** - Automatically detects and uses the appropriate storage backend
- **Hierarchical Sessions** - Parent/sub-agent relationships from SQLite displayed as tree view

### 🎨 Beautiful User Interface
- **🌈 Rich Terminal UI** - Professional design with clean styling and optimal space utilization
- **📊 Progress Bars** - Visual indicators for cost quotas, context usage, and session time
- **🚥 Color Coding** - Green/yellow/red status indicators based on usage thresholds
- **📱 Live Dashboard** - Real-time monitoring with project names and session titles
- **⏰ Session Time Tracking** - 5-hour session progress bar with color-coded time alerts
- **🔧 Tool Usage Panel** - Track tool success rates (bash, read, edit, etc.) in live dashboard

### 📤 Data Export & Integration
- **📋 CSV Export** - Spreadsheet-compatible exports with metadata
- **🔄 JSON Export** - Machine-readable exports for custom integrations
- **📊 Multiple Report Types** - Sessions, daily, weekly, monthly, model, and project reports

## 🚀 Quick Start

### Installation

**Option 1: uv Installation (Fastest - One-liner)**

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. It installs the tool in an isolated environment without cloning the repository.

```bash
# Install directly from GitHub
uv tool install git+https://github.com/Shlomob/ocmonitor-share.git

# With optional extras
uv tool install "git+https://github.com/Shlomob/ocmonitor-share.git#egg=ocmonitor[charts,export]"
```

**Why uv?**
- No need to clone the repository
- Lightning-fast dependency resolution
- Creates isolated environments automatically
- Easy to upgrade: `uv tool upgrade ocmonitor`

**Option 2: pipx Installation (Cross Platform)**

[pipx](https://pypa.github.io/pipx/) is the recommended way to install Python CLI applications. It creates isolated environments and works on all platforms (including Arch Linux, Ubuntu, macOS, etc.).

```bash
git clone https://github.com/Shlomob/ocmonitor-share.git
cd ocmonitor-share
pipx install .
```

**Why pipx?**
- Creates isolated environments (no dependency conflicts)
- Works on Arch Linux without breaking system packages
- No sudo required
- Easy to upgrade or uninstall

**Optional extras:**
```bash
# With visualization charts
pipx install ".[charts]"

# With export functionality  
pipx install ".[export]"

# With all extras
pipx install ".[charts,export]"
```

**Option 3: Automated Installation (Linux/macOS)**
```bash
git clone https://github.com/Shlomob/ocmonitor-share.git
cd ocmonitor-share
./install.sh
```

**Option 4: Manual Installation**
```bash
git clone https://github.com/Shlomob/ocmonitor-share.git
cd ocmonitor-share
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```

### Basic Usage

```bash
# Quick configuration check
ocmonitor config show

# Analyze your sessions (auto-detects SQLite or files)
ocmonitor --theme light sessions

# Analyze by project
ocmonitor projects

# Real-time monitoring (dark theme)
ocmonitor --theme dark live

# Export your data
ocmonitor export sessions --format csv

# Force specific data source
ocmonitor sessions --source sqlite
ocmonitor sessions --source files
```

## 📖 Documentation

- **[Quick Start Guide](QUICK_START.md)** - Get up and running in 5 minutes
- **[Manual Test Guide](MANUAL_TEST_GUIDE.md)** - Comprehensive testing instructions
- **[Contributing Guidelines](CONTRIBUTING.md)** - How to contribute to the project

## 🎯 Use Cases

### Individual Developers
- **Cost Management** - Track your AI usage costs across different models and projects
- **Usage Optimization** - Identify patterns in your coding sessions with session time tracking
- **Performance Monitoring** - Monitor session efficiency and token usage with real-time dashboards
- **Project Analytics** - Understand which projects consume the most AI resources

### Development Teams
- **Team Analytics** - Aggregate usage statistics across team members and projects
- **Budget Planning** - Forecast AI costs based on usage trends and project breakdowns
- **Model Comparison** - Compare performance and costs across different AI models
- **Session Management** - Track coding session durations and productivity patterns

### Organizations
- **Resource Planning** - Plan AI resource allocation and budgets by project
- **Usage Reporting** - Generate professional reports for stakeholders with export capabilities
- **Cost Attribution** - Track AI costs by project, team, and time period
- **Quality Monitoring** - Monitor session lengths and usage patterns for optimization


## 📊 Example Output

> **📸 Screenshots**: The following examples include both text output and clickable screenshots. To add your own screenshots, place PNG files in the `screenshots/` directory with the corresponding filenames.

### Sessions Summary

[![Sessions Summary Screenshot](screenshots/sessions-summary.png)](screenshots/sessions-summary.png)

*Click image to view full-size screenshot of sessions summary output*

#### Workflow Grouping

By default, sessions are grouped into **workflows** - a main session combined with its sub-agent sessions (like `explore`). This gives you a complete picture of your coding session including all agent activity.

```bash
# Sessions with workflow grouping (default)
ocmonitor sessions ~/.local/share/opencode/storage/message

# Sessions without grouping (flat list)
ocmonitor sessions ~/.local/share/opencode/storage/message --no-group

# List detected agents and their types
ocmonitor agents
```

**Workflow Features:**
- Main sessions and sub-agent sessions are visually grouped with tree-style formatting
- Aggregated tokens and costs are shown for the entire workflow
- Sub-agent count displayed in the Agent column (e.g., `+2` means 2 sub-agents)
- Use `--no-group` to see individual sessions without grouping

### Time-Based Reporting

#### `ocmonitor daily|weekly|monthly <path> [--breakdown]`

Time-based usage breakdown with optional per-model cost analysis.

```bash
# Daily breakdown
ocmonitor daily ~/.local/share/opencode/storage/message

# Weekly breakdown with per-model breakdown
ocmonitor weekly ~/.local/share/opencode/storage/message --breakdown

# Monthly breakdown
ocmonitor monthly ~/.local/share/opencode/storage/message

# Weekly with custom start day
ocmonitor weekly ~/.local/share/opencode/storage/message --start-day friday --breakdown
```

**`--breakdown` Flag:** Shows token consumption and cost per model within each time period (daily/weekly/monthly), making it easy to see which models are consuming resources.

Supported days: `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`

### Live Monitoring Commands

#### `ocmonitor live <path>`

Real-time monitoring dashboard that updates automatically.

```bash
# Start live monitoring (updates every 5 seconds)
ocmonitor live ~/.local/share/opencode/storage/message

# Custom refresh interval (in seconds)
ocmonitor live ~/.local/share/opencode/storage/message --refresh 10
```

**Features:**
- 🔄 Auto-refreshing display with professional UI design
- 📊 Real-time cost tracking with progress indicators
- ⏱️ Live session duration with 5-hour progress bar
- 📈 Token usage updates and context window monitoring
- 🚀 **Output Rate** - Rolling 5-minute window showing output tokens per second
- 🚦 Color-coded status indicators and time alerts
- 📂 Project name display for better context
- 📝 Human-readable session titles instead of cryptic IDs
- 🔗 **Workflow Tracking** - Automatically tracks entire workflow including sub-agents (explore, etc.)
- 🔧 **Tool Usage Stats** - Shows success rates for tools (bash, read, edit, etc.) with color-coded progress bars

[![Live Dashboard Screenshot](screenshots/live_dashboard.png)](screenshots/live_dashboard.png)

*Click image to view full-size screenshot of the live monitoring dashboard*

### Model Usage Breakdown

[![Model Usage Breakdown Screenshot](screenshots/model-usage-breakdown.png)](screenshots/model-usage-breakdown.png)

*Click image to view full-size screenshot of model usage analytics*

**Model Analytics Features:**
- Per-model token usage and cost breakdown
- Cost percentage distribution across models
- **Speed Column** - Average output tokens per second for each model
- Session and interaction counts per model


## ⚙️ Configuration

### Configuration File Location

Create your configuration file at: **`~/.config/ocmonitor/config.toml`**

```bash
# Create the configuration directory
mkdir -p ~/.config/ocmonitor

# Create your configuration file
touch ~/.config/ocmonitor/config.toml
```

### Configuration Options

The tool is highly configurable through the `config.toml` file:

```toml
[paths]
# OpenCode v1.2.0+ SQLite database (preferred)
database_file = "~/.local/share/opencode/opencode.db"
# Legacy file storage (fallback)
messages_dir = "~/.local/share/opencode/storage/message"
export_dir = "./exports"

[ui]
table_style = "rich"
progress_bars = true
colors = true

[export]
default_format = "csv"
include_metadata = true

[models]
# Path to local models pricing configuration
config_file = "models.json"
# Remote pricing fallback from models.dev (disabled by default)
remote_fallback = false
remote_url = "https://models.dev/api.json"
remote_timeout_seconds = 8
remote_cache_ttl_hours = 24
```

**Configuration File Search Order:**
1. `~/.config/ocmonitor/config.toml` (recommended user location)
2. `config.toml` (current directory)
3. Project directory fallback

### Remote Pricing Fallback

OpenCode Monitor supports automatic pricing updates from [models.dev](https://models.dev), a community-maintained pricing database.

**Features:**
- Automatically fetches pricing for new models not in your local `models.json`
- Fill-only mode - never overwrites your local or user-defined prices
- Shared cache across all your projects (`~/.cache/ocmonitor/models_dev_api.json`)
- 24-hour TTL with stale cache fallback on errors
- Works offline using cached data

**Enable Remote Fallback:**
```toml
[models]
remote_fallback = true
```

**Use `--no-remote` to disable for a single run:**
```bash
# Force local-only pricing for this command
ocmonitor --no-remote sessions
```

**Pricing Precedence (highest to lowest):**
1. OpenCode's pre-computed cost (from session data, when available)
2. User override file (`~/.config/ocmonitor/models.json`)
3. Project/local `models.json`
4. models.dev remote fallback (fill-only)

## 🛠️ Development

### Prerequisites
- Python 3.8+
- pip package manager

### Setting Up Development Environment

The project uses `pyproject.toml` for modern Python packaging. You can install in development mode using either pip or pipx:

```bash
git clone https://github.com/Shlomob/ocmonitor-share.git
cd ocmonitor-share

# Using pip (editable install)
python3 -m pip install -e ".[dev]"

# Or using pipx (editable install)
pipx install -e ".[dev]"
```

**Install all extras for development:**
```bash
python3 -m pip install -e ".[dev,charts,export]"
```

### Running Tests
```bash
# Run all tests
pytest

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Legacy test scripts
python3 test_basic.py
python3 test_simple.py
```

### Project Architecture
```
ocmonitor/
├── ocmonitor/              # Core package
│   ├── cli.py             # Command-line interface
│   ├── config.py          # Configuration management
│   ├── models/            # Pydantic data models
│   │   ├── session.py     # Session and interaction models
│   │   └── workflow.py    # Workflow grouping models
│   ├── services/          # Business logic services
│   │   ├── agent_registry.py    # Agent type detection
│   │   ├── session_grouper.py   # Workflow grouping logic
│   │   ├── live_monitor.py      # Real-time monitoring
│   │   └── report_generator.py  # Report generation
│   ├── ui/                # Rich UI components
│   │   └── dashboard.py   # Live dashboard UI
│   └── utils/             # Utility functions
│       ├── data_loader.py # Unified data loading (SQLite/files)
│       ├── file_utils.py  # File processing
│       └── sqlite_utils.py # SQLite database access
├── config.toml            # User configuration
├── models.json            # AI model pricing data
└── test_sessions/         # Sample test data
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on:

- 🐛 Reporting bugs
- 💡 Suggesting features
- 🔧 Setting up development environment
- 📝 Code style and standards
- 🚀 Submitting pull requests

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🏆 Acknowledgments

- **[OpenCode](https://opencode.ai/)** - For creating an excellent AI coding agent that makes development more efficient
- **[ccusage](https://ccusage.com/)** - A similar monitoring tool for Claude Code that inspired features in this project
- **[Click](https://click.palletsprojects.com/)** - Excellent CLI framework
- **[Rich](https://github.com/Textualize/rich)** - Beautiful terminal formatting
- **[Pydantic](https://pydantic-docs.helpmanual.io/)** - Data validation and settings

## 🚀 Status

**🧪 Beta Testing** - This application is currently in beta testing phase. Please report any issues you encounter.


---

*Built with ❤️ for the OpenCode community*
