import os
import json
import time

os.makedirs(".opencode_sessions/mock-session", exist_ok=True)
with open(".opencode_sessions/mock-session/opencode_session_mock-session.json", "w") as f:
    json.dump({
        "timestamp": time.time() * 1000,
        "model": "claude-3-5-sonnet-20241022",
        "tokens": {
            "input": 100,
            "output": 200,
            "cache_write": 0,
            "cache_read": 0
        },
        "time_data": {
            "duration_ms": 1000
        }
    }, f)

print("Done")
