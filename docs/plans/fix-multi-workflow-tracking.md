# Fix: Multi-Workflow Tracking for Live Dashboard

## Problem

When monitoring session A, then session B starts, the dashboard switches to B. If A continues, it never shows again - even after B closes.

## Root Cause

`LiveMonitor.start_sqlite_workflow_monitoring()` and `start_monitoring()` track only ONE workflow. When a new workflow is detected, they immediately switch without checking if the current workflow is still active.

## Solution: Track All Active Workflows

Maintain a list of active workflows and display the one with most recent activity.

## Implementation Tasks

### 1. Add `SQLiteProcessor.get_all_active_workflows()`
- [x] Create new method that returns all workflows where main session has no `end_time`
- [x] Order by most recent activity (latest file modification)
- [x] Return list of workflow dicts (same format as `get_most_recent_workflow`)

### 2. Modify `LiveMonitor.start_sqlite_workflow_monitoring()`
- [x] Change from single `current_workflow_id` to `active_workflows` list
- [x] On each refresh:
  - [x] Get all active workflows from SQLite
  - [x] Merge with current list (add new, remove ended)
  - [x] Display workflow with most recent activity
- [x] Track session IDs across all active workflows
- [x] Log when workflows are added/removed from tracking

### 3. Modify `LiveMonitor.start_monitoring()` (file-based)
- [x] Apply same multi-workflow logic
- [x] Filter `SessionGrouper.group_sessions()` results to active only

### 4. Add helper methods
- [x] `_select_most_recent_workflow()` - select workflow with most recent activity
- [x] `_select_most_recent_file_workflow()` - same for SessionWorkflow objects

### 5. Add tests
- [x] Test: multiple active workflows are tracked
- [x] Test: switching to most recently active workflow
- [x] Test: ended workflow is removed from tracking
- [x] Test: refresh updates tracked workflows

## Files to Modify

1. `ocmonitor/utils/sqlite_utils.py` - add `get_all_active_workflows()`
2. `ocmonitor/services/live_monitor.py` - modify both monitoring methods
3. `tests/unit/test_live_monitor.py` - add tests for new behavior

## Behavior After Fix

1. Session A starts → dashboard tracks A
2. Session B starts → dashboard tracks both A and B, shows most recently active
3. Session B closes → dashboard continues tracking A
4. Session A continues → dashboard shows A (most recently active)
