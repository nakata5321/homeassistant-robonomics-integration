"""Custom exceptions for the Robonomics integration."""
from homeassistant.exceptions import HomeAssistantError


class InvalidSubAdminSeed(HomeAssistantError):
    """Given sub admin seed is not correct"""


class InvalidSubOwnerAddress(HomeAssistantError):
    """Given subscription owner address is not correct"""


class NoSubscription(HomeAssistantError):
    """Given subscription owner address has no subscription"""


class ControllerNotInDevices(HomeAssistantError):
    """Account for given controller seed is not in subscription devices"""
