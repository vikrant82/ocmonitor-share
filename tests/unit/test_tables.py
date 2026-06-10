from decimal import Decimal
from unittest.mock import MagicMock

from ocmonitor.ui.tables import TableFormatter


def test_live_dashboard_parent_row_uses_session_total_tokens():
    formatter = TableFormatter()

    parent = MagicMock()
    parent.display_title = "Parent Session"
    parent.duration_percentage = 20.0
    parent.total_tokens.total = 150
    parent.calculate_total_cost.return_value = Decimal("1.00")

    sub_agent_a = MagicMock()
    sub_agent_a.display_title = "Sub A"
    sub_agent_a.total_tokens.total = 300
    sub_agent_a.calculate_total_cost.return_value = Decimal("2.00")

    sub_agent_b = MagicMock()
    sub_agent_b.display_title = "Sub B"
    sub_agent_b.total_tokens.total = 50
    sub_agent_b.calculate_total_cost.return_value = Decimal("0.50")

    hierarchy = {
        "root_sessions": [
            {
                "session": parent,
                "sub_agents": [sub_agent_a, sub_agent_b],
            }
        ]
    }

    table = formatter.create_live_dashboard_table(hierarchy, pricing_data={})

    # Token column (index 1) should show parent + all sub-agent tokens.
    assert table.columns[1]._cells[0] == "500"
    # Cost column (index 2) should show parent + all sub-agent cost.
    assert str(table.columns[2]._cells[0]) == "$3.50"


def test_live_dashboard_parent_row_with_no_sub_agents():
    formatter = TableFormatter()

    parent = MagicMock()
    parent.display_title = "Solo Parent"
    parent.duration_percentage = 20.0
    parent.total_tokens.total = 150
    parent.calculate_total_cost.return_value = Decimal("1.00")

    hierarchy = {
        "root_sessions": [
            {
                "session": parent,
                "sub_agents": [],
            }
        ]
    }

    table = formatter.create_live_dashboard_table(hierarchy, pricing_data={})

    assert table.columns[1]._cells[0] == "150"
    assert str(table.columns[2]._cells[0]) == "$1.00"


def test_live_dashboard_parent_row_with_null_sub_agents():
    formatter = TableFormatter()

    parent = MagicMock()
    parent.display_title = "Null Sub Parent"
    parent.duration_percentage = 20.0
    parent.total_tokens.total = 200
    parent.calculate_total_cost.return_value = Decimal("2.50")

    hierarchy = {
        "root_sessions": [
            {
                "session": parent,
                "sub_agents": None,
            }
        ]
    }

    table = formatter.create_live_dashboard_table(hierarchy, pricing_data={})

    assert table.columns[1]._cells[0] == "200"
    assert str(table.columns[2]._cells[0]) == "$2.50"


class TestCompactModelsDisplay:
    """Tests for TableFormatter._compact_models_display determinism and formatting."""

    def _fmt(self, models, max_groups=3):
        return TableFormatter._compact_models_display(models, max_groups=max_groups)

    def test_single_provider_single_model(self):
        assert self._fmt(["github-copilot/claude-sonnet-4.5"]) == "github-copilot/claude-sonnet-4.5"

    def test_single_bare_model(self):
        assert self._fmt(["unknown-model"]) == "unknown-model"

    def test_multi_model_same_provider(self):
        result = self._fmt(["prov/model-b", "prov/model-a"])
        assert result == "prov/{model-a, model-b}"

    def test_multi_provider_sorted_alphabetically(self):
        # Input order is z-first; output must be sorted by provider name.
        result = self._fmt(["z-prov/model-x", "a-prov/model-y"])
        assert result == "a-prov/model-y, z-prov/model-x"

    def test_bare_models_sorted_alphabetically(self):
        result = self._fmt(["zzz-bare", "aaa-bare"])
        assert result == "aaa-bare, zzz-bare"

    def test_mixed_provider_and_bare_sorted(self):
        # Provider entries come first (sorted), then bare entries (sorted).
        result = self._fmt(["bare-b", "z-prov/m1", "bare-a", "a-prov/m2"], max_groups=4)
        assert result == "a-prov/m2, z-prov/m1, bare-a, bare-b"

    def test_deterministic_regardless_of_input_order(self):
        models = ["prov-b/m2", "prov-a/m1", "prov-b/m1", "prov-a/m2"]
        import random
        shuffled = models[:]
        random.shuffle(shuffled)
        assert self._fmt(models) == self._fmt(shuffled) == "prov-a/{m1, m2}, prov-b/{m1, m2}"

    def test_truncation_with_plus_n_more(self):
        result = self._fmt(["a-prov/m1", "b-prov/m2", "c-prov/m3", "d-prov/m4"], max_groups=3)
        assert result == "a-prov/m1, b-prov/m2, c-prov/m3 (+1 more)"

    def test_deduplication(self):
        result = self._fmt(["prov/model-a", "prov/model-a", "prov/model-b"])
        assert result == "prov/{model-a, model-b}"

    def test_empty_list(self):
        assert self._fmt([]) == ""
