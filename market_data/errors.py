class MarketDataError(Exception):
    """Base error for trusted market data failures."""


class MarketDataNetworkError(MarketDataError):
    pass


class MarketDataHTTPError(MarketDataError):
    pass


class MarketDataRateLimitError(MarketDataError):
    pass


class MarketDataJSONError(MarketDataError):
    pass


class MarketDataValidationError(MarketDataError):
    pass


class MarketDataExpiredError(MarketDataError):
    pass


class HistoricalDataError(MarketDataError):
    pass


class HistoricalDataValidationError(HistoricalDataError):
    pass


class HistoricalDataConflictError(HistoricalDataError):
    pass


class HistoricalDataIntegrityError(HistoricalDataError):
    pass
