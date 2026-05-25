#! /usr/bin/python3

import logging
import paho.mqtt.client as mqtt
import configparser
import operator
import copy
import json
import time
import uptime
import datetime
import re
import sys
import traceback
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
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["0_10"][channel - 1] = value

        value = megaind.get4_20Out(stack, channel)
        if init or value != cache[stack]["response"]["4_20"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/4_20/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["4_20"][channel - 1] = value

        value = megaind.getOdPWM(stack, channel)
        if init or value != cache[stack]["response"]["pwm"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/pwm/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["pwm"][channel - 1] = value

        value = megaind.getLed(stack, channel)
        if init or value != cache[stack]["response"]["led"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/led/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["led"][channel - 1] = value

        value = megaind.getOptoRisingCountEnable(stack, channel)
        if init or value != cache[stack]["response"]["opto_edge"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/opto_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["opto_edge"][channel - 1] = value

        value = 0
        if init or value != cache[stack]["response"]["opto_rst"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/opto_rst/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["opto_rst"][channel - 1] = value

        value = round(megaind.get0_10In(stack, channel), 2)
        if init or value != cache[stack]["input"]["0_10"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/input/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["0_10"][channel - 1] = value

        value = round(megaind.getpm10In(stack, channel), 2)
        if init or value != cache[stack]["input"]["pm0_10"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/input/pm0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["pm0_10"][channel - 1] = value

        value = megaind.get4_20In(stack, channel)
        if init or value != cache[stack]["input"]["4_20"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/input/4_20/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["4_20"][channel - 1] = value

        value = megaind.getOptoCh(stack, channel)
        if init or value != cache[stack]["input"]["opto"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/input/opto/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["opto"][channel - 1] = value

        value = megaind.getOptoCount(stack, channel)
        if init or value != cache[stack]["input"]["opto_count"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/input/opto_count/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["opto_count"][channel - 1] = value


def set_megaind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "0_10" and 1 <= channel <= 4 and 0 <= value <= 10:
        try:
            megaind.set0_10Out(stack, channel, value)
            value == megaind.get0_10Out(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: 0_10, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["0_10"][channel - 1] = value
    elif output == "4_20" and 1 <= channel <= 4 and 4 <= value <= 20:
        try:
            megaind.set4_20Out(stack, channel, value)
            value == megaind.get0_10Out(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/4_20/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: 4_20, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["4_20"][channel - 1] = value
    elif output == "pwm" and 1 <= channel <= 4 and 0 <= value <= 100:
        try:
            megaind.setOdPWM(stack, channel, value)
            value = megaind.getOdPWM(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/pwm/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: pwm, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["pwm"][channel - 1] = value
    elif output == "led" and 1 <= channel <= 4 and value in [0, 1]:
        try:
            megaind.setLed(stack, channel, value)
            value = megaind.getLed(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/led/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: led, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["led"][channel - 1] = value
    elif output == "opto_edge" and 1 <= channel <= 4 and value in [0, 1, 2, 3]:
        try:
            rce = (value >> 0) & 1
            fce = (value >> 1) & 1
            megaind.setOptoRisingCountEnable(stack, channel, rce)
            megaind.setOptoFallingCountEnable(stack, channel, fce)
            rce = megaind.getOptoRisingCountEnable(stack, channel)
            fce = megaind.getOptoFallingCountEnable(stack, channel)
            value = (rce << 0) | (fce << 1)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/opto_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: opto_edge, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["opto_edge"][channel - 1] = value
    elif output == "opto_rst" and 1 <= channel <= 4 and value in [0, 1]:
        try:
            if value == 1:
                megaind.rstOptoCount(stack, channel)
                value = megaind.getOptoCount(stack, channel)
                client.publish(
                    config["MQTT"]["TOPIC"]
                    + "/megaind/"
                    + str(stack)
                    + "/response/opto_rst/"
                    + str(channel),
                    1,
                    int(config["MQTT"]["QOS"]),
                )
                client.publish(
                    config["MQTT"]["TOPIC"]
                    + "/megaind/"
                    + str(stack)
                    + "/input/opto_count/"
                    + str(channel),
                    str(value),
                    int(config["MQTT"]["QOS"]),
                )
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megaind/"
                + str(stack)
                + "/response/opto_rst/"
                + str(channel),
                0,
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megaind stack: "
                + str(stack)
                + ", response: opto_rst, channel: "
                + str(channel)
                + " to value: 1"
            )
        else:
            cache[stack]["input"]["opto_count"][channel - 1] = value
    else:
        raise AppError(
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
    for channel in range(1, 5):
        for output in ("4_20", "0_10", "pwm", "led"):
            set_megaind(stack, output, channel, 0)


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
            try:
                megaind.wdtSetPeriod(stack, int(config["WATCHDOG"]["TIMEOUT"]))
            except:
                raise AppError(
                    "Can't set watchdog period for megaind stack: "
                    + str(stack)
                    + " to value: "
                    + config["WATCHDOG"]["TIMEOUT"]
                )
        if megaind.wdtGetDefaultPeriod(stack) != int(config["WATCHDOG"]["BOOT"]):
            try:
                megaind.wdtSetDefaultPeriod(stack, int(config["WATCHDOG"]["BOOT"]))
            except:
                raise AppError(
                    "Can't set watchdog default period for megaind stack: "
                    + str(stack)
                    + " to value: "
                    + config["WATCHDOG"]["BOOT"]
                )
        if megaind.wdtGetOffInterval(stack) != int(config["WATCHDOG"]["RESET"]):
            try:
                megaind.wdtSetOffInterval(stack, int(config["WATCHDOG"]["RESET"]))
            except:
                raise AppError(
                    "Can't set watchdog off interval for megaind stack: "
                    + str(stack)
                    + " to value: "
                    + config["WATCHDOG"]["RESET"]
                )
    elif mode == 2:
        try:
            megaind.wdtSetPeriod(stack, 65000)
        except:
            raise AppError(
                "Can't set watchdog period for megaind stack: "
                + str(stack)
                + " to value: 65000"
            )
    else:
        try:
            megaind.wdtReload(stack)
        except:
            raise AppError("Can't reload watchdog for megaind stack: " + str(stack))
    return True


def get_megabas(stack: int, init: int) -> None:
    triacs = megabas.getTriacs(stack)
    for channel in range(1, 5):
        value = megabas.getUOut(stack, channel)
        if init or value != cache[stack]["response"]["0_10"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["0_10"][channel - 1] = value

        if triacs & (1 << channel - 1):
            value = 1
        else:
            value = 0
        if init or value != cache[stack]["response"]["triac"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/triac/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["triac"][channel - 1] = value

    for channel in range(1, 9):
        value = round(megabas.getUIn(stack, channel), 2)
        if init or value != cache[stack]["input"]["0_10"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/input/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["0_10"][channel - 1] = value

        value = round(megabas.getRIn1K(stack, channel), 2)
        if init or value != cache[stack]["input"]["1k"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/input/1k/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["0_10"][channel - 1] = value

        value = round(megabas.getRIn10K(stack, channel), 2)
        if init or value != cache[stack]["input"]["10k"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/input/10k/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["10k"][channel - 1] = value

        value = megabas.getContactCh(stack, channel)
        if init or value != cache[stack]["input"]["cont"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/input/cont/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["cont"][channel - 1] = value

        value = megabas.getContactCounter(stack, channel)
        if init or value != cache[stack]["input"]["cont_count"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/input/cont_count/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["cont_count"][channel - 1] = value

        value = megabas.getContactCountEdge(stack, channel)
        if init or value != cache[stack]["response"]["cont_edge"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/cont_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["cont_edge"][channel - 1] = value

    megabas.getTriacs(stack)


def set_megabas(stack: int, output: str, channel: int, value: int) -> None:
    if output == "0_10" and 1 <= channel <= 4 and 0 <= value <= 10:
        try:
            megabas.setUOut(stack, channel, value)
            value = megabas.getUOut(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/0_10/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megabas stack: "
                + str(stack)
                + ", response: 0_10, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["0_10"][channel - 1] = value
    elif output == "triac" and 1 <= channel <= 4 and value in [0, 1]:
        try:
            megabas.setTriac(stack, channel, value)
            triacs = megabas.getTriacs(stack)
            if triacs & (1 << channel - 1):
                value = 1
            else:
                value = 0
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/triac/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megabas stack: "
                + str(stack)
                + ", response: triac, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["triac"][channel - 1] = value
    elif output == "cont_edge" and 1 <= channel <= 8 and value in [0, 1, 2, 3]:
        try:
            megabas.setContactCountEdge(stack, channel, value)
            value = megabas.getContactCountEdge(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/megabas/"
                + str(stack)
                + "/response/cont_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set megabas stack: "
                + str(stack)
                + ", response: cont_edge, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["cont_edge"][channel - 1] = value
    else:
        raise AppError(
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
    for channel in range(1, 5):
        for output in ("0_10", "triac"):
            set_megabas(stack, output, channel, 0)


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
            try:
                megabas.wdtSetPeriod(stack, int(config["WATCHDOG"]["TIMEOUT"]))
            except:
                raise AppError(
                    "Can't set megabas stack: "
                    + str(stack)
                    + ", watchdog period to value: "
                    + str(config["WATCHDOG"]["TIMEOUT"])
                )
        if megabas.wdtGetDefaultPeriod(stack) != int(config["WATCHDOG"]["BOOT"]):
            try:
                megabas.wdtSetDefaultPeriod(stack, int(config["WATCHDOG"]["BOOT"]))
            except:
                raise AppError(
                    "Can't set megabas stack: "
                    + str(stack)
                    + ", watchdog default period to value: "
                    + str(config["WATCHDOG"]["BOOT"])
                )
        if megabas.wdtGetOffInterval(stack) != int(config["WATCHDOG"]["RESET"]):
            try:
                megabas.wdtSetOffInterval(stack, int(config["WATCHDOG"]["RESET"]))
            except:
                raise AppError(
                    "Can't set megabas stack: "
                    + str(stack)
                    + ", watchdog off interval to value: "
                    + str(config["WATCHDOG"]["RESET"])
                )
    elif mode == 2:
        try:
            megabas.wdtSetPeriod(stack, 65000)
        except:
            raise AppError(
                "Can't set megabas stack: "
                + str(stack)
                + ", watchdog period to value: 65000"
            )
    else:
        try:
            megabas.wdtReload(stack)
        except:
            raise AppError(
                "Can't set megabas stack: " + str(stack) + ", watchdog reload"
            )
    return True


def get_8relind(stack: int, init: int) -> None:
    for channel in range(1, 9):
        value = lib8relind.get(stack, channel)
        if init or value != cache[stack]["response"]["relay"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/8relind/"
                + str(stack)
                + "/response/relay/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["relay"][channel - 1] = value


def set_8relind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "relay" and 1 <= channel <= 8 and value in [0, 1]:
        try:
            lib8relind.set(stack, channel, value)
            value = lib8relind.get(stack, channel)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/8relind/"
                + str(stack)
                + "/response/relay/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set 8relind stack: "
                + str(stack)
                + ", response: relay, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["relay"][channel - 1] = value
    else:
        raise AppError(
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
    for channel in range(1, 9):
        set_8relind(stack, "relay", channel, 0)


def get_16inpind(stack: int, init: int) -> None:
    for channel in range(1, 17):
        fce = lib16inpind.getOptoEdge(stack, channel, 0)
        rce = lib16inpind.getOptoEdge(stack, channel, 1)
        value = (rce << 0) | (fce << 1)
        if init or value != cache[stack]["response"]["opto_edge"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/response/opto_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["opto_edge"][channel - 1] = value

        value = 0
        if init or value != cache[stack]["response"]["opto_rst"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/response/opto_rst/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["response"]["opto_rst"][channel - 1] = value

        value = lib16inpind.getOpto(stack, channel)
        if init or value != cache[stack]["input"]["opto"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/input/opto/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["opto"][channel - 1] = value

        value = lib16inpind.getOptoCount(stack, channel)
        if init or value != cache[stack]["input"]["opto_count"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/input/opto_count/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["opto_count"][channel - 1] = value


def set_16inpind(stack: int, output: str, channel: int, value: int) -> None:
    if output == "opto_edge" and 1 <= channel <= 16 and value in [0, 1, 2, 3]:
        try:
            rce = (value >> 0) & 1
            fce = (value >> 1) & 1
            # Edge type (0=falling, 1=rising)
            lib16inpind.setOptoEdge(stack, channel, 0, fce)
            lib16inpind.setOptoEdge(stack, channel, 1, rce)
            fce = lib16inpind.getOptoEdge(stack, channel, 0)
            rce = lib16inpind.getOptoEdge(stack, channel, 1)
            value = (rce << 0) | (fce << 1)
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/response/opto_edge/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set 16inpind stack: "
                + str(stack)
                + ", response: opto_edge, channel: "
                + str(channel)
                + " to value: "
                + str(value)
            )
        else:
            cache[stack]["response"]["opto_edge"][channel - 1] = value
    elif output == "opto_rst" and 1 <= channel <= 16 and value in [0, 1]:
        try:
            if value == 1:
                lib16inpind.resetOptoCount(stack, channel, 0, value)
                value = lib16inpind.getOptoCount(stack, channel, 0)
                client.publish(
                    config["MQTT"]["TOPIC"]
                    + "/16inpind/"
                    + str(stack)
                    + "/response/opto_rst/"
                    + str(channel),
                    1,
                    int(config["MQTT"]["QOS"]),
                )
                client.publish(
                    config["MQTT"]["TOPIC"]
                    + "/16inpind/"
                    + str(stack)
                    + "/input/opto_count/"
                    + str(channel),
                    str(value),
                    int(config["MQTT"]["QOS"]),
                )
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/16inpind/"
                + str(stack)
                + "/response/opto_rst/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
        except:
            raise AppError(
                "Can't set 16inpind stack: "
                + str(stack)
                + ", response: opto_rst, channel: "
                + str(channel)
                + " to value: 1"
            )
        else:
            cache[stack]["response"]["opto_rst"][channel - 1] = value
    else:
        raise AppError(
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
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/8inputs/"
                + str(stack)
                + "/input/opto/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["opto"][channel - 1] = value


def get_rtd(stack: int, init: int) -> None:
    for channel in range(1, 9):
        value = librtd.get(stack, channel)
        if init or value != cache[stack]["input"]["rtd"][channel - 1]:
            client.publish(
                config["MQTT"]["TOPIC"]
                + "/rtd/"
                + str(stack)
                + "/input/rtd/"
                + str(channel),
                str(value),
                int(config["MQTT"]["QOS"]),
            )
            cache[stack]["input"]["rtd"][channel - 1] = value


def cards_init() -> None:
    client.subscribe(
        config["MQTT"]["TOPIC"] + "/tele/cmnd/+", int(config["MQTT"]["QOS"])
    )
    cards_tele(1)
    for stack in cards.keys():
        # Subscribe for any card commands
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

        if cards[stack] == "megaind":
            get_megaind(stack, 1)
        elif cards[stack] == "megabas":
            get_megabas(stack, 1)
        elif cards[stack] == "8relind":
            get_8relind(stack, 1)
        elif cards[stack] == "8inputs":
            get_8inputs(stack, 1)
        elif cards[stack] == "16inpind":
            get_16inpind(stack, 1)
        elif cards[stack] == "rtd":
            get_rtd(stack, 1)
        else:
            raise AppError("Uknown card type " + cards[stack])

    # Subscribe for heartbeat challenge messages
    client.subscribe(
        config["MQTT"]["TOPIC"] + "/" + config["HEARTBEAT"]["TOPIC_CHALLENGE"]
    )

    # Subscribe for Home Assistant birth messages
    if config["MQTT"]["BIRTH_TOPIC"]:
        client.subscribe(config["MQTT"]["BIRTH_TOPIC"])


def cards_update(mode: int) -> None:
    if cards_tele(mode):
        mode = 1
    else:
        mode = 0

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
            raise AppError("Uknown card type " + cards[stack])

    # Sent LWT update
    client.publish(
        config["MQTT"]["TOPIC"] + "/tele/LWT", payload="Online", qos=0, retain=True
    )


def cards_unsubscribe() -> None:
    client.unsubscribe(
        config["MQTT"]["TOPIC"] + "/tele/cmnd/+", int(config["MQTT"]["QOS"])
    )
    client.unsubscribe(
        config["MQTT"]["TOPIC"] + "/" + config["HEARTBEAT"]["TOPIC_CHALLENGE"]
    )
    # Unsubscribe from Home Assistant birth messages
    if config["MQTT"]["BIRTH_TOPIC"]:
        client.unsubscribe(config["MQTT"]["BIRTH_TOPIC"])

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
        client.publish(
            config["MQTT"]["TOPIC"] + "/tele/STATE",
            json.dumps(tele),
            int(config["MQTT"]["QOS"]),
        )
        last_tele = now
        return True
    else:
        return False


def cards_watchdog(mode: int) -> bool:
    global last_watchdog

    now = int(time.time())
    for stack in cards.keys():
        if cards[stack] not in ["megaind", "megabas"]:
            continue
        if mode == 1:
            logger.debug(f"Enabling watchdog for stack {stack} of type {cards[stack]}")
        elif mode == 2:
            logger.debug(f"Disabling watchdog for stack {stack} of type {cards[stack]}")
        elif (
            mode == 0 and last_watchdog + (int(config["WATCHDOG"]["TIMEOUT"]) / 3) < now
        ):
            logger.debug(f"Reseting watchdog for stack {stack} of type {cards[stack]}")
        else:
            return False
        last_watchdog = now
        if cards[stack] == "megaind":
            watchdog_megaind(stack, mode)
            return True
        elif cards[stack] == "megabas":
            watchdog_megabas(stack, mode)
            return True
    return True


def check_heartbeat(mode: int) -> None:
    global last_heartbeat
    now = int(time.time())
    if mode == 1:
        last_heartbeat = now
        client.publish(
            config["MQTT"]["TOPIC"] + "/" + config["HEARTBEAT"]["TOPIC_RESPONSE"],
            str(now),
            int(config["MQTT"]["QOS"]),
        )
    elif (
        int(config["HEARTBEAT"]["TIMEOUT"]) > 0
        and last_heartbeat >= 0
        and now - last_heartbeat > int(config["HEARTBEAT"]["TIMEOUT"])
    ):
        for stack in cards.keys():
            if cards[stack] == "megaind":
                reset_megaind(stack)
            elif cards[stack] == "megabas":
                reset_megabas(stack)
            elif cards[stack] == "8relind":
                reset_8relind(stack)
        last_heartbeat = -1
        raise AppError("Missing heartbeat, all cards outputs reseted!")


def get_uptime_seconds() -> int:
    # Support different uptime package APIs and fallback to /proc/uptime.
    try:
        fn = getattr(uptime, "uptime", None)
        if callable(fn):
            return int(fn())

        fn = getattr(uptime, "boottime", None)
        if callable(fn):
            boot = fn()
            if isinstance(boot, datetime.datetime):
                return int((datetime.datetime.now() - boot).total_seconds())
            return int(time.time() - float(boot))

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
        config["MQTT"]["TOPIC"] + "/tele/LWT", payload="Offline", qos=0, retain=True
    )
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

    timeout = 0
    reconnect = 0
    time.sleep(1)
    while not client.is_connected():
        time.sleep(1)
        timeout += 1
        if timeout > 15:
            logger.info("MQTT waiting to connect")
            if reconnect > 10:
                logger.error("MQTT not connected!")
                raise MqttError("MQTT not connected!")
            client.reconnect()
            reconnect += 1
            timeout = 0


def mqtt_cleanup() -> None:
    global client

    if client:
        client.loop_stop()
        if client.is_connected():
            cards_unsubscribe()
            # Sent LWT update
            client.publish(
                config["MQTT"]["TOPIC"] + "/tele/LWT",
                payload="Offline",
                qos=0,
                retain=True,
            )
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
            cards_update(1)
    elif heartbeat:
        check_heartbeat(1)
    elif birth:
        if config["MQTT"]["BIRTH_TOPIC"]:
            if payload.lower() == "online":
                logger.info("Home Assistant is online")
                cards_update(1)
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
            set_megaind(stack, output, channel, payload)
        elif megabas:
            stack = int(megabas.group(1))
            output = megabas.group(2)
            channel = int(megabas.group(3))
            set_megabas(stack, output, channel, payload)
        elif relind8:
            stack = int(relind8.group(1))
            output = relind8.group(2)
            channel = int(relind8.group(3))
            set_8relind(stack, output, channel, payload)
        elif inpind16:
            stack = int(inpind16.group(1))
            output = inpind16.group(2)
            channel = int(inpind16.group(3))
            set_16inpind(stack, output, channel, payload)
        else:
            raise AppError(
                "Unknown MQTT topic: " + str(msg.topic) + ", Message: " + str(payload)
            )


# Imain loop
last_heartbeat = int(time.time())
client = None
restart = 0
while True:
    try:
        # Init counters
        last_tele = 0
        last_watchdog = 0
        # Heartbeat check
        check_heartbeat(0)
        # Create mqtt client
        if not client:
            # Init mqtt
            mqtt_init()
        # init cards inputs and subscribe for output topics
        cards_init()
        # init watchdogs
        cards_watchdog(1)
        # Run sending thread
        while True:
            cards_update(0)
            cards_watchdog(0)
            check_heartbeat(0)
            time.sleep(1)
    except BaseException as error:
        logger.error(f"An exception occurred: {type(error).__name__} – {error}")
        if type(error) in [MqttError, AppError] and (
            int(config["RUNTIME"]["MAX_ERROR"]) == 0
            or restart <= int(config["RUNTIME"]["MAX_ERROR"])
        ):
            if type(error) == MqttError:
                mqtt_cleanup()
            elif type(error) == AppError:
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
            logger.error(f"Unknown exception, aborting application")
            logger.debug(f"Exception details: {traceback.format_exc()}")
            sys.exit(1)
