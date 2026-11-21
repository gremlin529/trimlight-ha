"""Adds a Trimlight controller: pick one found on the network, or type its address."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import network
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import DOMAIN
from .protocol import Trimlight, TrimlightError, discover

_LOGGER = logging.getLogger(__name__)


class TrimlightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: list[str] | None = None

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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"found": str(len(self._found))},
        )
