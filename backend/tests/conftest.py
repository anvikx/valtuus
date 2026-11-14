import os

# Tests never read the real key from .env. app.main builds the app at import time, so the
# value must be set before any test module imports it.
os.environ["AGENT_KEY"] = "test-agent-key-0123456789"
