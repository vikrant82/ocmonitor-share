"""Unified data loader with SQLite preference and file fallback."""

from pathlib import Path
from typing import Dict, List, Optional, Any, Generator, Literal
from datetime import datetime

from ..models.session import SessionData
from ..models.tool_usage import ToolUsageStats
from .sqlite_utils import SQLiteProcessor
from .file_utils import FileProcessor


class DataSourceError(Exception):
    """Raised when no data source can be found."""
    pass


class DataLoader:
    """Unified data loader that prefers SQLite but falls back to file-based storage.
    
    This class provides a unified interface for loading OpenCode session data,
    automatically detecting and using the appropriate data source based on
    what's available.
    
    Priority:
        1. SQLite database (OpenCode v1.2.0+)
        2. File-based storage (legacy, for backwards compatibility)
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        files_path: Optional[Path] = None,
        force_source: Optional[Literal["sqlite", "files"]] = None
    ):
        """Initialize the data loader.
        
        Args:
            db_path: Custom path to SQLite database (uses default if not provided)
            files_path: Custom path to file-based storage (uses default if not provided)
            force_source: Force specific source ('sqlite' or 'files'), or None for auto
        """
        self._db_path = db_path
        self._files_path = files_path
        self._force_source = force_source
        self._last_source: Optional[str] = None
        
        # Resolve paths
        self._resolved_db_path = self._resolve_db_path()
        self._resolved_files_path = self._resolve_files_path()
    
    def _resolve_db_path(self) -> Optional[Path]:
        """Resolve the database path."""
        if self._db_path:
            return self._db_path
        return SQLiteProcessor.find_database_path()
    
    def _resolve_files_path(self) -> Optional[Path]:
        """Resolve the file-based storage path."""
        if self._files_path:
            return self._files_path
        
        # Try to get from FileProcessor
        storage_path = FileProcessor.get_opencode_storage_path()
        if storage_path:
            message_path = storage_path / "message"
            if message_path.exists():
                return message_path
        return None
    
    @property
    def sqlite_available(self) -> bool:
        """Check if SQLite database is available."""
        return self._resolved_db_path is not None and self._resolved_db_path.exists()
    
    @property
    def files_available(self) -> bool:
        """Check if file-based storage is available."""
        return self._resolved_files_path is not None and self._resolved_files_path.exists()
    
    @property
    def last_source(self) -> Optional[str]:
        """Get the data source used in the last operation."""
        return self._last_source
    
    def get_source_info(self) -> Dict[str, Any]:
        """Get information about available data sources.
        
        Returns:
            Dictionary with source availability and paths
        """
        return {
            'sqlite': {
                'available': self.sqlite_available,
                'path': str(self._resolved_db_path) if self._resolved_db_path else None
            },
            'files': {
                'available': self.files_available,
                'path': str(self._resolved_files_path) if self._resolved_files_path else None
            },
            'force_source': self._force_source,
            'last_used': self._last_source
        }
    
    def _determine_source(self) -> Literal["sqlite", "files"]:
        """Determine which data source to use.
        
        Returns:
            'sqlite' or 'files'
            
        Raises:
            DataSourceError: If no data source is available
        """
        # Check if source is forced
        if self._force_source:
            if self._force_source == "sqlite" and self.sqlite_available:
                return "sqlite"
            elif self._force_source == "files" and self.files_available:
                return "files"
            else:
                raise DataSourceError(
                    f"Forced source '{self._force_source}' is not available"
                )
        
        # Auto-detect: prefer SQLite
        if self.sqlite_available:
            return "sqlite"
        elif self.files_available:
            return "files"
        else:
            raise DataSourceError(
                "No session data found. "
                "Expected SQLite database at ~/.local/share/opencode/opencode.db "
                "or file storage at ~/.local/share/opencode/storage/message/"
            )
    
    def load_all_sessions(self, limit: Optional[int] = None) -> List[SessionData]:
        """Load all sessions from the preferred data source.
        
        Args:
            limit: Maximum number of sessions to load (None for all)
            
        Returns:
            List of SessionData objects
            
        Raises:
            DataSourceError: If no data source is available
        """
        source = self._determine_source()
        self._last_source = source
        
        if source == "sqlite":
            sessions = SQLiteProcessor.load_all_sessions(self._resolved_db_path, limit)
        else:
            sessions = FileProcessor.load_all_sessions(
                str(self._resolved_files_path), limit
            )
            # Tag sessions as coming from files
            for session in sessions:
                session.source = "files"
        
        return sessions
    
    def load_session_hierarchy(self) -> Dict[str, Any]:
        """Load sessions organized by parent-child hierarchy.
        
        Returns:
            Dictionary with:
                - 'root_sessions': List of parent sessions with sub_agents
                - 'all_sessions': Flat list of all sessions
                - 'source': 'sqlite' or 'files'
                
        Raises:
            DataSourceError: If no data source is available
        """
        source = self._determine_source()
        self._last_source = source
        
        if source == "sqlite":
            return SQLiteProcessor.load_session_hierarchy(self._resolved_db_path)
        else:
            # File-based: no hierarchy, all sessions are root level
            all_sessions = FileProcessor.load_all_sessions(
                str(self._resolved_files_path)
            )
            for session in all_sessions:
                session.source = "files"
            
            # Build flat hierarchy
            root_sessions = [
                {'session': session, 'sub_agents': []}
                for session in all_sessions
            ]
            
            return {
                'root_sessions': root_sessions,
                'all_sessions': all_sessions,
                'source': 'files'
            }
    
    def session_generator(self) -> Generator[SessionData, None, None]:
        """Generator that yields sessions one by one (memory efficient).
        
        Yields:
            SessionData objects
            
        Raises:
            DataSourceError: If no data source is available
        """
        source = self._determine_source()
        self._last_source = source
        
        if source == "sqlite":
            yield from SQLiteProcessor.session_generator(self._resolved_db_path)
        else:
            yield from FileProcessor.session_generator(str(self._resolved_files_path))
    
    def get_most_recent_session(self) -> Optional[SessionData]:
        """Get the most recent session.
        
        Returns:
            Most recent SessionData or None if no sessions found
        """
        sessions = self.load_all_sessions(limit=1)
        return sessions[0] if sessions else None
    
    def validate_data_source(self) -> bool:
        """Validate that at least one data source is available.
        
        Returns:
            True if a data source is available, False otherwise
        """
        try:
            self._determine_source()
            return True
        except DataSourceError:
            return False
    
    @classmethod
    def create_default(cls) -> "DataLoader":
        """Create a DataLoader with default paths.
        
        Returns:
            Configured DataLoader instance
        """
        return cls()
    
    def load_tool_usage(
        self,
        session_ids: List[str],
        preferred_source: Optional[Literal["sqlite", "files"]] = None,
    ) -> List[ToolUsageStats]:
        """Load tool usage statistics for the given sessions.
        
        For SQLite source, queries the `part` table for tool entries.
        For file-based source, returns empty list (not supported).
        
        Args:
            session_ids: List of session IDs to aggregate tool usage for
            preferred_source: Override source selection ("sqlite" or "files").
                If "files", returns [] even if SQLite is available.
                If "sqlite", queries SQLite if available, else returns [].
                If None, uses auto-detected source.
            
        Returns:
            List of ToolUsageStats sorted by total_calls descending
        """
        if not session_ids:
            return []
        
        # Handle explicit source override
        if preferred_source == "files":
            self._last_source = "files"
            return []
        
        if preferred_source == "sqlite":
            if self.sqlite_available:
                self._last_source = "sqlite"
                return SQLiteProcessor.load_tool_usage_for_sessions(
                    session_ids, self._resolved_db_path
                )
            self._last_source = None
            return []
        
        # Auto-detect source (original behavior)
        try:
            source = self._determine_source()
            self._last_source = source
        except DataSourceError:
            return []
        
        if source == "sqlite":
            return SQLiteProcessor.load_tool_usage_for_sessions(
                session_ids, self._resolved_db_path
            )
        
        return []
