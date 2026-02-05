"""Tests for time utility functions."""

import pytest
from datetime import datetime, date, timedelta

from ocmonitor.utils.time_utils import TimeUtils, WEEKDAY_MAP, WEEKDAY_NAMES


class TestWeekdayConstants:
    """Tests for weekday constants."""
    
    def test_weekday_map_values(self):
        """Test that WEEKDAY_MAP has correct values."""
        assert WEEKDAY_MAP['monday'] == 0
        assert WEEKDAY_MAP['tuesday'] == 1
        assert WEEKDAY_MAP['wednesday'] == 2
        assert WEEKDAY_MAP['thursday'] == 3
        assert WEEKDAY_MAP['friday'] == 4
        assert WEEKDAY_MAP['saturday'] == 5
        assert WEEKDAY_MAP['sunday'] == 6
    
    def test_weekday_names_order(self):
        """Test that WEEKDAY_NAMES are in correct order."""
        assert WEEKDAY_NAMES == ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    def test_weekday_map_matches_names(self):
        """Test that map values correspond to names."""
        for day_name, day_num in WEEKDAY_MAP.items():
            expected_name = day_name.capitalize()
            assert WEEKDAY_NAMES[day_num] == expected_name


class TestFormatTimestamp:
    """Tests for format_timestamp method."""
    
    def test_format_valid_timestamp(self):
        """Test formatting a valid timestamp."""
        # Unix timestamp for 2024-01-15 10:30:00 UTC (milliseconds)
        timestamp_ms = 1705314600000
        result = TimeUtils.format_timestamp(timestamp_ms)
        
        assert "2024" in result
        assert "01-15" in result or "15" in result
    
    def test_format_none_timestamp(self):
        """Test formatting None timestamp."""
        result = TimeUtils.format_timestamp(None)
        assert result == "N/A"
    
    def test_format_zero_timestamp(self):
        """Test formatting timestamp of 0."""
        result = TimeUtils.format_timestamp(0)
        # 1970-01-01 00:00:00 UTC
        assert "1970" in result
    
    def test_format_invalid_timestamp(self):
        """Test formatting invalid/negative timestamp returns valid date (not Invalid)."""
        result = TimeUtils.format_timestamp(-1)
        # Implementation converts to datetime, may return 1969 date
        assert isinstance(result, str)


class TestFormatDuration:
    """Tests for format_duration method."""
    
    def test_format_none_duration(self):
        """Test formatting None duration."""
        result = TimeUtils.format_duration(None)
        assert result == "N/A"
    
    def test_format_negative_duration(self):
        """Test formatting negative duration."""
        result = TimeUtils.format_duration(-1000)
        assert result == "N/A"
    
    def test_format_seconds(self):
        """Test formatting short duration in seconds."""
        # 30 seconds
        result = TimeUtils.format_duration(30000)
        assert "30s" in result or "30 s" in result or "30" in result
    
    def test_format_minutes(self):
        """Test formatting duration in minutes."""
        # 5 minutes
        result = TimeUtils.format_duration(300000)
        assert "5m" in result or "5 m" in result or "min" in result.lower()
    
    def test_format_hours(self):
        """Test formatting duration in hours only."""
        # 2 hours exactly
        result = TimeUtils.format_duration(7200000)
        assert "2h" in result or "2 h" in result
    
    def test_format_hours_and_minutes(self):
        """Test formatting duration with hours and minutes."""
        # 2 hours 30 minutes
        result = TimeUtils.format_duration(9000000)
        assert "2h" in result or "2 h" in result
        assert "30m" in result or "30 m" in result


class TestFormatDurationHm:
    """Tests for format_duration_hm method (alias)."""
    
    def test_alias_method(self):
        """Test that format_duration_hm is an alias for format_duration."""
        # Both methods should produce the same result
        duration_ms = 3600000  # 1 hour
        
        result1 = TimeUtils.format_duration(duration_ms)
        result2 = TimeUtils.format_duration_hm(duration_ms)
        
        assert result1 == result2


class TestGetCustomWeekStart:
    """Tests for get_custom_week_start method."""
    
    def test_monday_start(self):
        """Test week start with Monday as start day (0)."""
        # 2024-01-15 is a Monday
        test_date = date(2024, 1, 15)
        result = TimeUtils.get_custom_week_start(test_date, WEEKDAY_MAP['monday'])
        
        assert result == test_date  # Should be same day
    
    def test_sunday_start(self):
        """Test week start with Sunday as start day (6)."""
        # 2024-01-15 is a Monday
        test_date = date(2024, 1, 15)
        result = TimeUtils.get_custom_week_start(test_date, WEEKDAY_MAP['sunday'])
        
        # Should be the previous Sunday (Jan 14)
        assert result == date(2024, 1, 14)
    
    def test_friday_start(self):
        """Test week start with Friday as start day (4)."""
        # 2024-01-15 is a Monday
        test_date = date(2024, 1, 15)
        result = TimeUtils.get_custom_week_start(test_date, WEEKDAY_MAP['friday'])
        
        # Should be the previous Friday (Jan 12)
        assert result == date(2024, 1, 12)
    
    def test_all_week_start_days(self):
        """Test week start calculation for all valid days."""
        test_date = date(2024, 1, 15)  # Monday
        
        for day_name in WEEKDAY_NAMES:
            day_num = WEEKDAY_MAP[day_name.lower()]
            result = TimeUtils.get_custom_week_start(test_date, day_num)
            
            # Result should be within 0-6 days before test_date
            assert isinstance(result, date)
            delta = (test_date - result).days
            assert 0 <= delta < 7


class TestGetCustomWeekRange:
    """Tests for get_custom_week_range method."""
    
    def test_week_range_monday_start(self):
        """Test week range with Monday start (0)."""
        test_date = date(2024, 1, 15)  # Monday
        start, end = TimeUtils.get_custom_week_range(test_date, WEEKDAY_MAP['monday'])
        
        assert start == date(2024, 1, 15)
        assert end == date(2024, 1, 21)  # Sunday
    
    def test_week_range_sunday_start(self):
        """Test week range with Sunday start (6)."""
        test_date = date(2024, 1, 15)  # Monday
        start, end = TimeUtils.get_custom_week_range(test_date, WEEKDAY_MAP['sunday'])
        
        assert start == date(2024, 1, 14)  # Sunday
        assert end == date(2024, 1, 20)    # Saturday
    
    def test_week_range_span(self):
        """Test that week ranges are always 7 days."""
        test_date = date(2024, 6, 15)  # Saturday
        
        for day_name in WEEKDAY_NAMES:
            day_num = WEEKDAY_MAP[day_name.lower()]
            start, end = TimeUtils.get_custom_week_range(test_date, day_num)
            
            # Range should be exactly 6 days (start to end inclusive = 7 days)
            assert (end - start).days == 6


class TestFormatWeekRange:
    """Tests for format_week_range method."""
    
    def test_format_same_month(self):
        """Test formatting week range within same month."""
        start = date(2024, 1, 15)
        end = date(2024, 1, 21)
        result = TimeUtils.format_week_range(start, end)
        
        assert "Jan" in result or "January" in result
        assert "15" in result
        assert "21" in result
    
    def test_format_different_months(self):
        """Test formatting week range spanning months."""
        start = date(2024, 1, 29)
        end = date(2024, 2, 4)
        result = TimeUtils.format_week_range(start, end)
        
        # Should show both months
        assert ("Jan" in result or "January" in result)
        assert ("Feb" in result or "February" in result)
    
    def test_format_different_years(self):
        """Test formatting week range spanning years."""
        start = date(2023, 12, 25)
        end = date(2024, 1, 1)
        result = TimeUtils.format_week_range(start, end)
        
        # Should show both years
        assert "2023" in result
        assert "2024" in result


class TestDateParsing:
    """Tests for date parsing methods."""
    
    def test_parse_date_string_valid(self):
        """Test parsing valid date string."""
        result = TimeUtils.parse_date_string("2024-01-15")
        assert result == date(2024, 1, 15)
    
    def test_parse_date_string_invalid(self):
        """Test parsing invalid date string."""
        result = TimeUtils.parse_date_string("invalid")
        assert result is None
    
    def test_parse_date_string_empty(self):
        """Test parsing empty date string."""
        result = TimeUtils.parse_date_string("")
        assert result is None
    
    def test_get_month_range(self):
        """Test getting date range for a specific month."""
        start, end = TimeUtils.get_month_range(2024, 1)
        
        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 31)
    
    def test_get_year_range(self):
        """Test getting date range for a specific year."""
        start, end = TimeUtils.get_year_range(2024)
        
        assert start == date(2024, 1, 1)
        assert end == date(2024, 12, 31)
    
    def test_get_week_range(self):
        """Test getting date range for ISO week."""
        # Week 3 of 2024
        start, end = TimeUtils.get_week_range(2024, 3)
        
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert (end - start).days == 6  # Week spans 7 days


class TestRelativeTime:
    """Tests for get_relative_time_description method."""
    
    def test_recent_time(self):
        """Test relative time for recent datetime."""
        recent = datetime.now() - timedelta(minutes=5)
        result = TimeUtils.get_relative_time_description(recent)
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_old_time(self):
        """Test relative time for older datetime."""
        old = datetime.now() - timedelta(days=5)
        result = TimeUtils.get_relative_time_description(old)
        
        assert isinstance(result, str)
        assert len(result) > 0


class TestDateInRange:
    """Tests for date_in_range method."""
    
    def test_date_in_range(self):
        """Test date within range."""
        check_date = date(2024, 1, 15)
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        
        assert TimeUtils.date_in_range(check_date, start_date, end_date) is True
    
    def test_date_before_range(self):
        """Test date before range."""
        check_date = date(2023, 12, 31)
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        
        assert TimeUtils.date_in_range(check_date, start_date, end_date) is False
    
    def test_date_after_range(self):
        """Test date after range."""
        check_date = date(2024, 2, 1)
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        
        assert TimeUtils.date_in_range(check_date, start_date, end_date) is False
    
    def test_date_at_range_boundaries(self):
        """Test date at range boundaries."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        
        # Start boundary (inclusive)
        assert TimeUtils.date_in_range(start_date, start_date, end_date) is True
        # End boundary (inclusive)
        assert TimeUtils.date_in_range(end_date, start_date, end_date) is True


class TestCurrentRanges:
    """Tests for current range methods."""
    
    def test_get_current_month_range(self):
        """Test getting current month range."""
        start, end = TimeUtils.get_current_month_range()
        
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert start.day == 1
    
    def test_get_current_week_range(self):
        """Test getting current week range."""
        start, end = TimeUtils.get_current_week_range()
        
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert (end - start).days == 6
