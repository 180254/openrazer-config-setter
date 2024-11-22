#!/usr/bin/env python3
import argparse
import enum
import logging
import pathlib
import sys
import typing
from collections.abc import Callable

import openrazer.client
import openrazer.client.devices.mice


# The configuration I like to use.
class Config:
    # At least Razer DeathAdder V2 Pro (Wireless) capabilities are covered. (:
    # https://github.com/openrazer/openrazer/blob/v3.9.0/daemon/openrazer_daemon/hardware/mouse.py#L1238
    class Mouse:
        dpi = 1200
        poll_rate = 1000
        idle_time = 5 * 60
        low_battery_threshold = 10

        logo_brightness = 0.0
        logo_effect = "none"
        logo_effect_args = ()
        logo_effect_kwargs: typing.Final[dict] = {}


# helper for listing configurables
class UnreadableValueStrategy(enum.Enum):
    FALLBACK_TO_CONFIG = enum.auto()
    QUESTION_MARK = enum.auto()


class Mouse:
    def __init__(self, device: openrazer.client.devices.mice.RazerMouse) -> None:
        self.device = device

    def configurables_list(self, uvs: UnreadableValueStrategy) -> dict[str, object]:
        conf = {}

        def _with_getter(
            capability: str,
            getter: Callable[[openrazer.client.devices.mice.RazerMouse], object],
        ) -> object | None:
            if self.device.has(capability):
                return getter(self.device)
            return None

        def _with_getter_setter(
            capability: str,
            getter: Callable[[openrazer.client.devices.mice.RazerMouse], object],
            config_fallback: object,
        ) -> object | None:
            if self.device.has(f"get_{capability}"):
                return getter(self.device)
            if self.device.has(f"set_{capability}"):
                match uvs:
                    case UnreadableValueStrategy.FALLBACK_TO_CONFIG:
                        return config_fallback
                    case UnreadableValueStrategy.QUESTION_MARK:
                        return "?"
            return None

        conf["dpi"] = _with_getter(
            "dpi",
            lambda d: d.dpi,
        )
        conf["dpi_stages"] = _with_getter(
            "dpi_stages",
            lambda d: d.dpi_stages,
        )
        conf["poll_rate"] = _with_getter(
            "poll_rate",
            lambda d: d.poll_rate,
        )
        conf["idle_time"] = _with_getter_setter(
            "idle_time",
            lambda d: d.get_idle_time(),
            Config.Mouse.idle_time,
        )
        conf["low_battery_threshold"] = _with_getter_setter(
            "low_battery_threshold",
            lambda d: d.get_low_battery_threshold(),
            Config.Mouse.low_battery_threshold,
        )
        conf["logo_brightness"] = _with_getter(
            "lighting_logo",
            lambda d: d.fx.misc.logo.brightness,
        )
        conf["logo_effect"] = _with_getter(
            "lighting_logo",
            lambda d: d.fx.misc.logo.effect,
        )

        return conf

    def configurables_str(self, uvs: UnreadableValueStrategy) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.configurables_list(uvs).items())

    def configure(self) -> None:
        self.configure_dpi()
        self.configure_dpi_stages()
        self.configure_poll_rate()
        self.configure_idle_time()
        self.configure_low_battery_threshold()
        self.configure_logo()

    def configure_dpi(self) -> None:
        if not self.device.has("dpi"):
            return

        new_dpi = Config.Mouse.dpi

        if self.device.max_dpi is not None:
            new_dpi = min(self.device.max_dpi, Config.Mouse.dpi)

        if self.device.has("available_dpi"):
            available_dpis = self.device.available_dpi
            if available_dpis is not None and new_dpi not in available_dpis:
                new_dpi = min(available_dpis, key=lambda x: abs(x - Config.Mouse.dpi))

        if self.device.dpi != (new_dpi, new_dpi):
            self.device.dpi = (new_dpi, new_dpi)

    def configure_dpi_stages(self) -> None:
        if not self.device.has("dpi_stages"):
            return

        if self.device.dpi_stages != (1, [(Config.Mouse.dpi, Config.Mouse.dpi)]):
            self.device.dpi_stages = (1, [(Config.Mouse.dpi, Config.Mouse.dpi)])

    def configure_poll_rate(self) -> None:
        if not self.device.has("poll_rate"):
            return

        new_poll_rate = Config.Mouse.poll_rate

        if self.device.has("supported_poll_rates"):
            poll_rates = self.device.supported_poll_rates
            if poll_rates is not None and Config.Mouse.poll_rate not in poll_rates:
                new_poll_rate = min(
                    poll_rates, key=lambda x: abs(x - Config.Mouse.poll_rate)
                )

        if self.device.poll_rate != new_poll_rate:
            self.device.poll_rate = new_poll_rate

    def configure_idle_time(self) -> None:
        if not self.device.has("set_idle_time"):
            return

        if self.device.has("get_idle_time"):
            if self.device.get_idle_time() != Config.Mouse.idle_time:
                self.device.set_idle_time(Config.Mouse.idle_time)
        else:
            self.device.set_idle_time(Config.Mouse.idle_time)

    def configure_low_battery_threshold(self) -> None:
        if not self.device.has("set_low_battery_threshold"):
            return

        if self.device.has("get_low_battery_threshold"):
            if (
                self.device.get_low_battery_threshold()
                != Config.Mouse.low_battery_threshold
            ):
                self.device.set_low_battery_threshold(
                    Config.Mouse.low_battery_threshold
                )
        else:
            self.device.set_low_battery_threshold(Config.Mouse.low_battery_threshold)

    def configure_logo(self) -> None:
        if not self.device.has("lighting_logo"):
            return

        # https://github.com/openrazer/openrazer/blob/v3.9.0/examples/basic_effect.py#L13
        self.device.sync_effects = False

        if (
            self.device.has("lighting_logo_brightness")
            and self.device.fx.misc.logo.brightness != Config.Mouse.logo_brightness
        ):
            self.device.fx.misc.logo.brightness = Config.Mouse.logo_brightness

        if (
            self.device.has(f"lighting_logo_{Config.Mouse.logo_effect}")
            and self.device.fx.misc.logo.effect != Config.Mouse.logo_effect
        ):
            getattr(self.device.fx.misc.logo, Config.Mouse.logo_effect)(
                *Config.Mouse.logo_effect_args, **Config.Mouse.logo_effect_kwargs
            )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    args_parser = argparse.ArgumentParser(prog=pathlib.Path(__file__).name)
    args_parser.add_argument(
        "-d",
        "--dry",
        action="store_true",
        help="dry run: list devices only, will not reconfigure devices",
    )
    args = args_parser.parse_args()

    device_manager = openrazer.client.DeviceManager()

    for device in device_manager.devices:
        logging.info("%s", device.name)
        logging.info(
            "  type: %s, "
            "serial: %s, firmware version: %s, driver version: %s, "
            "battery level: %s, is charging: %s",
            device.type,
            device.serial,
            device.firmware_version,
            device.driver_version,
            device.battery_level,
            device.is_charging,
        )

        if device.type == "mouse":
            mouse = Mouse(device)

            configurables = mouse.configurables_str(
                UnreadableValueStrategy.QUESTION_MARK
            )
            logging.info("  configurables found: %s", configurables)

            if not args.dry:
                mouse.configure()

                configurables = mouse.configurables_str(
                    UnreadableValueStrategy.FALLBACK_TO_CONFIG
                )
                logging.info("  configurables now:   %s", configurables)

    return 0


if __name__ == "__main__":
    sys.exit(main())
