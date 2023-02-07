"""
Script for getting and sending data from Robonomics Integration.
Method `get_and_send_data` is imported to `__init__.py` to collect data with the configurated 
timeout and send it to Robonomics Network.
"""

from __future__ import annotations
from platform import platform

from homeassistant.core import HomeAssistant
from homeassistant.components.recorder import get_instance, history
from homeassistant.components.lovelace.const import DOMAIN as LOVELACE_DOMAIN
from homeassistant.helpers.service import async_get_all_descriptions

from substrateinterface import KeypairType
import asyncio
import logging
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from robonomicsinterface import Account
import typing as tp
import os
from datetime import timedelta, datetime

_LOGGER = logging.getLogger(__name__)

from .const import (
    CONF_ADMIN_SEED,
    DOMAIN,
    ROBONOMICS,
    DATA_CONFIG_PATH,
    DATA_PATH,
    IPFS_HASH_CONFIG,
    TWIN_ID,
)
from .utils import encrypt_message
from .ipfs import write_data_to_file, add_config_to_ipfs, add_telemetry_to_ipfs
import json


async def get_and_send_data(hass: HomeAssistant):
    """Collect data from all entities within 24hrs and send its hash to Robonomics Datalog.

    :param hass: HomeAssistant instance
    """

    try:
        _clear_files()
        sender_acc = Account(seed=hass.data[DOMAIN][CONF_ADMIN_SEED], crypto_type=KeypairType.ED25519)
        sender_kp = sender_acc.keypair
    except Exception as e:
        _LOGGER.error(f"Exception in create keypair during get and senf data: {e}")
    try:
        data_path = f"{os.path.expanduser('~')}/{DATA_PATH}"
        data = await _get_states(hass)
        data = json.dumps(data)
        # with open('/home/homeassistant/ha_test_data', 'w') as f:
        #     f.write(data)
        _LOGGER.debug(f"Got states to send datalog")
        encrypted_data = encrypt_message(str(data), sender_kp, sender_kp.public_key)
        await asyncio.sleep(2)
        filename = write_data_to_file(encrypted_data, data_path)
        ipfs_hash = await add_telemetry_to_ipfs(hass, filename)
        await hass.data[DOMAIN][ROBONOMICS].send_datalog_states(ipfs_hash)
    except Exception as e:
        _LOGGER.error(f"Exception in get_and_send_data: {e}")


def _state_changes_during_period(
    hass: HomeAssistant,
    start: datetime.datetime,
    end: datetime.datetime,
    entity_id: str,
) -> list[State]:
    """Save states of the given entity within 24hrs.

    :param hass: HomeAssistant instance
    :param start: Begin of the period
    :param end: End of the period
    :param entity_id: Id for entity from HomeAssistant

    :return: List of State within 24hrs
    """

    return history.state_changes_during_period(
        hass,
        start,
        end,
        entity_id,
        include_start_time_state=True,
        no_attributes=True,
    ).get(entity_id, [])


async def _get_state_history(hass: HomeAssistant, entity_id: str) -> tp.List[tp.Tuple[str, str]]:
    """Get 24 hours history for the given entity.

    :param hass: HomeAssistant instance
    :param entity_id: Id for entity from HomeAssistant

    :return: List of states with date for the given entity in the last 24hrs
    """

    start = datetime.now() - timedelta(hours=24)
    end = datetime.now()
    instance = get_instance(hass)
    states = await instance.async_add_executor_job(
        _state_changes_during_period,
        hass,
        start,
        end,
        entity_id,
    )
    states = states[1:]
    list_states = []
    for state in states:
        list_states.append({"state": state.state, "date": str(state.last_changed)})
    return list_states


async def _get_dashboard_and_services(hass: HomeAssistant) -> None:
    """Getting dashboard's configuration and list of services. If it was changed,
    set new topic in Digital Twin with IPFS hash of new dashboard's configuration.

    :param hass: HomeAssistant instance
    """

    _LOGGER.debug("Start getting info about dashboard and services")
    entity_registry = er.async_get(hass)
    try:
        descriptions = json.loads(json.dumps(await async_get_all_descriptions(hass)))
    except Exception as e:
        _LOGGER.error(f"Exception in getting descriptions: {e}")
    try:
        services_list = {}
        for entity in entity_registry.entities:
            entity_data = entity_registry.async_get(entity)
            platform = entity_data.entity_id.split(".")[0]
            if platform not in services_list and platform in descriptions:
                services_list[platform] = descriptions[platform]
        dashboard = hass.data[LOVELACE_DOMAIN]["dashboards"].get(None)
        config_dashboard = await dashboard.async_load(False)
    except Exception as e:
        _LOGGER.error(f"Exception in get services and dashboard: {e}")
    data_config_path = f"{os.path.expanduser('~')}/{DATA_CONFIG_PATH}"
    try:
        with open(f"{data_config_path}/config", "r") as f:
            current_config = json.load(f)
    except Exception as e:
        _LOGGER.error(f"Exception in json load config: {e}")
        current_config = {}
    try:
        new_config = {
            "services": services_list,
            "dashboard": config_dashboard,
            "twin_id": hass.data[DOMAIN][TWIN_ID],
        }
        if current_config != new_config or IPFS_HASH_CONFIG not in hass.data[DOMAIN]:
            if current_config != new_config:
                _LOGGER.debug("Config was changed")
                with open(f"{data_config_path}/config", "w") as f:
                    json.dump(new_config, f)
                sender_acc = Account(
                    seed=hass.data[DOMAIN][CONF_ADMIN_SEED],
                    crypto_type=KeypairType.ED25519,
                )
                sender_kp = sender_acc.keypair
                encrypted_data = encrypt_message(str(new_config), sender_kp, sender_kp.public_key)
            else:
                list_files = os.listdir(data_config_path)
                for name_file in list_files:
                    if "config_encrypted" in name_file:
                        encrypted_config_filename = name_file
                with open(f"{data_config_path}/{encrypted_config_filename}") as f:
                    encrypted_data = f.read()
            filename = write_data_to_file(encrypted_data, data_config_path, config=True)
            _LOGGER.debug(f"Filename: {filename}")
            hass.data[DOMAIN][IPFS_HASH_CONFIG] = await add_config_to_ipfs(hass, filename)
            _LOGGER.debug(f"New config IPFS hash: {hass.data[DOMAIN][IPFS_HASH_CONFIG]}")
            await hass.data[DOMAIN][ROBONOMICS].set_config_topic(
                hass.data[DOMAIN][IPFS_HASH_CONFIG], hass.data[DOMAIN][TWIN_ID]
            )
    except Exception as e:
        _LOGGER.error(f"Exception in change config: {e}")


async def _get_states(
    hass: HomeAssistant,
) -> tp.Dict[str, tp.Dict[str, tp.Union[str, tp.Dict[str, tp.Dict[str, tp.Union[str, float]]]]],]:
    """Get info about all entities within 24hrs

    :param hass: HomeAssistant instance

    :return: Dict with the history within 24hrs
    """

    await _get_dashboard_and_services(hass)
    registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    devices_data = {}
    data = {}

    for entity in entity_registry.entities:
        entity_data = entity_registry.async_get(entity)
        if entity_data.device_id != None:
            entity_state = hass.states.get(entity)
            if entity_state != None:
                try:
                    units = str(entity_state.attributes.get("unit_of_measurement"))
                except:
                    units = "None"
                history = await _get_state_history(hass, entity_data.entity_id)
                entity_info = {
                    "units": units,
                    "state": str(entity_state.state),
                    "history": history,
                }
                if entity_data.device_id not in devices_data:
                    device = registry.async_get(entity_data.device_id)
                    device_name = str(device.name_by_user) if device.name_by_user != None else str(device.name)
                    devices_data[entity_data.device_id] = {
                        "name": device_name,
                        "entities": {entity_data.entity_id: entity_info},
                    }
                else:
                    devices_data[entity_data.device_id]["entities"][entity_data.entity_id] = entity_info
    devices_data["twin_id"] = hass.data[DOMAIN][TWIN_ID]
    return devices_data


def _clear_files():
    """Remove files with telemetry."""

    data_path = f"{os.path.expanduser('~')}/{DATA_PATH}"
    files = os.listdir(data_path)
    for datafile in files:
        if datafile[:4] == "data":
            os.remove(f"{data_path}/{datafile}")
