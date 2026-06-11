"""Currency conversion utilities for OpenCode Monitor."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

# Currencies that use 0 decimal places
ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND"}


class CurrencyConverter:
    """Converter for currency display and conversion."""

    def __init__(
        self,
        code: str = "USD",
        symbol: str = "$",
        rate: Decimal = Decimal("1.0"),
        display_format: str = "symbol_prefix",
        decimals: Optional[int] = None,
    ):
        """Initialize currency converter.

        Args:
            code: ISO 4217 currency code (e.g., "USD", "GBP")
            symbol: Currency symbol (e.g., "$", "£")
            rate: Conversion rate from USD (e.g., 0.79 for GBP)
            display_format: "symbol_prefix" ($1.23) or "code_suffix" (1.23 USD)
            decimals: Number of decimal places (None for auto)
        """
        self.code = code.upper()
        self.symbol = symbol
        self.rate = rate
        self.display_format = display_format
        self.decimals = (
            decimals if decimals is not None else self._get_default_decimals()
        )

    @classmethod
    def from_config(cls, currency_config, resolved_rate: Optional[Decimal] = None):
        """Create a CurrencyConverter from config.

        Args:
            currency_config: CurrencyConfig instance
            resolved_rate: Optional resolved rate from remote fetcher

        Returns:
            CurrencyConverter instance
        """
        rate = resolved_rate if resolved_rate is not None else currency_config.rate
        return cls(
            code=currency_config.code,
            symbol=currency_config.symbol,
            rate=rate,
            display_format=currency_config.display_format,
            decimals=currency_config.decimals,
        )

    def _get_default_decimals(self) -> int:
        """Get default decimal places for the currency."""
        if self.code in ZERO_DECIMAL_CURRENCIES:
            return 0
        return 2

    def convert(self, usd_amount: Decimal) -> Decimal:
        """Convert USD amount to target currency.

        Args:
            usd_amount: Amount in USD

        Returns:
            Converted amount in target currency
        """
        return usd_amount * self.rate

    def format(self, usd_amount: Decimal) -> str:
        """Format USD amount for display in target currency.

        Args:
            usd_amount: Amount in USD

        Returns:
            Formatted string (e.g., "$1.23" or "1.23 GBP")
        """
        converted = self.convert(usd_amount)

        # Format with correct decimal places using proper rounding
        if self.decimals == 0:
            # Use ROUND_HALF_UP for proper financial rounding (not truncation)
            rounded = converted.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            formatted_amount = str(rounded)
        else:
            quantizer = Decimal(f"0.{'0' * self.decimals}")
            rounded = converted.quantize(quantizer, rounding=ROUND_HALF_UP)
            formatted_amount = str(rounded)

        if self.display_format == "code_suffix":
            return f"{formatted_amount} {self.code}"
        else:  # symbol_prefix
            return f"{self.symbol}{formatted_amount}"

    def __repr__(self) -> str:
        """Return debug representation with currency code, rate, and format."""
        return f"CurrencyConverter({self.code}, rate={self.rate}, format={self.display_format})"
