"""Gateway exceptions."""


class BrokerGatewayError(Exception):
    """Base class for gateway errors."""


class BrokerNotAvailable(BrokerGatewayError):
    """Requested broker adapter is missing or misconfigured."""


class BrokerCallFailed(BrokerGatewayError):
    """Broker API call failed."""
