import argparse
import io
import json
import logging
import mimetypes
import os
import random
import ssl
import string
import sys
from http.client import HTTPSConnection
from typing import Tuple, Union, Dict, Optional, Mapping, Iterable, Any
from urllib.parse import urlparse


__VERSION__ = "0.1.0"

Attachments = Mapping[Tuple[str, str], bytes]
Envelope = Dict[str, Union[str, int]]
Response = Mapping[str, Union[int, str]]

TELEGRAM_API_ENDPOINT = "https://api.telegram.org/bot"
VIDEO_SIZE_LIMIT = 20 * 1024 * 1024
PHOTO_SIZE_LIMIT = 5 * 1024 * 1024


class BadUploadError(Exception):
    pass


class RedactingFilter(logging.Filter):
    """
    Taken almost verbatim from
    https://relaxdiego.com/2014/07/logging-in-python.html#redacting-logs-using-a-filter
    """

    def __init__(self, patterns: Iterable[str]):
        super(RedactingFilter, self).__init__()
        self._patterns = patterns

    def filter(self, record):
        record.msg = self.redact(record.msg)
        if isinstance(record.args, dict):
            for k in record.args.keys():
                record.args[k] = self.redact(record.args[k])
        else:
            record.args = tuple(self.redact(arg) for arg in record.args)
        return True

    def redact(self, msg):
        # type: (str) -> str
        msg = isinstance(msg, str) and msg or str(msg)
        for pattern in self._patterns:
            msg = msg.replace(pattern, "<REDACTED>")
        return msg


logger = logging.getLogger("teleword")


def setup_logging(redacted_patterns, verbose=False):
    # type: (Iterable[str], bool) -> None
    logging.basicConfig(
        format="[ %(asctime)s | %(levelname)-6s ] %(message)s", level=logging.DEBUG if verbose else logging.INFO
    )
    redacting_filter = RedactingFilter([p for p in redacted_patterns if p])
    logging.getLogger("teleword").addFilter(redacting_filter)


def make_http_request(
    url, insecure=True, data=None, files=None
):
    # type: (str, bool, Optional[Envelope], Optional[Attachments]) -> Tuple[int, bytes]
    if data is None:
        data = {}

    if files is None:
        files = {}

    schema, netloc, url, params, query, fragments = urlparse(url)
    logger.debug("Sending POST request to {0}".format(url))
    body, boundary = encode_multipart_formdata(data, files)

    connection = HTTPSConnection(netloc, context=ssl._create_unverified_context() if insecure else None)
    connection.connect()

    connection.putrequest("POST", url)
    connection.putheader("Content-Type", "multipart/form-data; boundary={0}".format(boundary))
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()

    connection.send(body)

    r = connection.getresponse()

    return r.status, r.read()


def encode_multipart_formdata(data, files):
    # type: (Envelope, Attachments) -> Tuple[bytes, str]

    # Code loosely adapted from Jason Kulatunga's answer on SO: https://stackoverflow.com/a/29332627
    # (with a couple fixes to make it run on Python 3).

    boundary = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(64))
    body = io.BytesIO()
    append_crlf = False

    for key, value in data.items():
        if append_crlf:
            body.write(b"\r\n")
        append_crlf = True

        block = ["--{0}".format(boundary), 'Content-Disposition: form-data; name="{0}"'.format(key), "", str(value)]
        body.write(("\r\n".join(block)).encode())

    for (field, filename), contents in files.items():
        if append_crlf:
            body.write(b"\r\n")
        append_crlf = True

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        block = [
            "--{0}".format(boundary),
            'Content-Disposition: form-data; name="{0}"; filename="{1}"'.format(field, filename),
            "Content-Type: {0}".format(content_type),
            "Content-Length: {0}".format(len(contents)),
            "",
        ]
        body.write(("\r\n".join(block)).encode())
        body.write(b"\r\n")
        body.write(contents)

    body.write(b"\r\n--" + boundary.encode() + b"--\r\n\r\n")

    return body.getvalue(), boundary


class TelegramBotAPI:
    def __init__(self, token, chat_id):
        # type: (str, int) -> None

        self.token = token  # type: str
        self.silent = False  # type: bool
        self.parse_mode = None  # type: Optional[str]
        self.chat_id = chat_id  # type: int

    def disable_notifications(self):
        # type: () -> None
        self.silent = True

    def enable_notifications(self):
        # type: () -> None
        self.silent = False

    def set_parse_mode(self, mode):
        # type: (str) -> None
        self.parse_mode = mode

    def _generate_envelope(self):
        # type: () -> Envelope
        envelope = {"disable_notifications": "true" if self.silent else "false", "chat_id": self.chat_id}  # type: Envelope
        if self.parse_mode:
            envelope["parse_mode"] = self.parse_mode

        return envelope

    def _call_api(
        self, method_name, data=None, attachments=None
    ):
        # type: (str, Envelope, Mapping[str, str]) -> Optional[bytes]
        if attachments is None:
            attachments = {}

        files = {}
        for field, path in attachments.items():
            with open(path, "rb") as fp:
                _, filename = os.path.split(path)
                files[(field, filename)] = fp.read()

        status_code, response = make_http_request(
            "{0}{1}/{2}".format(TELEGRAM_API_ENDPOINT, self.token, method_name), insecure=True, data=data, files=files
        )

        logger.debug("Response status: {0}".format(status_code))
        logger.debug("Response data: {0}".format(response.decode()))

        if status_code != 200:
            logger.error("Call to Bot API failed with code {0}: {1}".format(status_code, response.decode()))
            return None

        return response

    def get_me(self):
        # type: () -> Optional[Response]
        response = self._call_api("getMe")
        if response is not None:
            return json.loads(response)["result"]

        return None

    def send_message(self, chat_id, text):
        # type: (int, str) -> bool
        message = self._generate_envelope()  # type: Envelope
        message["text"] = text

        logger.debug("Trying to send text message '{0}' to chat ID {1}...".format(text, chat_id))
        return self._call_api("sendMessage", data=message, attachments={}) is not None

    def send_photo(self, chat_id, path, caption=""):
        # type: (int, str, str) -> bool
        message = self._generate_envelope()  # type: Envelope
        if caption:
            message["caption"] = caption

        logger.debug("Trying to send photo '{0}' to chat ID {1}...".format(path, chat_id))
        return self._call_api("sendPhoto", data=message, attachments={"photo": path}) is not None

    def send_video(self, chat_id, path, caption="", streaming=False):
        # type: (int, str, str, bool) -> bool
        message = self._generate_envelope()  # type: Envelope
        if caption:
            message["caption"] = caption
        if streaming:
            message["supports_streaming"] = True

        logger.debug("Trying to send video '{0}' to chat ID {1}...".format(path, chat_id))
        return self._call_api("sendVideo", data=message, attachments={"video": path}) is not None


def sanity_check_upload(expected_mimetype, path_to_upload, limit):
    # type: (str, str, int) -> None
    stat_result = os.stat(path_to_upload)
    if stat_result.st_size > limit:
        raise BadUploadError(
            "File is too big for upload ({0} MB), limit is 5 MB".format(stat_result.st_size // (1024 * 1024))
        )

    actual_mimetype, _ = mimetypes.guess_type(path_to_upload)
    if actual_mimetype != expected_mimetype:
        raise BadUploadError("File should have type '{0}', found '{1}'".format(expected_mimetype, actual_mimetype))


def parse_cmdline_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("chat_id", metavar="CHAT_ID", type=int, help="ID of the chat that should receive the message.")
    parser.add_argument("--token", metavar="API_TOKEN", type=str, help="Set Bot API token.")
    parser.add_argument("--markdown", action="store_true", help="Use Markdown formatting for caption.")
    parser.add_argument("--silent", action="store_true", help="Do not notify recipient of the message.")
    parser.add_argument("--force", action="store_true", help="Skip sanity checks.")
    parser.add_argument("--verbose", action="store_true", help="Log debug information.")
    parser.add_argument('--version', action='version', version="%(prog)s {0}".format(__VERSION__))

    subparsers = parser.add_subparsers(help="Types of messages that can be sent:", dest="mode")

    msg_parser = subparsers.add_parser("text", help="Text message.")
    msg_parser.add_argument("text", metavar="TEXT", type=str, help="Text of the message.")

    photo_parser = subparsers.add_parser("photo", help="Photo.")
    photo_parser.add_argument("path", metavar="PATH", type=str, help="Path to the photo file.")
    photo_parser.add_argument("--caption", metavar="TEXT", type=str, help="Caption for the photo.")

    video_parser = subparsers.add_parser("video", help="Video file.")
    video_parser.add_argument("path", metavar="PATH", type=str, help="Path to the video file.")
    video_parser.add_argument("--caption", metavar="TEXT", type=str, help="Caption for the photo.")
    video_parser.add_argument("--streaming", action="store_true", help="This video file supports streaming.")

    return parser.parse_args()


def bail(message):
    logger.error(message)
    sys.exit(-1)


def main():
    arguments = parse_cmdline_arguments()
    token_from_env = os.environ.get("TELEGRAM_BOT_TOKEN")

    setup_logging([token_from_env or arguments.token], verbose=arguments.verbose)

    if not token_from_env and not arguments.token:
        bail("Telegram API token not specified as an argument and not set in environment! Exiting...")

    try:
        bot_api = TelegramBotAPI(token=arguments.token or token_from_env, chat_id=arguments.chat_id)
        if arguments.silent:
            bot_api.disable_notifications()
        if arguments.markdown:
            bot_api.set_parse_mode("markdown")

        if arguments.mode == "text":
            if bot_api.send_message(arguments.chat_id, arguments.text):
                logger.info("Successfully sent message.")
        elif arguments.mode == "photo":
            if not arguments.force:
                sanity_check_upload("image/jpeg", arguments.path, PHOTO_SIZE_LIMIT)

            if bot_api.send_photo(arguments.chat_id, arguments.path, caption=arguments.caption):
                logger.info("Successfully sent photo.")
            else:
                bail("Failed to send photo.")
        elif arguments.mode == "video":
            if not arguments.force:
                sanity_check_upload("video/mp4", arguments.path, VIDEO_SIZE_LIMIT)

            if bot_api.send_video(
                arguments.chat_id, arguments.path, caption=arguments.caption, streaming=arguments.streaming
            ):
                logger.info("Successfully sent video.")
            else:
                bail("Failed to send video.")
    except BadUploadError as exc:
        bail(str(exc))


if __name__ == "__main__":
    main()
