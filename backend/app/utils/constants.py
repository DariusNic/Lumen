SUPPORTED_CURRENCIES = ("RON", "EUR", "USD")
DEFAULT_BASE_CURRENCY = "RON"

CATEGORIES = (
    "Groceries", "Restaurants", "Transport", "Housing", "Utilities",
    "Health", "Entertainment", "Subscriptions", "Education", "Travel",
    "Salary", "Transfer", "Investments", "Goals", "Other",
)

SIGNAL_LABELS = ("BUY", "HOLD", "SELL")

CATEGORIZATION_CONFIDENCE_THRESHOLD = 0.65

# ----- Stock universe -------------------------------------------------------
# 100 S&P 500 large-caps with continuous price history from 2019-01 onward,
# selected for sector diversity. The list is fixed for reproducibility.
# Known limitation: no delisted names → survivorship bias in the training
# universe.
#
# Yahoo Finance ticker formats:
#   - Berkshire Hathaway B is "BRK-B" (Yahoo) — Excel/IEX use "BRK.B".
#     The fetcher uses Yahoo's canonical form everywhere.

TICKERS: tuple[str, ...] = (
    # Mega-cap tech (22)
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "CSCO", "AMD", "INTC", "TXN", "INTU", "IBM", "QCOM", "NOW",
    "AMAT", "ADI", "MU",
    # Healthcare (19)
    "LLY", "UNH", "JNJ", "MRK", "ABBV", "TMO", "ABT", "DHR", "AMGN", "BMY",
    "ELV", "ISRG", "GILD", "SYK", "VRTX", "REGN", "CI", "ZTS", "BSX",
    # Consumer (14)
    "WMT", "PG", "COST", "PEP", "KO", "MCD", "NKE", "PM", "MDLZ", "SBUX",
    "TJX", "MO", "LOW", "HD",
    # Finance (14)
    "JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "AXP", "BLK", "BX", "SCHW",
    "C", "SPGI", "PYPL",
    # Industrial (10) — HON replaces MMC: yfinance currently 404s on MMC
    # ("possibly delisted; no timezone found"), HON is a comparable mega-cap
    # diversified industrial with continuous 2019+ history.
    "RTX", "UPS", "CAT", "DE", "BA", "GE", "LMT", "HON", "ETN", "NSC",
    # Communication (5)
    "NFLX", "DIS", "CMCSA", "VZ", "T",
    # Energy (4)
    "XOM", "CVX", "COP", "EOG",
    # Utilities (3)
    "NEE", "SO", "DUK",
    # REITs (3)
    "PLD", "AMT", "EQIX",
    # Other large-caps (6)
    "BRK-B", "ACN", "ADP", "BKNG", "FCX", "LIN",
)
assert len(TICKERS) == 100, f"TICKERS list has {len(TICKERS)} entries, expected 100"

# History window for training (locked, do not change without sign-off).
TRAIN_DATA_START = "2019-01-01"

# Ticker → display name + sector. Used by `GET /api/stocks` for the Markets
# page and by the chatbot's `get_signal` tool when describing a ticker. Kept
# inline as a constant rather than fetched from yfinance to avoid a network
# call on every list request and to keep a stable reference table.
TICKER_META: dict[str, dict[str, str]] = {
    # Mega-cap tech
    "AAPL":  {"name": "Apple Inc.",                "sector": "Technology"},
    "MSFT":  {"name": "Microsoft Corp.",           "sector": "Technology"},
    "GOOGL": {"name": "Alphabet Inc.",             "sector": "Technology"},
    "AMZN":  {"name": "Amazon.com Inc.",           "sector": "Consumer Discretionary"},
    "NVDA":  {"name": "NVIDIA Corp.",              "sector": "Technology"},
    "META":  {"name": "Meta Platforms Inc.",       "sector": "Communication Services"},
    "TSLA":  {"name": "Tesla Inc.",                "sector": "Consumer Discretionary"},
    "AVGO":  {"name": "Broadcom Inc.",             "sector": "Technology"},
    "ORCL":  {"name": "Oracle Corp.",              "sector": "Technology"},
    "CRM":   {"name": "Salesforce Inc.",           "sector": "Technology"},
    "ADBE":  {"name": "Adobe Inc.",                "sector": "Technology"},
    "CSCO":  {"name": "Cisco Systems Inc.",        "sector": "Technology"},
    "AMD":   {"name": "Advanced Micro Devices",    "sector": "Technology"},
    "INTC":  {"name": "Intel Corp.",               "sector": "Technology"},
    "TXN":   {"name": "Texas Instruments Inc.",    "sector": "Technology"},
    "INTU":  {"name": "Intuit Inc.",               "sector": "Technology"},
    "IBM":   {"name": "International Business Machines", "sector": "Technology"},
    "QCOM":  {"name": "Qualcomm Inc.",             "sector": "Technology"},
    "NOW":   {"name": "ServiceNow Inc.",           "sector": "Technology"},
    "AMAT":  {"name": "Applied Materials Inc.",    "sector": "Technology"},
    "ADI":   {"name": "Analog Devices Inc.",       "sector": "Technology"},
    "MU":    {"name": "Micron Technology Inc.",    "sector": "Technology"},
    # Healthcare
    "LLY":   {"name": "Eli Lilly and Co.",         "sector": "Healthcare"},
    "UNH":   {"name": "UnitedHealth Group",        "sector": "Healthcare"},
    "JNJ":   {"name": "Johnson & Johnson",         "sector": "Healthcare"},
    "MRK":   {"name": "Merck & Co. Inc.",          "sector": "Healthcare"},
    "ABBV":  {"name": "AbbVie Inc.",               "sector": "Healthcare"},
    "TMO":   {"name": "Thermo Fisher Scientific",  "sector": "Healthcare"},
    "ABT":   {"name": "Abbott Laboratories",       "sector": "Healthcare"},
    "DHR":   {"name": "Danaher Corp.",             "sector": "Healthcare"},
    "AMGN":  {"name": "Amgen Inc.",                "sector": "Healthcare"},
    "BMY":   {"name": "Bristol-Myers Squibb",      "sector": "Healthcare"},
    "ELV":   {"name": "Elevance Health Inc.",      "sector": "Healthcare"},
    "ISRG":  {"name": "Intuitive Surgical Inc.",   "sector": "Healthcare"},
    "GILD":  {"name": "Gilead Sciences Inc.",      "sector": "Healthcare"},
    "SYK":   {"name": "Stryker Corp.",             "sector": "Healthcare"},
    "VRTX":  {"name": "Vertex Pharmaceuticals",    "sector": "Healthcare"},
    "REGN":  {"name": "Regeneron Pharmaceuticals", "sector": "Healthcare"},
    "CI":    {"name": "Cigna Group",               "sector": "Healthcare"},
    "ZTS":   {"name": "Zoetis Inc.",               "sector": "Healthcare"},
    "BSX":   {"name": "Boston Scientific Corp.",   "sector": "Healthcare"},
    # Consumer
    "WMT":   {"name": "Walmart Inc.",              "sector": "Consumer Staples"},
    "PG":    {"name": "Procter & Gamble Co.",      "sector": "Consumer Staples"},
    "COST":  {"name": "Costco Wholesale Corp.",    "sector": "Consumer Staples"},
    "PEP":   {"name": "PepsiCo Inc.",              "sector": "Consumer Staples"},
    "KO":    {"name": "Coca-Cola Co.",             "sector": "Consumer Staples"},
    "MCD":   {"name": "McDonald's Corp.",          "sector": "Consumer Discretionary"},
    "NKE":   {"name": "Nike Inc.",                 "sector": "Consumer Discretionary"},
    "PM":    {"name": "Philip Morris International", "sector": "Consumer Staples"},
    "MDLZ":  {"name": "Mondelez International",    "sector": "Consumer Staples"},
    "SBUX":  {"name": "Starbucks Corp.",           "sector": "Consumer Discretionary"},
    "TJX":   {"name": "TJX Companies Inc.",        "sector": "Consumer Discretionary"},
    "MO":    {"name": "Altria Group Inc.",         "sector": "Consumer Staples"},
    "LOW":   {"name": "Lowe's Companies Inc.",     "sector": "Consumer Discretionary"},
    "HD":    {"name": "Home Depot Inc.",           "sector": "Consumer Discretionary"},
    # Finance
    "JPM":   {"name": "JPMorgan Chase & Co.",      "sector": "Finance"},
    "V":     {"name": "Visa Inc.",                 "sector": "Finance"},
    "MA":    {"name": "Mastercard Inc.",           "sector": "Finance"},
    "BAC":   {"name": "Bank of America Corp.",     "sector": "Finance"},
    "WFC":   {"name": "Wells Fargo & Co.",         "sector": "Finance"},
    "MS":    {"name": "Morgan Stanley",            "sector": "Finance"},
    "GS":    {"name": "Goldman Sachs Group",       "sector": "Finance"},
    "AXP":   {"name": "American Express Co.",      "sector": "Finance"},
    "BLK":   {"name": "BlackRock Inc.",            "sector": "Finance"},
    "BX":    {"name": "Blackstone Inc.",           "sector": "Finance"},
    "SCHW":  {"name": "Charles Schwab Corp.",      "sector": "Finance"},
    "C":     {"name": "Citigroup Inc.",            "sector": "Finance"},
    "SPGI":  {"name": "S&P Global Inc.",           "sector": "Finance"},
    "PYPL":  {"name": "PayPal Holdings Inc.",      "sector": "Finance"},
    # Industrial
    "RTX":   {"name": "RTX Corp.",                 "sector": "Industrial"},
    "UPS":   {"name": "United Parcel Service",     "sector": "Industrial"},
    "CAT":   {"name": "Caterpillar Inc.",          "sector": "Industrial"},
    "DE":    {"name": "Deere & Co.",               "sector": "Industrial"},
    "BA":    {"name": "Boeing Co.",                "sector": "Industrial"},
    "GE":    {"name": "GE Aerospace",              "sector": "Industrial"},
    "LMT":   {"name": "Lockheed Martin Corp.",     "sector": "Industrial"},
    "HON":   {"name": "Honeywell International",   "sector": "Industrial"},
    "ETN":   {"name": "Eaton Corp.",               "sector": "Industrial"},
    "NSC":   {"name": "Norfolk Southern Corp.",    "sector": "Industrial"},
    # Communication
    "NFLX":  {"name": "Netflix Inc.",              "sector": "Communication Services"},
    "DIS":   {"name": "Walt Disney Co.",           "sector": "Communication Services"},
    "CMCSA": {"name": "Comcast Corp.",             "sector": "Communication Services"},
    "VZ":    {"name": "Verizon Communications",    "sector": "Communication Services"},
    "T":     {"name": "AT&T Inc.",                 "sector": "Communication Services"},
    # Energy
    "XOM":   {"name": "Exxon Mobil Corp.",         "sector": "Energy"},
    "CVX":   {"name": "Chevron Corp.",             "sector": "Energy"},
    "COP":   {"name": "ConocoPhillips",            "sector": "Energy"},
    "EOG":   {"name": "EOG Resources Inc.",        "sector": "Energy"},
    # Utilities
    "NEE":   {"name": "NextEra Energy Inc.",       "sector": "Utilities"},
    "SO":    {"name": "Southern Co.",              "sector": "Utilities"},
    "DUK":   {"name": "Duke Energy Corp.",         "sector": "Utilities"},
    # REITs
    "PLD":   {"name": "Prologis Inc.",             "sector": "Real Estate"},
    "AMT":   {"name": "American Tower Corp.",      "sector": "Real Estate"},
    "EQIX":  {"name": "Equinix Inc.",              "sector": "Real Estate"},
    # Other large-caps
    "BRK-B": {"name": "Berkshire Hathaway B",      "sector": "Finance"},
    "ACN":   {"name": "Accenture plc",             "sector": "Technology"},
    "ADP":   {"name": "Automatic Data Processing", "sector": "Industrial"},
    "BKNG":  {"name": "Booking Holdings Inc.",     "sector": "Consumer Discretionary"},
    "FCX":   {"name": "Freeport-McMoRan Inc.",     "sector": "Materials"},
    "LIN":   {"name": "Linde plc",                 "sector": "Materials"},
}
assert set(TICKER_META.keys()) == set(TICKERS), "TICKER_META keys must match TICKERS exactly"

# Paper-trading defaults
INITIAL_PORTFOLIO_CASH_USD: float = 10_000.0
