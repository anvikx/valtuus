from decimal import Decimal
from zoneinfo import ZoneInfo

MAX_QUERY_WORDS = 5
MIN_QUERY_LETTERS = 3
MAX_SEARCH_CANDIDATES = 40
SEARCH_CATEGORY_COUNT = 8
SEARCH_CATEGORY_EXAMPLES = 2
OFFER_TTL_MINUTES = 15
# Claude Code saves an MCP result over 50,000 characters to a file. A line is about 1,100
# characters and a rejected product about 300, so the full offer stays near 40,000.
MAX_OFFER_LINES = 30
MAX_REJECTED_SHOWN = 20
# A buyer chat with clarifying questions can take a while. Offers price live anyway.
SEARCH_SET_TTL_MINUTES = 60
DUPLICATE_WINDOW_MINUTES = 60
REJECT_MEMORY_MINUTES = 60
MAX_OVER_REQUEST_PERCENT = 10

# This amount or more means the count is not known.
UNKNOWN_STOCK_MARKER = 999_999

GATEWAY_TIMEZONE = ZoneInfo("Europe/Helsinki")
MONEY_DECIMALS = 2
CURRENCY = "EUR"
# The largest automatic limit the main user can set. More is a typo, not a kitchen order.
MAX_MANDATE_LIMIT = Decimal(1_000_000)
VALIO_CACHE_SECONDS = 60
# The mock blocks a caller for 30 seconds after a 429.
VALIO_COOLDOWN_SECONDS = 30
