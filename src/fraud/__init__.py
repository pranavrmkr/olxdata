"""
Fraud detection package for OLX listings.
"""

from .detector import FraudDetector, run_fraud_detection

__all__ = [
    "FraudDetector",
    "run_fraud_detection",
]