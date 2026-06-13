#! /usr/bin/python3

import logging
import paho.mqtt.client as mqtt
import configparser
import copy
import json
import time
import datetime
import re
import sys
import traceback
import signal
from typing import Any


# Define user-defined exception
class AppError(Exception):
    "Raised on application error"

    pass


class MqttError(Exception):
    "Raised on MQTT connection failure"

    pass


# Setup logging
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Explicitly handle termination signals to allow graceful shutdown
def handle_termination_signal(signum: int, frame: Any) -> None:
    logger.error(f"Received signal {signum}, requesting graceful shutdown")
    raise SystemExit(0)


signal.signal(signal.SIGTERM, handle_termination_signal)
signal.signal(signal.SIGINT, handle_termination_signal)


# global variables
cards = {}
tele = {}
cache = [{}, {}, {}, {}, {}, {}, {}, {}]
defaults = {
    "megaind": {
        "response": {
            "0_10": [0, 0, 0, 0],
            "4_20": [0, 0, 0, 0],
            "pwm": [0, 0, 0, 0],
            "led": [0, 0, 0, 0],
            "opto_edge": [0, 0, 0, 0],
            "opto_rst": [0, 0, 0, 0],
        },
        "input": {
            "0_10": [0, 0, 0, 0],
            "pm0_10": [0, 0, 0, 0],
            "4_20": [0, 0, 0, 0],
            "opto": [0, 0, 0, 0],
            "opto_count": [0, 0, 0, 0],
        },
    },
    "megabas": {
        "response": {
            "0_10": [0, 0, 0, 0],
            "triac": [0, 0, 0, 0],
            "cont_edge": [0, 0, 0, 0, 0, 0, 0, 0],
            "cont_rst": [0, 0, 0, 0, 0, 0, 0, 0],
        },
        "input": {
            "0_10": [0, 0, 0, 0, 0, 0, 0, 0],
            "1k": [0, 0, 0, 0, 0, 0, 0, 0],
            "10k": [0, 0, 0, 0, 0, 0, 0, 0],
            "cont": [0, 0, 0, 0, 0, 0, 0, 0],
            "cont_count": [0, 0, 0, 0, 0, 0, 0, 0],
        },
    },
    "8relind": {"response": {"relay": [0, 0, 0, 0, 0, 0, 0, 0]}},
    "8inputs": {"input": {"opto": [0, 0, 0, 0, 0, 0, 0, 0]}},
    "16inpind": {
        "response": {
            "opto_edge": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "opto_rst": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        },
        "input": {
            "opto": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "opto_count": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        },
    },
    "rtd": {"input": {"rtd": [0, 0, 0, 0, 0, 0, 0, 0]}},
}

# read config
config = configparser.ConfigParser()
config.read("config.ini")

if "LOGGING" in config:
    if "LEVEL" in config["LOGGING"] and config["LOGGING"]["LEVEL"]:
        log_level = config["LOGGING"]["LEVEL"].upper()
        if log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            logger.setLevel(getattr(logging, log_level))
        else:
            raise AppError("Invalid logging level " + config["LOGGING"]["LEVEL"])

if "MQTT" in config:
    for key in [
        "TOPIC",
        "SERVER",
        "PORT",
        "QOS",
        "TIMEOUT",
        "USER",
        "PASS",
        "BIRTH_TOPIC",
    ]:
        if not config["MQTT"][key]:
            raise AppError("Missing or empty config entry MQTT/" + key)
else:
    raise AppError("Missing config section MQTT")

if "CARDS" in config:
    for key in config["CARDS"]:
        if config["CARDS"][key]:
            match = re.match(r"^STACK([0-7])$", key, re.IGNORECASE)
            if match:
                cards[int(match.group(1))] = config["CARDS"][key]
    if not len(cards):
        raise AppError("Missing config section CARDS")
else:
    raise AppError("Missing config section CARDS")

if "WATCHDOG" in config:
    for key in ["TIMEOUT", "BOOT", "RESET"]:
        if not config["WATCHDOG"][key]:
            raise AppError("Missing or empty config entry WATCHDOG/" + key)
else:
    raise AppError("Missing config section WATCHDOG")

if "HEARTBEAT" in config:
    for key in ["TIMEOUT", "TOPIC_CHALLENGE", "TOPIC_RESPONSE"]:
        if not config["HEARTBEAT"][key]:
            raise AppError("Missing or empty config entry HEARTBEAT/" + key)
else:
    raise AppError("Missing config section HEARTBEAT")

if "RUNTIME" in config:
    for key in ["MAX_ERROR", "RESTART_DELAY", "TELE_INTERVAL"]:
        if not config["RUNTIME"][key]:
            logger.error("Missing or empty config entry RUNTIME/" + key)
            raise AppError("Missing or empty config entry RUNTIME/" + key)
else:
    logger.error("Missing config section RUNTIME")
    raise AppError("Missing config section RUNTIME")


for stack in cards.keys():
    if cards[stack] == "megaind":
        try:
            import megaind
        except ImportError:
            raise AppError("Can't import megaind library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["megaind"])
    elif cards[stack] == "megabas":
        try:
            import megabas
        except ImportError:
            raise AppError("Can't import megabas library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["megabas"])
    elif cards[stack] == "8relind":
        try:
            import lib8relind
        except ImportError:
            raise AppError("Can't import lib8relind library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["8relind"])
    elif cards[stack] == "8inputs":
        try:
            import lib8inputs
        except ImportError:
            raise AppError("Can't import lib8inputs library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["8inputs"])
    elif cards[stack] == "16inpind":
        try:
            import lib16inpind
        except ImportError:
            raise AppError("Can't import lib16inpind library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["16inpind"])
    elif cards[stack] == "rtd":
        try:
            import librtd
        except ImportError:
            raise AppError("Can't import librtd library, is it installed?")
        else:
            cache[stack] = copy.deepcopy(defaults["rtd"])
    else:
        logger.error("Unknown card type " + cards[stack])
        raise AppError("Unknown card type " + cards[stack])


def get_megaind(stack: int, init: int) -> None:
    for channel in range(1, 5):
        value = megaind.get0_10Out(stack, channel)
        if init or value != cache[stack]["response"]["0_10"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/0_10/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["0_10"][channel - 1] = value

        value = megaind.get4_20Out(stack, channel)
        if init or value != cache[stack]["response"]["4_20"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/4_20/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["4_20"][channel - 1] = value

        value = megaind.getOdPWM(stack, channel)
        if init or value != cache[stack]["response"]["pwm"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/pwm/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["pwm"][channel - 1] = value

        value = megaind.getLed(stack, channel)
        if init or value != cache[stack]["response"]["led"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/led/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["led"][channel - 1] = value

        value = megaind.getOptoRisingCountEnable(stack, channel)
        if init or value != cache[stack]["response"]["opto_edge"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/opto_edge/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["opto_edge"][channel - 1] = value

        value = 0
        if init or value != cache[stack]["response"]["opto_rst"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/response/opto_rst/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["opto_rst"][channel - 1] = value

        value = round(megaind.get0_10In(stack, channel), 2)
        if init or value != cache[stack]["input"]["0_10"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/input/0_10/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["0_10"][channel - 1] = value

        value = round(megaind.getpm10In(stack, channel), 2)
        if init or value != cache[stack]["input"]["pm0_10"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/input/pm0_10/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["pm0_10"][channel - 1] = value

        value = megaind.get4_20In(stack, channel)
        if init or value != cache[stack]["input"]["4_20"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/input/4_20/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["4_20"][channel - 1] = value

        value = megaind.getOptoCh(stack, channel)
        if init or value != cache[stack]["input"]["opto"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/input/opto/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["opto"][channel - 1] = value

        value = megaind.getOptoCount(stack, channel)
        if init or value != cache[stack]["input"]["opto_count"][channel - 1]:
            mqtt_publish(
                "megaind/" + str(stack) + "/input/opto_count/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["opto_count"][channel - 1] = value


def set_megaind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "0_10" and 1 <= channel <= 4 and 0 <= value <= 10:
        logger.debug(
            "Setting megaind stack: %s, response: 0_10, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megaind.set0_10Out(stack, channel, value)
        value = megaind.get0_10Out(stack, channel)
        mqtt_publish(
            "megaind/" + str(stack) + "/response/0_10/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["0_10"][channel - 1] = value
    elif output == "4_20" and 1 <= channel <= 4 and 4 <= value <= 20:
        logger.debug(
            "Setting megaind stack: %s, response: 4_20, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megaind.set4_20Out(stack, channel, value)
        value = megaind.get4_20Out(stack, channel)
        mqtt_publish(
            "megaind/" + str(stack) + "/response/4_20/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["4_20"][channel - 1] = value
    elif output == "pwm" and 1 <= channel <= 4 and 0 <= value <= 100:
        logger.debug(
            "Setting megaind stack: %s, response: pwm, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megaind.setOdPWM(stack, channel, value)
        value = megaind.getOdPWM(stack, channel)
        mqtt_publish(
            "megaind/" + str(stack) + "/response/pwm/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["pwm"][channel - 1] = value
    elif output == "led" and 1 <= channel <= 4 and value in [0, 1]:
        logger.debug(
            "Setting megaind stack: %s, response: led, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megaind.setLed(stack, channel, value)
        value = megaind.getLed(stack, channel)
        mqtt_publish(
            "megaind/" + str(stack) + "/response/led/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["led"][channel - 1] = value
    elif output == "opto_edge" and 1 <= channel <= 4 and value in [0, 1, 2, 3]:
        logger.debug(
            "Setting megaind stack: %s, response: opto_edge, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        rce = (value >> 0) & 1
        fce = (value >> 1) & 1
        megaind.setOptoRisingCountEnable(stack, channel, rce)
        megaind.setOptoFallingCountEnable(stack, channel, fce)
        rce = megaind.getOptoRisingCountEnable(stack, channel)
        fce = megaind.getOptoFallingCountEnable(stack, channel)
        value = (rce << 0) | (fce << 1)
        mqtt_publish(
            "megaind/" + str(stack) + "/response/opto_edge/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["opto_edge"][channel - 1] = value
    elif output == "opto_rst" and 1 <= channel <= 4 and value in [0, 1]:
        logger.debug(
            "Setting megaind stack: %s, response: opto_rst, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        if value == 1:
            megaind.rstOptoCount(stack, channel)
            value = megaind.getOptoCount(stack, channel)
            mqtt_publish(
                "megaind/" + str(stack) + "/response/opto_rst/" + str(channel),
                payload=1,
            )
            mqtt_publish(
                "megaind/" + str(stack) + "/input/opto_count/" + str(channel),
                payload=str(value),
            )
        mqtt_publish(
            "megaind/" + str(stack) + "/response/opto_rst/" + str(channel),
            payload=0,
        )
        cache[stack]["input"]["opto_count"][channel - 1] = value
    else:
        logger.error(
            "Can't set megaind stack: "
            + str(stack)
            + ", topic: "
            + output
            + ", channel: "
            + str(channel)
            + " to value: "
            + str(value)
        )


def reset_megaind(stack: int) -> None:
    for output in defaults["megaind"]["response"].keys():
        for channel in defaults["megaind"]["response"][output].keys():
            set_megaind(
                stack, output, channel, defaults["megaind"]["response"][output][channel]
            )


def tele_megaind(stack: int) -> bool:
    if megaind.getPowerVolt(stack) < 5:
        return False
    tele["master"] = "megaind" + str(stack)
    tele["fw"] = megaind.getFwVer(stack)
    tele["power_in"] = megaind.getPowerVolt(stack)
    tele["power_rsp"] = megaind.getRaspVolt(stack)
    tele["cpu_temp"] = megaind.getCpuTemp(stack)
    tele["wtd_resets"] = megaind.wdtGetResetCount(stack)
    return True


def watchdog_megaind(stack: int, mode: int) -> bool:
    if megaind.getPowerVolt(stack) < 5:
        return False
    if mode == 1:
        if megaind.wdtGetPeriod(stack) != int(config["WATCHDOG"]["TIMEOUT"]):
            logger.debug(
                "Setting megaind watchdog period: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["TIMEOUT"],
            )
            megaind.wdtSetPeriod(stack, int(config["WATCHDOG"]["TIMEOUT"]))
        if megaind.wdtGetDefaultPeriod(stack) != int(config["WATCHDOG"]["BOOT"]):
            logger.debug(
                "Setting megaind watchdog default period: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["BOOT"],
            )
            megaind.wdtSetDefaultPeriod(stack, int(config["WATCHDOG"]["BOOT"]))
        if megaind.wdtGetOffInterval(stack) != int(config["WATCHDOG"]["RESET"]):
            logger.debug(
                "Setting megaind watchdog off interval: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["RESET"],
            )
            megaind.wdtSetOffInterval(stack, int(config["WATCHDOG"]["RESET"]))
    elif mode == 2:
        logger.debug("Disabling megaind watchdog: stack=%s", stack)
        megaind.wdtSetPeriod(stack, 65000)
    else:
        logger.debug("Reloading megaind watchdog: stack=%s", stack)
        megaind.wdtReload(stack)
    return True


def get_megabas(stack: int, init: int) -> None:
    triacs = megabas.getTriacs(stack)
    for channel in range(1, 5):
        value = megabas.getUOut(stack, channel)
        if init or value != cache[stack]["response"]["0_10"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/response/0_10/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["0_10"][channel - 1] = value

        if triacs & (1 << channel - 1):
            value = 1
        else:
            value = 0
        if init or value != cache[stack]["response"]["triac"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/response/triac/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["triac"][channel - 1] = value

    for channel in range(1, 9):
        value = round(megabas.getUIn(stack, channel), 2)
        if init or value != cache[stack]["input"]["0_10"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/input/0_10/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["0_10"][channel - 1] = value

        value = round(megabas.getRIn1K(stack, channel), 2)
        if init or value != cache[stack]["input"]["1k"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/input/1k/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["1k"][channel - 1] = value

        value = round(megabas.getRIn10K(stack, channel), 2)
        if init or value != cache[stack]["input"]["10k"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/input/10k/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["10k"][channel - 1] = value

        value = megabas.getContactCh(stack, channel)
        if init or value != cache[stack]["input"]["cont"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/input/cont/" + str(channel),
                str(value),
            )
            cache[stack]["input"]["cont"][channel - 1] = value

        value = megabas.getContactCounter(stack, channel)
        if init or value != cache[stack]["input"]["cont_count"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/input/cont_count/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["cont_count"][channel - 1] = value

        value = megabas.getContactCountEdge(stack, channel)
        if init or value != cache[stack]["response"]["cont_edge"][channel - 1]:
            mqtt_publish(
                "megabas/" + str(stack) + "/response/cont_edge/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["cont_edge"][channel - 1] = value

    megabas.getTriacs(stack)


def set_megabas(stack: int, output: str, channel: int, value: int) -> None:
    if output == "0_10" and 1 <= channel <= 4 and 0 <= value <= 10:
        logger.debug(
            "Setting megabas stack: %s, response: 0_10, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megabas.setUOut(stack, channel, value)
        value = megabas.getUOut(stack, channel)
        mqtt_publish(
            "megabas/" + str(stack) + "/response/0_10/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["0_10"][channel - 1] = value
    elif output == "triac" and 1 <= channel <= 4 and value in [0, 1]:
        logger.debug(
            "Setting megabas stack: %s, response: triac, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megabas.setTriac(stack, channel, value)
        triacs = megabas.getTriacs(stack)
        if triacs & (1 << channel - 1):
            value = 1
        else:
            value = 0
        mqtt_publish(
            "megabas/" + str(stack) + "/response/triac/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["triac"][channel - 1] = value
    elif output == "cont_edge" and 1 <= channel <= 8 and value in [0, 1, 2, 3]:
        logger.debug(
            "Setting megabas stack: %s, response: cont_edge, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        megabas.setContactCountEdge(stack, channel, value)
        value = megabas.getContactCountEdge(stack, channel)
        mqtt_publish(
            "megabas/" + str(stack) + "/response/cont_edge/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["cont_edge"][channel - 1] = value
    else:
        logger.error(
            "Can't set megabas stack: "
            + str(stack)
            + ", response: "
            + output
            + ", channel: "
            + str(channel)
            + " to value: "
            + str(value)
        )


def reset_megabas(stack: int) -> None:
    for output in defaults["megabas"]["response"].keys():
        for channel in defaults["megabas"]["response"][output].keys():
            set_megabas(
                stack, output, channel, defaults["megabas"]["response"][output][channel]
            )


def tele_megabas(stack: int) -> bool:
    if megabas.getInVolt(stack) < 5:
        return False
    tele["master"] = "megabas" + str(stack)
    tele["fw"] = megabas.getVer(stack)
    tele["power_in"] = megabas.getInVolt(stack)
    tele["power_rsp"] = megabas.getRaspVolt(stack)
    tele["cpu_temp"] = megabas.getCpuTemp(stack)
    tele["wtd_resets"] = megabas.wdtGetResetCount(stack)
    return True


def watchdog_megabas(stack: int, mode: int) -> bool:
    if megabas.getInVolt(stack) < 5:
        return False
    if mode == 1:
        if megabas.wdtGetPeriod(stack) != int(config["WATCHDOG"]["TIMEOUT"]):
            logger.debug(
                "Setting megabas watchdog period: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["TIMEOUT"],
            )
            megabas.wdtSetPeriod(stack, int(config["WATCHDOG"]["TIMEOUT"]))
        if megabas.wdtGetDefaultPeriod(stack) != int(config["WATCHDOG"]["BOOT"]):
            logger.debug(
                "Setting megabas watchdog default period: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["BOOT"],
            )
            megabas.wdtSetDefaultPeriod(stack, int(config["WATCHDOG"]["BOOT"]))
        if megabas.wdtGetOffInterval(stack) != int(config["WATCHDOG"]["RESET"]):
            logger.debug(
                "Setting megabas watchdog off interval: stack=%s value=%s",
                stack,
                config["WATCHDOG"]["RESET"],
            )
            megabas.wdtSetOffInterval(stack, int(config["WATCHDOG"]["RESET"]))
    elif mode == 2:
        logger.debug("Disabling megabas watchdog: stack=%s", stack)
        megabas.wdtSetPeriod(stack, 65000)
    else:
        logger.debug("Reloading megabas watchdog: stack=%s", stack)
        megabas.wdtReload(stack)
    return True


def get_8relind(stack: int, init: int) -> None:
    for channel in range(1, 9):
        value = lib8relind.get(stack, channel)
        if init or value != cache[stack]["response"]["relay"][channel - 1]:
            mqtt_publish(
                "8relind/" + str(stack) + "/response/relay/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["relay"][channel - 1] = value


def set_8relind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "relay" and 1 <= channel <= 8 and value in [0, 1]:
        logger.debug(
            "Setting 8relind stack: %s, response: relay, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        lib8relind.set(stack, channel, value)
        value = lib8relind.get(stack, channel)
        mqtt_publish(
            "8relind/" + str(stack) + "/response/relay/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["relay"][channel - 1] = value
    else:
        logger.error(
            "Can't set 8relind stack: "
            + str(stack)
            + ", topic: "
            + output
            + ", channel: "
            + str(channel)
            + " to value: "
            + str(value)
        )


def reset_8relind(stack: int) -> None:
    for output in defaults["8relind"]["response"].keys():
        for channel in defaults["8relind"]["response"][output].keys():
            set_8relind(
                stack, output, channel, defaults["8relind"]["response"][output][channel]
            )


def get_16inpind(stack: int, init: int) -> None:
    for channel in range(1, 17):
        fce = lib16inpind.getOptoEdge(stack, channel, 0)
        rce = lib16inpind.getOptoEdge(stack, channel, 1)
        value = (rce << 0) | (fce << 1)
        if init or value != cache[stack]["response"]["opto_edge"][channel - 1]:
            mqtt_publish(
                "16inpind/" + str(stack) + "/response/opto_edge/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["opto_edge"][channel - 1] = value

        value = 0
        if init or value != cache[stack]["response"]["opto_rst"][channel - 1]:
            mqtt_publish(
                "16inpind/" + str(stack) + "/response/opto_rst/" + str(channel),
                payload=str(value),
            )
            cache[stack]["response"]["opto_rst"][channel - 1] = value

        value = lib16inpind.getOpto(stack, channel)
        if init or value != cache[stack]["input"]["opto"][channel - 1]:
            mqtt_publish(
                "16inpind/" + str(stack) + "/input/opto/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["opto"][channel - 1] = value

        value = lib16inpind.getOptoCount(stack, channel)
        if init or value != cache[stack]["input"]["opto_count"][channel - 1]:
            mqtt_publish(
                "16inpind/" + str(stack) + "/input/opto_count/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["opto_count"][channel - 1] = value


def set_16inpind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "opto_edge" and 1 <= channel <= 16 and value in [0, 1, 2, 3]:
        logger.debug(
            "Setting 16inpind stack: %s, response: opto_edge, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        rce = (value >> 0) & 1
        fce = (value >> 1) & 1
        # Edge type (0=falling, 1=rising)
        lib16inpind.setOptoEdge(stack, channel, 0, fce)
        lib16inpind.setOptoEdge(stack, channel, 1, rce)
        fce = lib16inpind.getOptoEdge(stack, channel, 0)
        rce = lib16inpind.getOptoEdge(stack, channel, 1)
        value = (rce << 0) | (fce << 1)
        mqtt_publish(
            "16inpind/" + str(stack) + "/response/opto_edge/" + str(channel),
            payload=str(value),
        )
        cache[stack]["response"]["opto_edge"][channel - 1] = value
    elif output == "opto_rst" and 1 <= channel <= 16 and value in [0, 1]:
        logger.debug(
            "Setting 16inpind stack: %s, response: opto_rst, channel: %s to value: %s",
            stack,
            channel,
            value,
        )
        if value == 1:
            lib16inpind.resetOptoCount(stack, channel, 0, value)
            value = lib16inpind.getOptoCount(stack, channel, 0)
            mqtt_publish(
                "16inpind/" + str(stack) + "/response/opto_rst/" + str(channel),
                payload="1",
            )
            mqtt_publish(
                "16inpind/" + str(stack) + "/input/opto_count/" + str(channel),
                payload=str(value),
            )
        mqtt_publish(
            "16inpind/" + str(stack) + "/response/opto_rst/" + str(channel),
            str(value),
        )
        cache[stack]["response"]["opto_rst"][channel - 1] = value
    else:
        logger.error(
            "Can't set 16inpind stack: "
            + str(stack)
            + ", topic: "
            + output
            + ", channel: "
            + str(channel)
            + " to value: "
            + str(value)
        )


def get_8inputs(stack: int, init: int) -> None:
    for channel in range(1, 9):
        value = lib8inputs.get_opto(stack, channel)
        if init or value != cache[stack]["input"]["opto"][channel - 1]:
            mqtt_publish(
                "8inputs/" + str(stack) + "/input/opto/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["opto"][channel - 1] = value


def get_rtd(stack: int, init: int) -> None:
    for channel in range(1, 9):
        value = librtd.get(stack, channel)
        if init or value != cache[stack]["input"]["rtd"][channel - 1]:
            mqtt_publish(
                "rtd/" + str(stack) + "/input/rtd/" + str(channel),
                payload=str(value),
            )
            cache[stack]["input"]["rtd"][channel - 1] = value


def cards_subscribe():
    client.subscribe(
        config["MQTT"]["TOPIC"] + "/tele/cmnd/+", int(config["MQTT"]["QOS"])
    )
    for stack in cards.keys():
        # Subscribe for output commands only for cards with response topics
        if "response" in cache[stack]:
            logging.debug(
                f"Subscribing for output commands for stack {stack} of type {cards[stack]}"
            )
            client.subscribe(
                config["MQTT"]["TOPIC"]
                + "/"
                + cards[stack]
                + "/"
                + str(stack)
                + "/output/#",
                int(config["MQTT"]["QOS"]),
            )

    # Subscribe for heartbeat challenge messages
    client.subscribe(
        config["MQTT"]["TOPIC"] + "/" + config["HEARTBEAT"]["TOPIC_CHALLENGE"], int(config["MQTT"]["QOS"])
    )

    # Subscribe for Home Assistant birth messages
    if config["MQTT"]["BIRTH_TOPIC"]:
        client.subscribe(config["MQTT"]["BIRTH_TOPIC"], int(config["MQTT"]["QOS"]))


def cards_unsubscribe() -> None:
    client.unsubscribe(
        config["MQTT"]["TOPIC"] + "/tele/cmnd/+", int(config["MQTT"]["QOS"])
    )
    client.unsubscribe(
        config["MQTT"]["TOPIC"] + "/" + config["HEARTBEAT"]["TOPIC_CHALLENGE"], int(config["MQTT"]["QOS"])
    )
    # Unsubscribe from Home Assistant birth messages
    if config["MQTT"]["BIRTH_TOPIC"]:
        client.unsubscribe(config["MQTT"]["BIRTH_TOPIC"], int(config["MQTT"]["QOS"]))

    for stack in cards.keys():
        client.unsubscribe(
            config["MQTT"]["TOPIC"] + "/" + cards[stack] + "/#",
            int(config["MQTT"]["QOS"]),
        )


def cards_tele(mode: int) -> bool:
    global last_tele
    now = time.time()
    if now - last_tele > int(config["RUNTIME"]["TELE_INTERVAL"]) or mode == 1:
        get_time()
        for stack in cards.keys():
            if cards[stack] == "megaind":
                if tele_megaind(stack):
                    break
            elif cards[stack] == "megabas":
                if tele_megabas(stack):
                    break
        mqtt_publish(
            "tele/STATE",
            payload=json.dumps(tele),
        )
        last_tele = now
        mode = 1

    for stack in cards.keys():
        if client and client.is_connected():
            logger.debug(
                f"Updating MQTT telemetry for stack {stack} of type {cards[stack]}"
            )
        else:
            logger.error("MQTT not connected!")
            raise MqttError("MQTT not connected!")

        if cards[stack] == "megaind":
            get_megaind(stack, mode)
        elif cards[stack] == "megabas":
            get_megabas(stack, mode)
        elif cards[stack] == "8relind":
            get_8relind(stack, mode)
        elif cards[stack] == "8inputs":
            get_8inputs(stack, mode)
        elif cards[stack] == "16inpind":
            get_16inpind(stack, mode)
        elif cards[stack] == "rtd":
            get_rtd(stack, mode)
        else:
            raise AppError("Unknown card type " + cards[stack])

    # Sent LWT update
    mqtt_publish("tele/LWT", payload="Online", retain=True)


def cards_watchdog(mode: int) -> bool:
    global last_watchdog

    # If watchdog is disabled, do nothing
    if int(config["WATCHDOG"]["TIMEOUT"]) == 0:
        return True

    now = int(time.time())
    for stack in cards.keys():
        if cards[stack] not in ["megaind", "megabas"]:
            continue
        if mode == 1:
            logger.debug(f"Enabling watchdog for stack {stack} of type {cards[stack]}")
        elif mode == 2:
            logger.debug(f"Disabling watchdog for stack {stack} of type {cards[stack]}")
        elif mode == 0:
            if (
                last_watchdog >= 0
                and last_watchdog + (int(config["WATCHDOG"]["TIMEOUT"]) / 3) < now
            ):
                logger.debug(
                    f"Resetting watchdog timer for stack {stack} of type {cards[stack]}"
                )
            else:
                return True
        else:
            return False

        if cards[stack] == "megaind":
            if watchdog_megaind(stack, mode):
                last_watchdog = now
                logger.debug("Card watchdog set completed")
                return True
        elif cards[stack] == "megabas":
            if watchdog_megabas(stack, mode):
                last_watchdog = now
                logger.debug("Card watchdog set completed")
                return True
    return False


def check_heartbeat(mode: int) -> None:
    global last_heartbeat
    global last_watchdog

    # If heartbeat is disabled, do nothing
    if int(config["HEARTBEAT"]["TIMEOUT"]) == 0:
        return True

    now = int(time.time())
    if mode == 1:
        last_heartbeat = now
        mqtt_publish(
            config["HEARTBEAT"]["TOPIC_RESPONSE"],
            payload=str(now),
        )
    elif mode == 0:
        if (
            int(config["HEARTBEAT"]["TIMEOUT"]) > 0
            and last_heartbeat >= 0
            and now - last_heartbeat > int(config["HEARTBEAT"]["TIMEOUT"])
        ):
            logger.error("Missing heartbeat, all cards outputs will be reset!")
            # This is critical error, reset all outputs to default values to prevent possible damage of connected devices
            # Disable hardware watchdog timer reset, so hardware reboot will be triggered if cards reset is not successful
            last_watchdog_bak = last_watchdog
            last_watchdog = -1
            for stack in cards.keys():
                if cards[stack] == "megaind":
                    reset_megaind(stack)
                elif cards[stack] == "megabas":
                    reset_megabas(stack)
                elif cards[stack] == "8relind":
                    reset_8relind(stack)
            # Restore watchdog timer resets
            last_watchdog = last_watchdog_bak
            # Prevent multiple resets until heartbeat is received again
            last_heartbeat = -1
            logger.error("Missing heartbeat, all cards outputs were reset!")
            raise AppError("Missing heartbeat, all cards outputs were reset!")
        else:
            return True
    else:
        return False


def get_uptime_seconds() -> int:
    # Support different uptime package APIs and fallback to /proc/uptime.
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return int(float(f.read().split()[0]))
    except Exception as error:
        logger.warning(f"Could not determine system uptime: {error}")
        return 0


def get_time() -> None:
    result = ""
    uptime_seconds = get_uptime_seconds()
    result = "%01d" % int(uptime_seconds / 86400)
    uptime_seconds = uptime_seconds % 86400
    result = result + "T" + "%02d" % (int(uptime_seconds / 3600))
    uptime_seconds = uptime_seconds % 3600
    tele["Uptime"] = (
        result
        + ":"
        + "%02d" % (int(uptime_seconds / 60))
        + ":"
        + "%02d" % (uptime_seconds % 60)
    )
    tele["Time"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def mqtt_init() -> None:
    global client

    # Create mqtt client
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    # Register LWT message
    client.will_set(
        config["MQTT"]["TOPIC"] + "/tele/LWT", payload="Offline", qos=int(config["MQTT"]["QOS"]), retain=True
    )
    # Let auto-reconnect progressively if the link drops.
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Register connect callback
    client.on_connect = mqtt_on_connect
    # Register disconnect callback
    client.on_disconnect = mqtt_on_disconnect
    # Register publish message callback
    client.on_message = mqtt_on_message
    # Set access token
    client.username_pw_set(config["MQTT"]["USER"], config["MQTT"]["PASS"])
    # Run receive thread
    client.loop_start()
    # Connect to broker
    client.connect(
        config["MQTT"]["SERVER"],
        int(config["MQTT"]["PORT"]),
        int(config["MQTT"]["TIMEOUT"]),
    )
    time.sleep(1)
    mqtt_check()


def mqtt_check() -> None:
    global client

    if not client:
        raise MqttError("MQTT client is not initialized")

    retries = 0
    while not client.is_connected():
        if retries >= 5:
            raise MqttError("MQTT reconnect failed")
        logger.warning("MQTT is disconnected, trying to connect")
        try:
            client.reconnect()
        except Exception as error:
            logger.warning(f"MQTT reconnect attempt failed: {error}")
        retries += 1
        time.sleep(1)


def mqtt_publish(
    topic: str,
    payload: str,
    qos: int = int(config["MQTT"]["QOS"]),
    retain: bool = False,
) -> None:
    global client

    if client and client.is_connected():
        try:
            result = client.publish(
                config["MQTT"]["TOPIC"] + "/" + topic,
                payload=payload,
                qos=qos,
                retain=retain,
            )
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise MqttError(f"MQTT publish failed with code {result.rc} on topic {topic}")
        except Exception as error:
            logger.error(f"Failed to publish MQTT message: {error}")
            raise MqttError(f"Failed to publish MQTT message: {error}")
    else:
        logger.error("MQTT not connected!")
        raise MqttError("MQTT not connected!")


def mqtt_cleanup() -> None:
    global client

    if client:
        client.loop_stop()
        if client.is_connected():
            # Unsubscribe from all topics
            cards_unsubscribe()
            # Sent LWT update
            mqtt_publish("/tele/LWT", payload="Offline", retain=True)
            client.disconnect()
        client = None


def mqtt_on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: dict,
    reason_code: int,
    properties: mqtt.Properties,
):
    if reason_code != 0:
        logger.error("MQTT unexpected connect return code " + str(reason_code))
    else:
        logger.info("MQTT client connected")
        client.connected_flag = 1

    # Subscribe for MQTT topics
    cards_subscribe()


def mqtt_on_disconnect(
    client: mqtt.Client,
    userdata: Any,
    flags: dict,
    reason_code: int,
    properties: mqtt.Properties,
):
    client.connected_flag = 0
    if reason_code != 0:
        logger.error("MQTT unexpected disconnect return code " + str(reason_code))
    logger.info("MQTT client disconnected")


# The callback for when a PUBLISH message is received from the server.
def mqtt_on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    tele = re.match(
        r"^" + config["MQTT"]["TOPIC"] + "/tele/cmnd/(state)$", str(msg.topic)
    )
    megaind = re.match(
        r"^"
        + config["MQTT"]["TOPIC"]
        + "/megaind/([0-7])/output/(0_10|4_20|pwm|led|opto_edge|opto_rst)/([0-9]+)$",
        str(msg.topic),
    )
    megabas = re.match(
        r"^"
        + config["MQTT"]["TOPIC"]
        + "/megabas/([0-7])/output/(0_10|triac|cont_edge)/([0-9]+)$",
        str(msg.topic),
    )
    relind8 = re.match(
        r"^" + config["MQTT"]["TOPIC"] + "/8relind/([0-7])/output/(relay)/([0-9]+)$",
        str(msg.topic),
    )
    inpind16 = re.match(
        r"^"
        + config["MQTT"]["TOPIC"]
        + "/16inpind/([0-7])/output/(opto_edge|opto_rst)/([0-9]+)$",
        str(msg.topic),
    )
    heartbeat = re.match(
        r"^"
        + config["MQTT"]["TOPIC"]
        + "/"
        + config["HEARTBEAT"]["TOPIC_CHALLENGE"]
        + "$",
        str(msg.topic),
    )
    birth = re.match(r"^" + config["MQTT"]["BIRTH_TOPIC"] + "$", str(msg.topic))

    payload = str(msg.payload.decode("utf-8"))

    if tele:
        topic = tele.group(1)
        if topic == "state" and payload == "":
            cards_tele(1)
    elif heartbeat:
        check_heartbeat(1)
    elif birth:
        if config["MQTT"]["BIRTH_TOPIC"]:
            if payload.lower() == "online":
                logger.info("Home Assistant is online")
                cards_tele(1)
            else:
                logger.info("Home Assistant is " + payload)
    else:
        payload_i = re.match(r"^(\d+)$", payload)
        payload_f = re.match(r"^(\d+\.\d+)$", payload)
        if payload_i:
            payload = int(payload_i.group(1))
        elif payload_f:
            payload = float(payload_f.group(1))
        logger.debug(
            "Received MQTT message: " + str(msg.topic) + ", Message: " + str(payload)
        )
        if megaind:
            stack = int(megaind.group(1))
            output = megaind.group(2)
            channel = int(megaind.group(3))
            logger.debug(
                "MQTT output command: topic=%s payload=%s retain=%s stack=%s output=%s channel=%s",
                str(msg.topic),
                payload,
                msg.retain,
                stack,
                output,
                channel,
            )
            set_megaind(stack, output, channel, payload)
            logger.debug(
                "MQTT output applied: stack=%s output=%s channel=%s requested=%s",
                stack,
                output,
                channel,
                payload,
            )
        elif megabas:
            stack = int(megabas.group(1))
            output = megabas.group(2)
            channel = int(megabas.group(3))
            logger.debug(
                "MQTT output command: topic=%s payload=%s retain=%s stack=%s output=%s channel=%s",
                str(msg.topic),
                payload,
                msg.retain,
                stack,
                output,
                channel,
            )
            set_megabas(stack, output, channel, payload)
            logger.debug(
                "MQTT output applied: stack=%s output=%s channel=%s requested=%s",
                stack,
                output,
                channel,
                payload,
            )
        elif relind8:
            stack = int(relind8.group(1))
            output = relind8.group(2)
            channel = int(relind8.group(3))
            logger.debug(
                "MQTT output command: topic=%s payload=%s retain=%s stack=%s output=%s channel=%s",
                str(msg.topic),
                payload,
                msg.retain,
                stack,
                output,
                channel,
            )
            set_8relind(stack, output, channel, payload)
            logger.debug(
                "MQTT output applied: stack=%s output=%s channel=%s requested=%s",
                stack,
                output,
                channel,
                payload,
            )
        elif inpind16:
            stack = int(inpind16.group(1))
            output = inpind16.group(2)
            channel = int(inpind16.group(3))
            logger.debug(
                "MQTT output command: topic=%s payload=%s retain=%s stack=%s output=%s channel=%s",
                str(msg.topic),
                payload,
                msg.retain,
                stack,
                output,
                channel,
            )
            set_16inpind(stack, output, channel, payload)
            logger.debug(
                "MQTT output applied: stack=%s output=%s channel=%s requested=%s",
                stack,
                output,
                channel,
                payload,
            )
        else:
            logger.warning(
                "Unknown MQTT topic: " + str(msg.topic) + ", Message: " + str(payload)
            )


# Main loop
last_heartbeat = int(time.time())
last_watchdog = 0
client = None
restart = 0
while True:
    try:
        # Init counters
        last_tele = 0
        last_watchdog = 0
        # Arm hardware watchdog
        cards_watchdog(1)
        # Heartbeat check
        check_heartbeat(0)
        # Reset watchdog timer
        cards_watchdog(0)
        # Create mqtt client
        if not client:
            # Init mqtt
            mqtt_init()
        # Run sending thread
        while True:
            cards_tele(0)
            check_heartbeat(0)
            cards_watchdog(0)
            time.sleep(1)
    except BaseException as error:
        logger.error(f"An exception occurred: {type(error).__name__} – {error}")
        if type(error) in [MqttError, AppError] and (
            int(config["RUNTIME"]["MAX_ERROR"]) == 0
            or restart <= int(config["RUNTIME"]["MAX_ERROR"])
        ):
            if type(error) is MqttError:
                mqtt_cleanup()
            elif type(error) is AppError:
                pass
            restart += 1
            # Try to reconnect later
            time.sleep(int(config["RUNTIME"]["RESTART_DELAY"]))
        elif type(error) in [KeyboardInterrupt, SystemExit]:
            # Graceful shutdown
            logger.error("Gracefully terminating application")
            mqtt_cleanup()
            cards_watchdog(2)
            logger.error("Application terminated")
            sys.exit(0)
        else:
            # Exit with error
            logger.error("Unknown exception, aborting application")
            logger.debug(f"Exception details: {traceback.format_exc()}")
            sys.exit(1)
