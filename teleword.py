import json
import logging
import ssl
import sys
import urllib.request
from typing import Tuple, Union, Dict, Optional
from urllib.error import URLError, HTTPError

TELEGRAM_API_ENDPOINT = "https://api.telegram.org/bot"

logger = logging.getLogger("teleword")


def setup_logging() -> None:
    logging.basicConfig(format="[ %(asctime)s | %(levelname)-6s ] %(message)s", level=logging.DEBUG)


def make_http_request(url: str, insecure: bool = True) -> Tuple[int, str]:
    ssl_context: Optional[ssl.SSLContext]
    if insecure:
        ssl_context = ssl.SSLContext()
    else:
        ssl_context = None

    try:
        with urllib.request.urlopen(url, context=ssl_context) as response:
            return response.getcode(), response.read().decode()
    except HTTPError as exc:
        logger.debug("{0}: {1}".format(exc.code, str(exc.reason)))
        return exc.code, str(exc.reason)
    except URLError as exc:
        logger.debug(exc.reason)
        return -1, str(exc.reason)


class TelegramBotAPI:
    def __init__(self, token: str) -> None:
        self.token = token

    def get_me(self) -> Optional[Dict[str, Union[str, int]]]:
        status_code, response = make_http_request(
            "{0}{1}/getMe".format(TELEGRAM_API_ENDPOINT, self.token), insecure=True
        )
        if status_code == 200:
            result = json.loads(response)["result"]
            return result
        elif status_code == 401:
            logger.error("Telegram Bot API rejected your token, please check.")
        else:
            logger.error("Call to Bot API failed with code {0}: {1}".format(status_code, response))
        return None


def main():
    setup_logging()

    if len(sys.argv) != 2:
        print("Usage: python teleword.py <token>")
        exit(-1)

    bot_api = TelegramBotAPI(token=sys.argv[1])

    logger.debug("Trying to verify token by calling 'getMe' on Bot API...")
    result = bot_api.get_me()
    if result is not None:
        logger.info("Your username is {0} (ID: {1})".format(result["username"], result["id"]))
    else:
        logger.info("Failed to call 'getMe' on Bot API. :(")


if __name__ == "__main__":
    main()
