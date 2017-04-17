#!/usr/bin/env python3

import argparse
import asyncio
import collections
import contextlib
import ctypes
import json
import logging
import platform
import traceback

import attr
import requests
import requests.exceptions

"""
TODO
gmail notifier

show caught exceptions only if more than 3 last 5 iterations. Eg >50% failures
keep a list of last 5 executions
print only if >3 failed and current one is failing
in other words we don't want to print in this case:  ok fail fail fail ok,
because we are currently ok


use streams api as api.twitch.tv/kraken/streams?channel=chan1,chan2
to reduce num requests

a more generic recurring event reminder? supporting expiration/end dates?
    backup reminder
    property tax
    birthday reminder

grafici.txt parser/reminder
    maybe add notifications that an event will happen (like 1 day or 7 days
    before)
show recently expired events

rss?
hackernews top stories? https://github.com/HackerNews/API
just use http://hckrnews.com/ for now


javascript/html gui?

    vue + websockets? https://websockets.readthedocs.io/en/stable/intro.html / aiohttp.web websockets
        monitor close and error events to reconnect
        have a small div with websocket state
    vue + EventSource
    vue + axios + lodash. setInterval on vue ready() lifecycle hook - polling
    vue + socketio (sux, weird protocol)
    javascript has nice 2d engines, see pixijs.com and http://html5gameengine.com/

qt ui?
sdl2 gui?
pygame gui, so you can click the text and the browser will take you there
pygame is sdl 1.2, sdl2 is out tho.

log screens with diff verbosity
    diff notifiers in diff colors, so you can ignore the spam easily?
    a box with all text (incl errors) and one with just the normal info
screen with "currently live" streams and when they were last checked


In v5, you can also use the search/channels endpoint to find a channel and get the ID.
kraken/users?login=dallas,dallasnchains  up to 100
"""

"""
seems we need to create windows without stealing focus in order to show a
tooltip/traytip

qt has WA_ShowWithoutActivating
http://www.archivum.info/qt-interest@trolltech.com/2009-07/00045/Re-(Qt-interest)-does-WA_ShowWithoutActivating-work-with-QMainWindow.html
http://stackoverflow.com/questions/966688/show-window-in-qt-without-stealing-focus

"""

TWITCH_CLIENT_ID = 'km6hcouu2ulc8ageas889k9m8y8v2ss'
TWITCH = 'twitch'
HITBOX = 'hitbox'
STREAM_API_DATA = {
    TWITCH: {
        'url': 'https://api.twitch.tv/kraken/streams/{}',
        'headers': {
            'Accept': 'application/vnd.twitchtv.v3+json',
            # id is public, so it can be shared
            # https://github.com/justintv/Twitch-API#rate-limits
            'Client-ID': TWITCH_CLIENT_ID,
            },
        'message': "http://twitch.tv/{} is {}",  # abc is LIVE or offline
        'session': requests.Session(),
        'previous_state': dict(),
    },

    HITBOX: {
        'url': 'http://api.hitbox.tv/media/live/{}',
        'headers': {},
        'message': 'hitbox.tv/{} is {}',
        'session': requests.Session(),
        'previous_state': dict(),
    },
}
LIVE = 'LIVE'
OFFLINE = 'offline'

REQUEST_TIMEOUT = 10
ONE_HOUR_SEC = 60 * 60

ABV_API_URL = 'https://api.abv.bg/api/checkMail/json?username={}&password={}'

QLR_STREAM_NAME = 'qlrankstv'
QLR_MSG_LIVE = 'http://twitch.tv/qlrankstv {} LIVE'
QLR_MSG_OFF = 'http://twitch.tv/qlrankstv {} offline'


class StateTracker:
    STATE_UNKNOWN = 'STATE_UNKNOWN'
    STATE_UP = 'STATE_UP'
    STATE_DOWN = 'STATE_DOWN'

    def __init__(self):
        self._old_state = dict()

    def set_state(self, key, state):
        old = self._old_state.get(key, StateTracker.STATE_UNKNOWN)
        self._old_state[key] = state

        if old == StateTracker.STATE_UNKNOWN and state == StateTracker.STATE_DOWN:
            # don't notify from unknown to down
            return

        if old == state:
            # don't notify if no change in state
            return

        return state


def session_get_timeout(session, url, timeout=REQUEST_TIMEOUT):
    return session.get(url, timeout=timeout)


@asyncio.coroutine
def session_get_in_executor(loop, session, url, timeout):
    future = loop.run_in_executor(
            None, session_get_timeout, session, url, timeout)
    resp = yield from future
    return resp


@contextlib.contextmanager
def safe_requests_logged():
    try:
        yield
    except (requests.exceptions.ConnectionError,  # noqa
            requests.exceptions.ReadTimeout,
            requests.exceptions.ChunkedEncodingError,
            json.decoder.JSONDecodeError,
            ) as e:
        logging.debug('recovered from ' + repr(e))
        # logging.debug(traceback.format_exc())
        pass


def log_lastchance_exc(func):
    # note for generators
    def inner(*args, **kwargs):
        try:
            yield from func(*args, **kwargs)
        except Exception:
            logging.error('last chance exception')
            logging.error(traceback.format_exc())
    return inner


Stream = collections.namedtuple('Stream', ['name', 'type', 'comment'])
Player = collections.namedtuple('Player', ['name', 'comment'])


@asyncio.coroutine
def followed_streams(streams):

    @asyncio.coroutine
    def update_stream_info(stream):
        streamdata = STREAM_API_DATA[stream.type]
        url = streamdata['url']
        session = streamdata['session']
        headers = streamdata['headers']
        previous_state = streamdata['previous_state']
        session.headers.update(headers)
        future = loop.run_in_executor(
            None, session_get_timeout, session, url.format(stream.name))
        resp = yield from future

        resp_json = None
        try:
            # logging.info('checking {}'.format(stream['name']))
            resp_json = json.loads(resp.text)
            if stream.type == TWITCH:
                if resp_json['stream'] is not None:
                    liveness = LIVE
                else:
                    liveness = OFFLINE
            elif stream.type == HITBOX:
                liveness = OFFLINE
                if ('livestream' in resp_json
                   and int(resp_json['livestream'][0]['media_is_live'])):
                    liveness = LIVE
            else:
                raise NotImplementedError('unknown stream type')

        except (ValueError, KeyError):
            logging.debug("can't parse reply for {}".format(stream.name))
            if resp_json is not None:
                logging.debug('value error json')
                logging.debug(resp_json)
            return

        if liveness != previous_state.get(stream.name, OFFLINE):
            msg_name_comment = stream.name
            if stream.comment:
                msg_name_comment += ' (' + stream.comment + ')'
            info_msg = streamdata['message'].format(msg_name_comment, liveness)
            logging.info(info_msg)
        previous_state[stream.name] = liveness

    try:
        logging.debug('hi from followed streams')
        logging.debug('started with ' + str(streams))
        loop = asyncio.get_event_loop()

        while 1:
            for stream in streams:
                with safe_requests_logged():
                    yield from update_stream_info(stream)
                yield from asyncio.sleep(5)

            yield from asyncio.sleep(10 * 60)  # secs
    except Exception as e:
        logging.error('last chance exception')
        logging.error(traceback.format_exc())


@asyncio.coroutine
def get_abv(users_dict):
    try:
        logging.debug('hi from get_abv')
        logging.debug('started with ' + str(users_dict.keys()))
        loop = asyncio.get_event_loop()

        session = requests.Session()
        session.headers.update({'content-type': 'application/json'})

        while 1:
            for user in users_dict:
                passwd = users_dict[user]

                future1 = loop.run_in_executor(
                    None,
                    session_get_timeout, session,
                    ABV_API_URL.format(user, passwd))
                with safe_requests_logged():
                    response1 = yield from future1
                    resp = json.loads(response1.text)
                    # logging.info(response1.text)
                    if resp['message']['status'] != 0:

                        logging.error('status: {} text: {}'.format(
                            resp['message']['status'],
                            resp['message']['text']))
                    else:
                        folders = resp['mail']['folders']
                        for folder in folders:
                            logging.info('{} {} {}'.format(
                                user, folder['name'], folder['newMsgCount']))

                yield from asyncio.sleep(60 * 20)  # secs

    except Exception:
        logging.error(traceback.format_exc())

    logging.error('bye')



async def backup_reminder():
    logging.debug('hi from backup reminder')
    while True:
        await asyncio.sleep(60 * 60 * 24 * 10)
        logging.info('time to backup! freefilesync on desktop and ftp folder')



async def time_tick(seconds):
    logging.debug('hi from hour tick')
    while True:
        await asyncio.sleep(seconds)
        logging.info('tick {}'.format(seconds))


@asyncio.coroutine
def qlranks_inspect(players, tick_min=15):
    """
    notify if a player is in the title of qlrankstv
    """

    def process_reply(json_reply, previous_state):
        stream = json_reply.get('stream')
        if stream is None:
            return

        stream_title = stream['channel']['status']
        stream_title = stream_title.lower()

        # to show offlines before onlines
        output = collections.deque()
        for player in players:
            if player in stream_title:
                if previous_state.get(player, OFFLINE) != LIVE:
                    output.append(QLR_MSG_LIVE.format(player))
                    previous_state[player] = LIVE
            else:  # not in stream_title
                if previous_state.get(player, OFFLINE) != OFFLINE:
                    output.appendleft(QLR_MSG_OFF.format(player))
                    previous_state[player] = OFFLINE
        for msg in output:
            logging.info(msg)

    players = [player.lower() for player in players]
    logging.debug('hi from qlranks inspect')
    logging.debug('started with ' + str(players))
    try:
        session = STREAM_API_DATA[TWITCH]['session']
        headers = STREAM_API_DATA[TWITCH]['headers']
        url = STREAM_API_DATA[TWITCH]['url']
        loop = asyncio.get_event_loop()
        previous_state = dict()  # player to liveness
        while True:
            session.headers.update(headers)
            future = loop.run_in_executor(
                None, session_get_timeout, session, url.format(QLR_STREAM_NAME))

            with safe_requests_logged():
                resp = yield from future
                try:
                    json_reply = json.loads(resp.text)
                    process_reply(json_reply, previous_state)

                except ValueError:
                    logging.debug(traceback.format_exc())

            yield from asyncio.sleep(tick_min * 60)
    except Exception:
        logging.error('last chance exception')
        logging.error(traceback.format_exc())


@asyncio.coroutine
@log_lastchance_exc
def cs_streams(api_url, streams):
    loop = asyncio.get_event_loop()
    session = requests.Session()
    poll_interval = 15 * 60
    streams = set(streams)
    logging.debug('hi from cs_streams {}'.format(streams))
    state_tracker = StateTracker()
    while True:
        with safe_requests_logged():

            resp = yield from session_get_in_executor(loop, session, api_url, REQUEST_TIMEOUT)
            j = resp.json()

            streams_online = set()
            for record in j:
                username = record['username']
                if username in streams:
                    streams_online.add(username)

            for stream in streams_online:
                state = state_tracker.set_state(stream, StateTracker.STATE_UP)

                if state:
                    logging.info('{} is {}'.format(stream, state))

            for stream in streams - streams_online:
                state = state_tracker.set_state(stream, StateTracker.STATE_DOWN)

                if state:
                    logging.info('{} is {}'.format(stream, state))
        yield from asyncio.sleep(poll_interval)


def get_twitch_requests_session():
    session = requests.Session()
    session.headers.update({
        'Accept': 'application/vnd.twitchtv.v5+json',
        # id is public, so it can be shared
        'Client-ID': TWITCH_CLIENT_ID,
    })
    return session


@attr.s(frozen=True)
class TwitchStream:
    name = attr.ib()
    comment = attr.ib()
    api_id = attr.ib()
    game = attr.ib()

    @classmethod
    def from_config(cls, stream):
        if isinstance(stream, dict):
            stream = cls(name=stream['name'].lower(), comment=stream['comment'], api_id=None, game=None)
        else:
            stream = cls(name=stream.lower(), comment='', api_id=None, game=None)
        return stream


async def resolve_logins_batch(streams_list, session, loop):
    # https://dev.twitch.tv/docs/v5/guides/using-the-twitch-api/
    found = []
    logins = dict()
    for s in streams_list:
        logins[s.name] = s
    logins_qry = ','.join(logins.keys())
    url = 'https://api.twitch.tv/kraken/users?login=' + logins_qry
    resp = await session_get_in_executor(loop, session, url, REQUEST_TIMEOUT)
    users = resp.json()['users']
    for user in users:
        stream = logins[user['name']]
        stream = attr.assoc(stream, api_id=user['_id'])
        found.append(stream)
    return found


async def resolve_logins(all_streams, session, loop):
    # resolved, not_found dicts of name -> TwitchStream
    batch_size = 10
    sleep_time_sec = 2
    resolved_streams = dict()

    all_streams_list = list(all_streams.values())
    for i in range(0, len(all_streams_list), batch_size):
        stream_batch = all_streams_list[i:i+batch_size]
        resolved_batch = await resolve_logins_batch(stream_batch, session, loop)
        resolved_streams.update({
            s.name: s for s in resolved_batch
        })
        await asyncio.sleep(sleep_time_sec, loop=loop)
    not_found_streams = dict()
    for s in all_streams.values():
        if s.name not in resolved_streams:
            not_found_streams[s.name] = s
    return resolved_streams, not_found_streams


async def twitch_check_online_batch(streams_list, session, loop):
    streams = {s.name: s for s in streams_list}
    channels = [s.api_id for s in streams_list]
    channels_qry = ','.join(channels)
    url = 'https://api.twitch.tv/kraken/streams?channel=' + channels_qry
    resp = await session_get_in_executor(loop, session, url, REQUEST_TIMEOUT)
    resp_streams = resp.json()['streams']
    online = dict()
    for s in resp_streams:
        name = s['channel']['name']
        game = s['game']
        stream = streams[name]
        stream = attr.assoc(stream, game=game)
        online[name] = stream
    return online

async def twitch_check_online(streams, session, loop):
    batch_size = 10
    sleep_time_sec = 2
    stream_list = list(streams.values())
    online = dict()
    for i in range(0, len(streams), batch_size):
        stream_batch = stream_list[i:i+batch_size]
        online_batch = await twitch_check_online_batch(stream_batch, session, loop)
        online.update(online_batch)
        await asyncio.sleep(sleep_time_sec, loop)

    offline = dict()
    for s in streams.values():
        if s.name not in online:
            offline[s.name] = s
    return online, offline



@log_lastchance_exc
async def track_twitch_streams(streams_conf, loop):
    notification_msg_fmt = 'twitch.tv/{name} {comment} {game} {state}'
    session = get_twitch_requests_session()
    state_tracker = StateTracker()
    streams = dict()  # user -> TwitchStream
    for s in streams_conf:
        stream = TwitchStream.from_config(s)
        streams[stream.name] = stream

    logging.debug('hi from track_twitch_streams {}'.format(sorted(list(streams))))
    # resolve logins to user api id
    streams, not_found = await resolve_logins(streams, session, loop)

    for s in not_found.values():
        logging.warning('USER NOT FOUND {}'.format(s))

    while True:
        # batches of api ids, check if online, convert back to logins
        streams_online, streams_offline = await twitch_check_online(streams, session, loop)

        for s in streams_online.values():
            state_changed = state_tracker.set_state(s.name, StateTracker.STATE_UP)
            if state_changed:
                logging.info(notification_msg_fmt.format(name=s.name, comment=s.comment, game=s.game, state=StateTracker.STATE_UP))

        for s in streams_offline.values():
            state_changed = state_tracker.set_state(s.name, StateTracker.STATE_DOWN)
            if state_changed:
                logging.info(notification_msg_fmt.format(name=s.name, comment=s.comment, game=s.game, state=StateTracker.STATE_UP))








def read_config(filename):
    with open(filename) as f:
        config = json.loads(f.read())
    return config


def append_streams(all_streams, json_streams, streamtype):
    for s in json_streams:
        if isinstance(s, str):
            all_streams.append(Stream(s, streamtype, None))
        elif isinstance(s, dict):
            all_streams.append(Stream(s['name'], streamtype, s['comment']))


def main():

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(name)s %(levelname)s L%(lineno)d %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    for logger_name in [
            'requests',
            'asyncio'
        ]:
        alogger = logging.getLogger(logger_name)
        alogger.setLevel(logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument('CONFIGPATH', type=str, help='path to secrets.json')
    args = parser.parse_args()
    config = read_config(args.CONFIGPATH)

    logging.debug('hi from notifier')
    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    if platform.uname().system == 'Windows':
        ctypes.windll.kernel32.SetConsoleTitleA(b'notify')

    twitch_streams = config.get('twitch_streams', None)

    abv_accounts = config.get('abv_accounts', {})

    qlranks_players = config.get('qlranks_players', set())

    cs_streams_url, *cs_streams_list = config.get('cs_streams')

    tasks = [
        asyncio.ensure_future(get_abv(abv_accounts)),
        asyncio.ensure_future(backup_reminder()),
        asyncio.ensure_future(time_tick(ONE_HOUR_SEC)),
        #asyncio.ensure_future(qlranks_inspect(qlranks_players)),
        asyncio.ensure_future(cs_streams(cs_streams_url, cs_streams_list)),
        asyncio.ensure_future(track_twitch_streams(twitch_streams, loop)),
    ]

    #loop.run_until_complete(asyncio.wait(tasks))
    loop.run_forever()
    loop.close()

if __name__ == '__main__':
    main()
