"""Config flow for Robonomics Control integration. It is service module for HomeAssistant, 
which sets in `manifest.json`. This module allows to setup the integration from the web interface.
"""

from __future__ import annotations
from robonomicsinterface import Account, RWS
from substrateinterface.utils.ss58 import is_valid_ss58_address
from substrateinterface import KeypairType

import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from .exceptions import InvalidSubAdminSeed, InvalidSubOwnerAddress, NoSubscription, ControllerNotInDevices
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_PINATA_PUB,
    CONF_PINATA_SECRET,
    CONF_SUB_OWNER_ADDRESS,
    CONF_ADMIN_SEED,
    DOMAIN,
    CONF_SENDING_TIMEOUT,
    CONF_IPFS_GATEWAY,
    CONF_IPFS_GATEWAY_AUTH,
    CONF_WARN_DATA_SENDING,
    CONF_WARN_ACCOUNT_MANAGMENT,
    CONF_IPFS_GATEWAY_PORT,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADMIN_SEED): str,
        vol.Required(CONF_SUB_OWNER_ADDRESS): str,
        vol.Required(CONF_SENDING_TIMEOUT, default=10): int,
        vol.Optional(CONF_IPFS_GATEWAY): str,
        vol.Required(CONF_IPFS_GATEWAY_PORT, default=443): int,
        vol.Required(CONF_IPFS_GATEWAY_AUTH, default=False): bool,
        vol.Optional(CONF_PINATA_PUB): str,
        vol.Optional(CONF_PINATA_SECRET): str,
    }
)

STEP_WARN_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_WARN_DATA_SENDING): bool,
        vol.Required(CONF_WARN_ACCOUNT_MANAGMENT): bool,
    }
)


def _has_sub_owner_subscription(sub_owner_address: str) -> bool:
    """Check if controller account is in subscription devices

    :param sub_owner_address: Subscription owner address

    :return: True if ledger is not None, false otherwise
    """

    rws = RWS(Account())
    res = rws.get_ledger(sub_owner_address)
    if res is None:
        return False
    else:
        return True


def _is_sub_admin_in_subscription(sub_admin_seed: str, sub_owner_address: str) -> bool:
    """Check if controller account is in subscription devices

    :param sub_admin_seed: Controller's seed
    :param sub_owner_address: Subscription owner address

    :return: True if controller account is in subscription devices, false otherwise
    """

    rws = RWS(Account(sub_admin_seed, crypto_type=KeypairType.ED25519))
    res = rws.is_in_sub(sub_owner_address)
    return res


def _is_valid_sub_admin_seed(sub_admin_seed: str) -> Optional[ValueError]:
    """Check if provided controller seed is valid

    :param sub_admin_seed: Controller's seed
    """

    try:
        Account(sub_admin_seed)
    except Exception as e:
        return e


def _is_valid_sub_owner_address(sub_owner_address: str) -> bool:
    """Check if provided subscription owner address is valid

    :param sub_owner_address: Subscription owner address

    :return: True if address is valid, false otherwise
    """

    return is_valid_ss58_address(sub_owner_address, valid_ss58_format=32)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    :param hass: HomeAssistant instance
    :param data: dict with the keys from STEP_USER_DATA_SCHEMA and values provided by the user
    """

    if await hass.async_add_executor_job(_is_valid_sub_admin_seed, data[CONF_ADMIN_SEED]):
        raise InvalidSubAdminSeed
    if not _is_valid_sub_owner_address(data[CONF_SUB_OWNER_ADDRESS]):
        raise InvalidSubOwnerAddress
    if not _has_sub_owner_subscription(data[CONF_SUB_OWNER_ADDRESS]):
        raise NoSubscription
    if not _is_sub_admin_in_subscription(data[CONF_ADMIN_SEED], data[CONF_SUB_OWNER_ADDRESS]):
        raise ControllerNotInDevices

    return {"title": "Robonomics"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Robonomics Control."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""

        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step of the configuration. Contains user's warnings.

        :param user_input: Dict with the keys from STEP_WARN_DATA_SCHEMA and values provided by user

        :return: Service functions from HomeAssistant
        """

        errors = {}
        device_unique_id = "robonomics"
        await self.async_set_unique_id(device_unique_id)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_WARN_DATA_SCHEMA)
        else:
            if [x for x in user_input if not user_input[x]]:
                errors["base"] = "warnings"
                return self.async_show_form(step_id="user", data_schema=STEP_WARN_DATA_SCHEMA, errors=errors)
            return await self.async_step_conf()

    async def async_step_conf(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the second step of the configuration. Contains fields to provide credentials.
        :param: user_input: Dict with the keys from STEP_USER_DATA_SCHEMA and values provided by user

        :return: Service functions from HomeAssistant
        """

        self.updated_config = {}
        if user_input is None:
            return self.async_show_form(step_id="conf", data_schema=STEP_USER_DATA_SCHEMA)
        errors = {}
        try:
            info = await _validate_input(self.hass, user_input)
        except InvalidSubAdminSeed:
            errors["base"] = "invalid_sub_admin_seed"
        except InvalidSubOwnerAddress:
            errors["base"] = "invalid_sub_owner_address"
        except NoSubscription:
            errors["base"] = "has_no_subscription"
        except ControllerNotInDevices:
            errors["base"] = "is_not_in_devices"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(step_id="conf", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow. THis class contains methods to manage config after it was initialised."""

        self.config_entry = config_entry
        _LOGGER.debug(config_entry.data)
        self.updated_config = self.config_entry.data.copy()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage Timeout and Pinata and Custom IPFS gateways.

        :param user_input: Dict with the keys from OPTIONS_DATA_SCHEMA and values provided by user

        :return: Service functions from HomeAssistant
        """

        if user_input is not None:
            self.updated_config.update(user_input)

            self.hass.config_entries.async_update_entry(self.config_entry, data=self.updated_config)
            return self.async_create_entry(title="", data=user_input)

        if CONF_PINATA_PUB in self.config_entry.data:
            pinata_pub = self.config_entry.data[CONF_PINATA_PUB]
            pinata_secret = self.config_entry.data[CONF_PINATA_SECRET]
            if CONF_IPFS_GATEWAY in self.config_entry.data:
                custom_ipfs_gateway = self.config_entry.data[CONF_IPFS_GATEWAY]
                custom_ipfs_port = self.config_entry.data[CONF_IPFS_GATEWAY_PORT]
                custom_ipfs_gateway_auth = self.config_entry.data[CONF_IPFS_GATEWAY_AUTH]
                OPTIONS_DATA_SCHEMA = vol.Schema(
                    {
                        vol.Required(
                            CONF_SENDING_TIMEOUT,
                            default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                        ): int,
                        vol.Optional(CONF_PINATA_PUB, default=pinata_pub): str,
                        vol.Optional(CONF_PINATA_SECRET, default=pinata_secret): str,
                        vol.Optional(CONF_IPFS_GATEWAY, default=custom_ipfs_gateway): str,
                        vol.Required(CONF_IPFS_GATEWAY_PORT, default=custom_ipfs_port): int,
                        vol.Required(CONF_IPFS_GATEWAY_AUTH, default=custom_ipfs_gateway_auth): bool,
                    }
                )
            else:
                OPTIONS_DATA_SCHEMA = vol.Schema(
                    {
                        vol.Required(
                            CONF_SENDING_TIMEOUT,
                            default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                        ): int,
                        vol.Optional(CONF_PINATA_PUB, default=pinata_pub): str,
                        vol.Optional(CONF_PINATA_SECRET, default=pinata_secret): str,
                        vol.Optional(CONF_IPFS_GATEWAY): str,
                        vol.Required(CONF_IPFS_GATEWAY_PORT, default=443): int,
                        vol.Required(CONF_IPFS_GATEWAY_AUTH, default=False): bool,
                    }
                )
        else:
            if CONF_IPFS_GATEWAY in self.config_entry.data:
                custom_ipfs_gateway = self.config_entry.data[CONF_IPFS_GATEWAY]
                custom_ipfs_port = self.config_entry.data[CONF_IPFS_GATEWAY_PORT]
                custom_ipfs_gateway_auth = self.config_entry.data[CONF_IPFS_GATEWAY_AUTH]
                OPTIONS_DATA_SCHEMA = vol.Schema(
                    {
                        vol.Required(
                            CONF_SENDING_TIMEOUT,
                            default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                        ): int,
                        vol.Optional(CONF_PINATA_PUB): str,
                        vol.Optional(CONF_PINATA_SECRET): str,
                        vol.Optional(CONF_IPFS_GATEWAY, default=custom_ipfs_gateway): str,
                        vol.Required(CONF_IPFS_GATEWAY_PORT, default=custom_ipfs_port): int,
                        vol.Required(CONF_IPFS_GATEWAY_AUTH, default=custom_ipfs_gateway_auth): bool,
                    }
                )
            else:
                OPTIONS_DATA_SCHEMA = vol.Schema(
                    {
                        vol.Required(
                            CONF_SENDING_TIMEOUT,
                            default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                        ): int,
                        vol.Optional(CONF_PINATA_PUB): str,
                        vol.Optional(CONF_PINATA_SECRET): str,
                        vol.Optional(CONF_IPFS_GATEWAY): str,
                        vol.Required(CONF_IPFS_GATEWAY_PORT, default=443): int,
                        vol.Required(CONF_IPFS_GATEWAY_AUTH, default=False): bool,
                    }
                )

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_DATA_SCHEMA,
            last_step=False,
        )
