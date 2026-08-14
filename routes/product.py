"""Compatibility import for product-related code.

This module used to duplicate the Product model definition. Keeping a
single source of truth in models.product avoids mapper conflicts and
preserves backward compatibility for any legacy imports.
"""

from models.product import Product

__all__ = ["Product"]
