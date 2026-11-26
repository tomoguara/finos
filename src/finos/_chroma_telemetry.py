"""A product-telemetry client for Chroma that does nothing.

``finos.vectorstore`` points Chroma's ``chroma_product_telemetry_impl``
setting here, alongside ``anonymized_telemetry=False``. Chroma's default
client still calls into ``posthog`` when disabled, and with the installed
``posthog`` that call fails and logs an error to stderr, which would break
the CLI's one-line error contract. This client makes telemetry a no-op
whatever ``posthog`` version is installed. Only Chroma imports this module.
"""

from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoProductTelemetry(ProductTelemetryClient):
    """Drops every telemetry event."""

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return None
