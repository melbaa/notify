import asyncio

import pytest
import requests

import melbalabs.notify.notify as notify

@pytest.fixture
def config():
    return notify.read_config('secrets.json')

@pytest.fixture
def twitch_streams(config):
    streams_conf = config.get('twitch_streams')

    streams = dict()
    for s in streams_conf:
        stream = notify.TwitchStream.from_config(s)
        streams[stream.name] = stream
    return streams

@pytest.fixture
def loop():
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    return loop

@pytest.fixture
def session():
    return notify.get_twitch_requests_session()
