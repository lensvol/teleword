import argparse
import io
import json
import logging
import os
import random
import ssl
import string
from http.client import HTTPSConnection
from typing import Tuple, Union, Dict, Optional
from urllib.parse import urlparse

TELEGRAM_API_ENDPOINT = "https://api.telegram.org/bot"

logger = logging.getLogger("teleword")


def setup_logging() -> None:
    logging.basicConfig(format="[ %(asctime)s | %(levelname)-6s ] %(message)s", level=logging.DEBUG)


def make_http_request(
    url: str, insecure: bool = True, data: Optional[Dict[str, Union[int, str]]] = None
) -> Tuple[int, bytes]:
    if data is None:
        data = {}

    schema, netloc, url, params, query, fragments = urlparse(url)
    logger.debug("Sending POST request to {0}".format(url))
    body, boundary = encode_multipart_formdata(data)

    connection = HTTPSConnection(netloc, context=ssl._create_unverified_context() if insecure else None,)
    connection.connect()

    connection.putrequest("POST", url)
    connection.putheader("Content-Type", "multipart/form-data; boundary={0}".format(boundary))
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()

    connection.send(body)

    r = connection.getresponse()
    return r.status, r.read()


def encode_multipart_formdata(data: Dict[str, Union[str, int]]):
    """
    Code loosely adapted from Jason Kulatunga's answer on SO: https://stackoverflow.com/a/29332627
    (with a couple fixes to make it run on Python 3).
    """
    boundary = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(64))
    body = io.BytesIO()
    append_crlf = False

    for key, value in data.items():
        if append_crlf:
            body.write(b"\r\n")
        append_crlf = True

        block = [
            "--{0}".format(boundary),
            'Content-Disposition: form-data; name="{0}"'.format(key),
            "",
            str(value),
        ]
        body.write(("\r\n".join(block)).encode())
    body.write(b"\r\n--" + boundary.encode() + b"--\r\n\r\n")

    return body.getvalue(), boundary


class TelegramBotAPI:
    def __init__(self, token: str) -> None:
        self.token = token

    def _call_api(self, method_name: str, data: Dict[str, Union[int, str]] = None) -> Optional[bytes]:
        status_code, response = make_http_request(
            "{0}{1}/{2}".format(TELEGRAM_API_ENDPOINT, self.token, method_name), insecure=True, data=data,
        )

        logger.debug("Response status: {0}".format(status_code))
        logger.debug("Response data: {0}".format(response.decode()))

        if status_code != 200:
            logger.error("Call to Bot API failed with code {0}: {1}".format(status_code, response.decode()))
            return None

        return response

    def get_me(self) -> Optional[Dict[str, Union[str, int]]]:
        response = self._call_api("getMe")
        if response is not None:
            return json.loads(response)["result"]

        return None

    def send_message(self, chat_id, text, silent=True, mode=None):
        message = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": silent,
        }
        if mode:
            message["parse_mode"] = mode

        return self._call_api("sendMessage", data=message) is not None


def main():
    setup_logging()

    token_from_env = os.environ.get("TELEGRAM_BOT_TOKEN")

    parser = argparse.ArgumentParser()
    parser.add_argument("chat_id", metavar="CHAT_ID", type=int, help="ID of the user that should receive the message.")
    parser.add_argument("--token", metavar="API_TOKEN", type=str, help="Set Bot API token.")

    subparsers = parser.add_subparsers(help="Types of messages that can be sent:", dest="mode")

    msg_parser = subparsers.add_parser("text", help="Text message.")
    msg_parser.add_argument("text", metavar="TEXT", type=str, help="Text of the message.")
    msg_parser.add_argument("--markdown", action="store_true", help="Use Markdown formatting when sending.")
    msg_parser.add_argument("--silent", action="store_true", help="Do not notify recipient of the message.")

    arguments = parser.parse_args()
    if arguments.mode != "text":
        logger.error("Unknown mode: {0}".format(arguments.mode))
        exit(-1)

    bot_api = TelegramBotAPI(token=arguments.token or token_from_env)

    logger.debug("Trying to verify token by calling 'getMe' on Bot API...")
    result = bot_api.get_me()
    if result is not None:
        logger.info("Your username is {0} (ID: {1})".format(result["username"], result["id"]))
    else:
        logger.info("Failed to call 'getMe' on Bot API. :(")

    logger.debug("Trying to send message '{0}' to chat ID {1}...".format(arguments.text, arguments.chat_id))
    if bot_api.send_message(
        arguments.chat_id, arguments.text, mode="markdown" if arguments.markdown else None, silent=arguments.silent,
    ):
        logger.info("Successfully sent message.")


if __name__ == "__main__":
    main()
