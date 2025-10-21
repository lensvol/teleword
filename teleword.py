from __future__ import absolute_import, print_function, unicode_literals, division

import sys  # noqa

import argparse
import io
import json
import logging
import mimetypes
import os
import random
import ssl
import string
from http.client import HTTPSConnection
from tempfile import mkstemp

PY2 = sys.version_info[0] == 2  # noqa

if PY2:
    from urlparse import urlparse
else:
    from urllib.parse import urlparse

__VERSION__ = "0.1.0"

GODADDY_ROOT_CERTIFICATE = """
-----BEGIN CERTIFICATE-----
MIIEADCCAuigAwIBAgIBADANBgkqhkiG9w0BAQUFADBjMQswCQYDVQQGEwJVUzEh
MB8GA1UEChMYVGhlIEdvIERhZGR5IEdyb3VwLCBJbmMuMTEwLwYDVQQLEyhHbyBE
YWRkeSBDbGFzcyAyIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MB4XDTA0MDYyOTE3
MDYyMFoXDTM0MDYyOTE3MDYyMFowYzELMAkGA1UEBhMCVVMxITAfBgNVBAoTGFRo
ZSBHbyBEYWRkeSBHcm91cCwgSW5jLjExMC8GA1UECxMoR28gRGFkZHkgQ2xhc3Mg
MiBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTCCASAwDQYJKoZIhvcNAQEBBQADggEN
ADCCAQgCggEBAN6d1+pXGEmhW+vXX0iG6r7d/+TvZxz0ZWizV3GgXne77ZtJ6XCA
PVYYYwhv2vLM0D9/AlQiVBDYsoHUwHU9S3/Hd8M+eKsaA7Ugay9qK7HFiH7Eux6w
wdhFJ2+qN1j3hybX2C32qRe3H3I2TqYXP2WYktsqbl2i/ojgC95/5Y0V4evLOtXi
EqITLdiOr18SPaAIBQi2XKVlOARFmR6jYGB0xUGlcmIbYsUfb18aQr4CUWWoriMY
avx4A6lNf4DD+qta/KFApMoZFv6yyO9ecw3ud72a9nmYvLEHZ6IVDd2gWMZEewo+
YihfukEHU1jPEX44dMX4/7VpkI+EdOqXG68CAQOjgcAwgb0wHQYDVR0OBBYEFNLE
sNKR1EwRcbNhyz2h/t2oatTjMIGNBgNVHSMEgYUwgYKAFNLEsNKR1EwRcbNhyz2h
/t2oatTjoWekZTBjMQswCQYDVQQGEwJVUzEhMB8GA1UEChMYVGhlIEdvIERhZGR5
IEdyb3VwLCBJbmMuMTEwLwYDVQQLEyhHbyBEYWRkeSBDbGFzcyAyIENlcnRpZmlj
YXRpb24gQXV0aG9yaXR5ggEAMAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQEFBQAD
ggEBADJL87LKPpH8EsahB4yOd6AzBhRckB4Y9wimPQoZ+YeAEW5p5JYXMP80kWNy
OO7MHAGjHZQopDH2esRU1/blMVgDoszOYtuURXO1v0XJJLXVggKtI3lpjbi2Tc7P
TMozI+gciKqdi0FuFskg5YmezTvacPd+mSYgFFQlq25zheabIZ0KbIIOqPjCDPoQ
HmyW74cNxA9hi63ugyuV+I6ShHI56yDqg+2DzZduCLzrTia2cyvk0/ZM/iZx4mER
dEr/VxqHD3VILs9RaRegAhJhldXRQLIQTO7ErBBDpqWeCtWVYpoNz4iCxTIM5Cuf
ReYNnyicsbkqWletNw+vHX/bvZ8=
-----END CERTIFICATE-----
"""


if not PY2:
    try:
        from typing import Tuple, Union, Dict, Mapping

        # We explicitly silence F401 here because those are used inside type comments
        from typing import Optional, Iterable  # noqa: F401

        Attachments = Mapping[Tuple[str, str], bytes]
        Envelope = Dict[str, Union[str, int]]
        Response = Mapping[str, Union[int, str]]
    except ImportError:
        # Apparently, this is a Python 3 version without `typing` module
        pass

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

    def __init__(self, patterns):
        # type: (Iterable[str]) -> None
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
        format="[ %(asctime)s | %(levelname)-6s ] %(message)s",
        level=logging.DEBUG if verbose else logging.INFO,
    )
    redacting_filter = RedactingFilter([p for p in redacted_patterns if p])
    logging.getLogger("teleword").addFilter(redacting_filter)


def make_http_request(url, data=None, files=None, certificate=None):
    # type: (str, Optional[Envelope], Optional[Attachments], str) -> Tuple[int, bytes]
    if data is None:
        data = {}

    if files is None:
        files = {}

    schema, netloc, url, params, query, fragments = urlparse(url)
    logger.debug("Sending POST request to {0}".format(url))
    body, boundary = encode_multipart_formdata(data, files)

    # Sadly, ssl_create_default_context() only available in Python 3.4+
    if not PY2 and sys.version_info[1] >= 4:
        if certificate:
            ssl_context = ssl.create_default_context(cafile=certificate)
        else:
            ssl_context = ssl._create_default_https_context()
        connection = HTTPSConnection(netloc, context=ssl_context)
    else:
        from ssl import SSLContext

        ssl_context = SSLContext(protocol=ssl.PROTOCOL_SSLv23)
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_verify_locations(cafile=certificate)
        connection = HTTPSConnection(netloc, context=ssl_context, check_hostname=True)

    connection.connect()

    connection.putrequest("POST", url)
    connection.putheader(
        "Content-Type", "multipart/form-data; boundary={0}".format(boundary)
    )
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()

    connection.send(body)

    r = connection.getresponse()

    return r.status, r.read()


def encode_multipart_formdata(data, files):
    # type: (Envelope, Attachments) -> Tuple[bytes, str]

    # Code loosely adapted from Jason Kulatunga's answer on SO: https://stackoverflow.com/a/29332627
    # (with a couple fixes to make it run on Python 3).

    boundary = "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(64)
    )
    body = io.BytesIO()
    append_crlf = False

    for key, value in data.items():
        if append_crlf:
            body.write(b"\r\n")
        append_crlf = True

        encoded_value = str(value)
        if PY2:
            encoded_value = encoded_value.decode("utf-8")

        block = [
            "--{0}".format(boundary),
            'Content-Disposition: form-data; name="{0}"'.format(key),
            "",
            encoded_value,
        ]
        body.write(("\r\n".join(block)).encode("utf-8", "surrogateescape"))

    for (field, filename), contents in files.items():
        if append_crlf:
            body.write(b"\r\n")
        append_crlf = True

        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        block = [
            "--{0}".format(boundary),
            'Content-Disposition: form-data; name="{0}"; filename="{1}"'.format(
                field, filename
            ),
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
        self.insecure = False
        self.silent = False  # type: bool
        self.parse_mode = None  # type: Optional[str]
        self.chat_id = chat_id  # type: int

    def enable_insecure_connection(self):
        self.insecure = True

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
        envelope = {
            "disable_notifications": "true" if self.silent else "false",
            "chat_id": self.chat_id,
        }  # type: Envelope
        if self.parse_mode:
            envelope["parse_mode"] = self.parse_mode

        return envelope

    def _call_api(self, method_name, data=None, attachments=None):
        # type: (str, Envelope, Mapping[str, str]) -> Optional[bytes]
        if attachments is None:
            attachments = {}

        files = {}
        for field, path in attachments.items():
            with open(path, "rb") as fp:
                _, filename = os.path.split(path)
                files[(field, filename)] = fp.read()

        if self.insecure:
            cafile_path = None
            logger.info("Skipping certificate verification as requested by user!")
        else:
            (fd, cafile_path) = mkstemp(text=True)
            os.write(fd, GODADDY_ROOT_CERTIFICATE.encode())
            os.close(fd)

        try:
            status_code, response = make_http_request(
                "{0}{1}/{2}".format(TELEGRAM_API_ENDPOINT, self.token, method_name),
                certificate=cafile_path,
                data=data,
                files=files,
            )
        finally:
            if cafile_path:
                os.remove(cafile_path)

        logger.debug("Response status: {0}".format(status_code))
        logger.debug("Response data: {0}".format(response.decode()))

        if status_code != 200:
            logger.error(
                "Call to Bot API failed with code {0}: {1}".format(
                    status_code, response.decode()
                )
            )
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

        logger.debug(
            "Trying to send text message '{0}' to chat ID {1}...".format(text, chat_id)
        )
        return self._call_api("sendMessage", data=message, attachments={}) is not None

    def send_photo(self, chat_id, path, caption=""):
        # type: (int, str, str) -> bool
        message = self._generate_envelope()  # type: Envelope
        if caption:
            message["caption"] = caption

        logger.debug(
            "Trying to send photo '{0}' to chat ID {1}...".format(path, chat_id)
        )
        return (
            self._call_api("sendPhoto", data=message, attachments={"photo": path})
            is not None
        )

    def send_video(self, chat_id, path, caption="", streaming=False):
        # type: (int, str, str, bool) -> bool
        message = self._generate_envelope()  # type: Envelope
        if caption:
            message["caption"] = caption
        if streaming:
            message["supports_streaming"] = True

        logger.debug(
            "Trying to send video '{0}' to chat ID {1}...".format(path, chat_id)
        )
        return (
            self._call_api("sendVideo", data=message, attachments={"video": path})
            is not None
        )


def sanity_check_upload(expected_mimetype, path_to_upload, limit):
    # type: (str, str, int) -> None
    stat_result = os.stat(path_to_upload)
    if stat_result.st_size > limit:
        raise BadUploadError(
            "File is too big for upload ({0} MB), limit is 5 MB".format(
                stat_result.st_size // (1024 * 1024)
            )
        )

    actual_mimetype, _ = mimetypes.guess_type(path_to_upload)
    if actual_mimetype != expected_mimetype:
        raise BadUploadError(
            "File should have type '{0}', found '{1}'".format(
                expected_mimetype, actual_mimetype
            )
        )


def parse_cmdline_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "chat_id",
        metavar="CHAT_ID",
        type=int,
        help="ID of the chat that should receive the message.",
    )
    parser.add_argument(
        "--token", metavar="API_TOKEN", type=str, help="Set Bot API token."
    )
    parser.add_argument(
        "--markdown", action="store_true", help="Use Markdown formatting for caption."
    )
    parser.add_argument(
        "--silent", action="store_true", help="Do not notify recipient of the message."
    )
    parser.add_argument("--force", action="store_true", help="Skip sanity checks.")
    parser.add_argument(
        "--insecure", action="store_true", help="Skip certificate verification."
    )
    parser.add_argument("--verbose", action="store_true", help="Log debug information.")
    parser.add_argument(
        "--version", action="version", version="%(prog)s {0}".format(__VERSION__)
    )

    subparsers = parser.add_subparsers(
        help="Types of messages that can be sent:", dest="mode"
    )

    msg_parser = subparsers.add_parser("text", help="Text message.")
    msg_parser.add_argument(
        "text",
        metavar="TEXT",
        type=str,
        help="Text of the message ('-' to read it from STDIN).",
    )

    photo_parser = subparsers.add_parser("photo", help="Photo.")
    photo_parser.add_argument(
        "path", metavar="PATH", type=str, help="Path to the photo file."
    )
    photo_parser.add_argument(
        "--caption", metavar="TEXT", type=str, help="Caption for the photo."
    )

    video_parser = subparsers.add_parser("video", help="Video file.")
    video_parser.add_argument(
        "path", metavar="PATH", type=str, help="Path to the video file."
    )
    video_parser.add_argument(
        "--caption", metavar="TEXT", type=str, help="Caption for the photo."
    )
    video_parser.add_argument(
        "--streaming", action="store_true", help="This video file supports streaming."
    )

    return parser.parse_args()


def bail(message):
    logger.error(message)
    sys.exit(-1)


def load_token_from_file():
    possible_paths = [
        ".teleword_token",
        os.path.expanduser("~/.teleword_token"),
    ]

    for token_path in possible_paths:
        if not os.path.exists(token_path):
            continue

        with open(token_path, "r") as token_file:
            return token_file.read()

    return None


def main():
    arguments = parse_cmdline_arguments()
    token_from_env = os.environ.get("TELEGRAM_BOT_TOKEN")
    token_from_file = load_token_from_file()

    bot_token = arguments.token or token_from_env or token_from_file
    setup_logging([bot_token] if bot_token else [], verbose=arguments.verbose)

    if not bot_token:
        bail(
            "Bot API token was not provided as an argument, environment variable or provided via file!"
        )

    try:
        bot_api = TelegramBotAPI(
            token=bot_token,
            chat_id=arguments.chat_id,
        )
        if arguments.silent:
            bot_api.disable_notifications()
        if arguments.markdown:
            bot_api.set_parse_mode("markdown")
        if arguments.insecure:
            bot_api.enable_insecure_connection()

        if arguments.mode == "text":
            if arguments.text == "-":
                text_to_send = sys.stdin.read()
            else:
                text_to_send = arguments.text

            if bot_api.send_message(arguments.chat_id, text_to_send):
                logger.info("Successfully sent message.")
        elif arguments.mode == "photo":
            if not arguments.force:
                sanity_check_upload("image/jpeg", arguments.path, PHOTO_SIZE_LIMIT)

            if bot_api.send_photo(
                arguments.chat_id, arguments.path, caption=arguments.caption
            ):
                logger.info("Successfully sent photo.")
            else:
                bail("Failed to send photo.")
        elif arguments.mode == "video":
            if not arguments.force:
                sanity_check_upload("video/mp4", arguments.path, VIDEO_SIZE_LIMIT)

            if bot_api.send_video(
                arguments.chat_id,
                arguments.path,
                caption=arguments.caption,
                streaming=arguments.streaming,
            ):
                logger.info("Successfully sent video.")
            else:
                bail("Failed to send video.")
    except BadUploadError as exc:
        bail(str(exc))


if __name__ == "__main__":
    main()


__all__ = [
    "Attachments",
    "BadUploadError",
    "Envelope",
    "GODADDY_ROOT_CERTIFICATE",
    "PHOTO_SIZE_LIMIT",
    "RedactingFilter",
    "Response",
    "TELEGRAM_API_ENDPOINT",
    "TelegramBotAPI",
    "VIDEO_SIZE_LIMIT",
    "bail",
    "encode_multipart_formdata",
    "logger",
    "main",
    "make_http_request",
    "parse_cmdline_arguments",
    "sanity_check_upload",
    "setup_logging",
]
