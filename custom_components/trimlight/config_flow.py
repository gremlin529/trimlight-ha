"""Adds a Trimlight controller (found on the network, or typed), or a group
of controllers in the same space."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import CONF_MEMBERS, CONF_TYPE, DOMAIN, TYPE_GROUP
from .group import is_group, member_ids
from .protocol import Trimlight, TrimlightError, discover

_LOGGER = logging.getLogger(__name__)


def _controllers(entries: list[ConfigEntry]) -> list[SelectOptionDict]:
    return [SelectOptionDict(value=e.entry_id, label=e.title) for e in entries if not is_group(e)]


def _members_selector(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST))


class TrimlightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: list[str] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GroupOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return is_group(config_entry)  # only a group has anything to change

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # A group needs controllers to put in it.
        if len(_controllers(self._async_current_entries())) < 2:
            return await self.async_step_controller()
        return self.async_show_menu(step_id="user", menu_options=["controller", "group"])

    # -------------------------------------------------------- controller

    async def _own_ipv4(self) -> list[str]:
        """Home Assistant's IPv4 addresses on its enabled network adapters
        (the source IP alone can be an IPv6 one)."""
        ips = []
        for adapter in await network.async_get_adapters(self.hass):
            if not adapter.get("enabled"):
                continue
            for ip in adapter.get("ipv4", []):
                address = ip.get("address")
                if address and not address.startswith("127.") and address not in ips:
                    ips.append(address)
        if not ips:
            source = await network.async_get_source_ip(self.hass)
            if source and ":" not in source:
                ips.append(source)
        return ips

    async def async_step_controller(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            try:
                info = await Trimlight(host).device_info()
            except TrimlightError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=info.name, data={CONF_HOST: host})

        if self._found is None:
            # The controllers have no discovery protocol: like the Trimlight
            # app, try their port on every address of this network.
            self._found = []
            try:
                configured = {e.data.get(CONF_HOST) for e in self._async_current_entries()}
                for own_ip in await self._own_ipv4():
                    found = await discover(own_ip)
                    _LOGGER.info("Trimlight scan of %s/24 found %s", own_ip, found or "nothing")
                    self._found += [h for h in found if h not in configured and h not in self._found]
            except Exception:  # noqa: BLE001 - a failed scan just means typing the address
                _LOGGER.exception("Trimlight network scan failed")

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._found[0] if self._found else ""): SelectSelector(
                    SelectSelectorConfig(options=self._found, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(
            step_id="controller",
            data_schema=schema,
            errors=errors,
            description_placeholders={"found": str(len(self._found))},
        )

    # ------------------------------------------------------------- group

    async def async_step_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        options = _controllers(self._async_current_entries())
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            members = user_input.get(CONF_MEMBERS, [])
            if not name:
                errors[CONF_NAME] = "name_required"
            elif len(members) < 2:
                errors[CONF_MEMBERS] = "two_members"
            else:
                return self.async_create_entry(
                    title=name, data={CONF_TYPE: TYPE_GROUP, CONF_MEMBERS: members}
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=(user_input or {}).get(CONF_NAME, "")): TextSelector(),
                vol.Required(CONF_MEMBERS, default=(user_input or {}).get(CONF_MEMBERS, [])): _members_selector(options),
            }
        )
        return self.async_show_form(step_id="group", data_schema=schema, errors=errors)


class GroupOptionsFlow(OptionsFlow):
    """Changes which controllers are in a group."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if len(user_input.get(CONF_MEMBERS, [])) < 2:
                errors[CONF_MEMBERS] = "two_members"
            else:
                return self.async_create_entry(data={CONF_MEMBERS: user_input[CONF_MEMBERS]})
        options = _controllers(self.hass.config_entries.async_entries(DOMAIN))
        current = [m for m in member_ids(self.config_entry) if any(o["value"] == m for o in options)]
        schema = vol.Schema({vol.Required(CONF_MEMBERS, default=current): _members_selector(options)})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
