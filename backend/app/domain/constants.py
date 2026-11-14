from decimal import Decimal
from zoneinfo import ZoneInfo

MAX_SEARCH_CANDIDATES = 25
MAX_OFFER_CANDIDATES = 25
MAX_SEARCH_OPTIONS = 4
OFFER_TTL_MINUTES = 15
DUPLICATE_WINDOW_MINUTES = 60
REJECT_MEMORY_MINUTES = 60
MAX_OVER_REQUEST_PERCENT = 10

# The mock's stock markers: the first means "no limit", the second "amount not known".
UNLIMITED_STOCK_MARKER = 9_999_999_999
UNKNOWN_STOCK_MARKER = 999_999

GATEWAY_TIMEZONE = ZoneInfo("Europe/Helsinki")
MONEY_DECIMALS = 2
CURRENCY = "EUR"
# The largest automatic limit the main user can set. More is a typo, not a kitchen order.
MAX_MANDATE_LIMIT = Decimal(1_000_000)
VALIO_CACHE_SECONDS = 60
# The mock blocks a caller for 30 seconds after a 429.
VALIO_COOLDOWN_SECONDS = 30
