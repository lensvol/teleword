# teleword

![Supports Python 2.7](https://img.shields.io/badge/Python-2.7-yellow?logo=python&logoColor=white) ![Python 3.2 and above](https://img.shields.io/badge/Python-3.2%2B-blue?logo=python&logoColor=white) [![License](https://img.shields.io/github/license/lensvol/pybetter)](LICENSE) [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Single-file Telegram client for Python 3 without external dependencies.

## Premise

Sometimes you just need to send a simple Telegram message without the hustle of creating _virtualenvs_, installing necessary dependencies etc. 

Why bother? Just grab `teleword.py` from this repo, `scp` it onto the machine and - voila! You can send messages and media from the command line!

## Features

* Uses only standard library.
* Works on Python 2.7, 3.2 - 3.12
* Can send text, photos and videos.
* Supports Markdown.

## Prerequisites

* You need to [create Telegram bot](https://core.telegram.org/bots#6-botfather) first and get its token.
* Somehow find out your Telegram *chat_id*.
* Set `TELEGRAM_BOT_TOKEN` environment variable (or provide it via command line argument).

## Example usage

Sending simple text:

```bash
python <YOUR CHAT_ID> text "Hello, world!"
```

Sending photo:

```shell
python <YOUR CHAT_ID> photo cutest_cat.jpg --caption "_Cutest_ cat" --markdown
```

Sending video:

```bash
python <YOUR CHAT_ID> video chasing_own_tail.mp4 --caption "Check this out" --streaming
```



## Usage

```bash
⇒  python teleword.py --help
usage: teleword.py [-h] [--token API_TOKEN] [--markdown] [--silent] [--force]
                   [--insecure] [--verbose] [--version]
                   CHAT_ID {text,photo,video} ...

positional arguments:
  CHAT_ID             ID of the chat that should receive the message.
  {text,photo,video}  Types of messages that can be sent:
    text              Text message.
    photo             Photo.
    video             Video file.

optional arguments:
  -h, --help          show this help message and exit
  --token API_TOKEN   Set Bot API token.
  --markdown          Use Markdown formatting for caption.
  --silent            Do not notify recipient of the message.
  --force             Skip sanity checks.
  --insecure          Skip certificate verification.
  --verbose           Log debug information.
  --version           show programs version number and exit
```



## TODOs

* Support sending "media groups", audio.
* Shell completion.
* Chat ID retrieval mode.
