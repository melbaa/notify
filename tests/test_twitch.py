import melbalabs.notify.notify as notify

def test_echo():
    print('hi')

def test_config(config):
    assert config

def test_resolve_logins(twitch_streams, session, loop):
    fut = notify.resolve_logins(twitch_streams, session, loop)
    twitch_streams, not_found_streams = loop.run_until_complete(fut)
    for s in not_found_streams.values():
        print(s.name)
    for s in twitch_streams.values():
        assert s.api_id is not None

def test_check_online(twitch_streams, session, loop):
    fut = notify.resolve_logins(twitch_streams, session, loop)
    twitch_streams, not_found_streams = loop.run_until_complete(fut)

    fut = notify.twitch_check_online(twitch_streams, session, loop)
    online, offline = loop.run_until_complete(fut)
    print('online', online)
    print('offline', offline)
