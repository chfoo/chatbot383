import logging
import queue
import ssl
import threading
import functools
import re

import irc.client
import irc.strings
import irc.connection

_logger = logging.getLogger(__name__)

IRC_RATE_LIMIT = (20 - 0.5) / 30
RECONNECT_INTERVAL = 60 * 2


class InvalidTextError(ValueError):
    pass


class Client(irc.client.SimpleIRCClient):
    def __init__(self, inbound_queue=None, twitch_char_limit=False):
        super().__init__()

        irc.client.ServerConnection.buffer_class.errors = 'replace'
        self.connection.set_rate_limit(IRC_RATE_LIMIT)
        self._running = True
        self._inbound_queue = inbound_queue or queue.Queue(100)
        self._outbound_queue = queue.Queue(10)

        self.twitch_char_limit = twitch_char_limit
        if twitch_char_limit:
            assert self.connection.send_raw
            assert self.connection._prep_message
            self.connection._prep_message = ClientMonkeyPatch._prep_message

        self.reactor.execute_every(300, self._keep_alive)

    @property
    def inbound_queue(self):
        return self._inbound_queue

    @property
    def outbound_queue(self):
        return self._outbound_queue

    def _dispatcher(self, connection, event):
        # Override parent class
        _logger.debug("_dispatcher: %s", event.type)

        do_nothing = lambda c, e: None
        method = getattr(self, "_on_" + event.type, do_nothing)
        method(connection, event)

    @classmethod
    def new_connect_factory(cls, hostname=None, use_ssl=False):
        if use_ssl:
            context = ssl.create_default_context()
            wrapper = functools.partial(context.wrap_socket, server_hostname=hostname)
            connect_factory = irc.connection.Factory(wrapper=wrapper)
        else:
            connect_factory = irc.connection.Factory()

        return connect_factory

    def async_connect(self, *args, **kwargs):
        self.reactor.execute_delayed(
            0, functools.partial(self.autoconnect, *args, **kwargs))

    def autoconnect(self, *args, **kwargs):
        _logger.info('Connecting %s...', args[:2] or self.connection.server_address)
        try:
            if args:
                self.connect(*args, **kwargs)
            else:
                self.connection.reconnect()
        except irc.client.ServerConnectionError:
            _logger.exception('Connect failed.')
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        self.reactor.execute_delayed(RECONNECT_INTERVAL, self.autoconnect)

    def _on_disconnect(self, connection, event):
        _logger.info('Disconnected %s!', self.connection.server_address)

        if self._running:
            self._schedule_reconnect()

    def stop(self):
        self._running = False
        self.reactor.disconnect_all()

    def process(self):
        self._process_outbound_messages()

        self.reactor.process_once(0.2)

    @classmethod
    def validate_text(cls, text):
        if re.search(r'[\x00-\x1f]', text):
            raise InvalidTextError('Forbidden control characters')

    def _on_welcome(self, connection, event):
        _logger.info('Logged in to server %s.', self.connection.server_address)
        self.connection.cap('REQ', 'twitch.tv/membership')
        self.connection.cap('REQ', 'twitch.tv/commands')
        self.connection.cap('REQ', 'twitch.tv/tags')

        self._inbound_queue.put({
            'client': self,
            'event_type': 'welcome'
        })

    def _on_pubmsg(self, connection, event):
        channel = irc.strings.lower(event.target)
        nick = self.tags_to_dict(event.tags).get('display-name') or event.source.nick
        username = irc.strings.lower(event.source.nick)

        if not event.arguments:
            return

        text = event.arguments[0]

        self._inbound_queue.put({
            'client': self,
            'event_type': 'pubmsg',
            'channel': channel,
            'nick': nick,
            'username': username,
            'text': text
        })

    def _on_action(self, connection, event):
        channel = irc.strings.lower(event.target)
        nick = self.tags_to_dict(event.tags).get('display-name') or event.source.nick
        username = irc.strings.lower(event.source.nick)

        if not event.arguments:
            return

        text = event.arguments[0]

        self._inbound_queue.put({
            'client': self,
            'event_type': 'action',
            'channel': channel,
            'nick': nick,
            'username': username,
            'text': text
        })

    def _on_pubnotice(self, connection, event):
        channel = irc.strings.lower(event.target)
        text = event.arguments[0]

        self._inbound_queue.put({
            'client': self,
            'event_type': 'pubnotice',
            'channel': channel,
            'text': text
        })

    def _on_clearchat(self, connection, event):
        channel = irc.strings.lower(event.target)
        nick = event.arguments[0] if event.arguments else None
        username = irc.strings.lower(nick) if nick else None

        self._inbound_queue.put({
            'client': self,
            'event_type': 'clearchat',
            'channel': channel,
            'nick': nick,
            'username': username,
        })

    def _on_whisper(self, connection, event):
        nick = event.source.nick
        username = irc.strings.lower(nick)
        text = event.arguments[0]

        self._inbound_queue.put({
            'client': self,
            'event_type': 'whisper',
            'nick': nick,
            'username': username,
            'text': text
        })

    def _on_join(self, connection, event):
        channel = irc.strings.lower(event.target)
        nick = event.source.nick
        username = irc.strings.lower(event.source.nick)

        self._inbound_queue.put({
            'client': self,
            'event_type': 'join',
            'channel': channel,
            'nick': nick,
            'username': username,
        })

    def _on_part(self, connection, event):
        channel = irc.strings.lower(event.target)
        nick = event.source.nick
        username = irc.strings.lower(event.source.nick)

        self._inbound_queue.put({
            'client': self,
            'event_type': 'part',
            'channel': channel,
            'nick': nick,
            'username': username,
        })

    def _process_outbound_messages(self):
        for dummy in range(5):
            try:
                item = self._outbound_queue.get_nowait()
            except queue.Empty:
                break

            if not self.connection.connected:
                _logger.error('Not connected. Dropping output item %s', item)
                return

            _logger.debug('Process outbound queue item %s %s',
                          item, self.connection.server_address)

            outbound_message_type = item['message_type']

            if outbound_message_type == 'privmsg':
                target = item['target']
                text = item['text']

                try:
                    self.validate_text(target)
                    self.validate_text(text)
                except InvalidTextError:
                    _logger.exception('Skipping messages')
                    continue

                if item['format_action']:
                    self.connection.action(target, text)
                else:
                    self.connection.privmsg(target, text)

            elif outbound_message_type == 'join':
                _logger.info('Join %s', item['channel'])
                self.connection.join(item['channel'])

            elif outbound_message_type == 'part':
                _logger.info('Part %s', item['channel'])
                self.connection.part(item['channel'])

            else:
                raise ValueError('Unknown message type {}'
                                 .format(outbound_message_type))

            self.reactor.process_once(0.01)

    def privmsg(self, target, text, action=False):
        self._outbound_queue.put({
            'message_type': 'privmsg',
            'target': target,
            'text': text,
            'format_action': action
        })

    def join(self, channel):
        self._outbound_queue.put({
            'message_type': 'join',
            'channel': channel
        })

    def part(self, channel):
        self._outbound_queue.put({
            'message_type': 'part',
            'channel': channel
        })

    def get_nickname(self, lower=False):
        if lower:
            return irc.strings.lower(self.connection.get_nickname())
        else:
            return self.connection.get_nickname()

    @classmethod
    def tags_to_dict(cls, tags):
        return dict([
            (item.get('key'), item.get('value'))
            for item in tags
        ])

    def _keep_alive(self):
        if self.connection.is_connected():
            self.connection.ping('keep-alive')


class ClientThread(threading.Thread):
    def __init__(self, client):
        super().__init__()
        self.daemon = True
        self._client = client
        self._running = False

    def run(self):
        self._running = True

        while self._running:
            self._client.process()

    def stop(self):
        self._running = False


class ClientMonkeyPatch:
    @staticmethod
    def _prep_message(string):
        # The string should not contain any carriage return other than the
        # one added here.
        if '\n' in string:
            msg = "Carriage returns not allowed in privmsg(text)"
            raise irc.client.InvalidCharacters(msg)
        bytes = string.encode('utf-8') + b'\r\n'
        # According to the RFC http://tools.ietf.org/html/rfc2812#page-6,
        # clients should not transmit more than 512 bytes.
        # if len(bytes) > 512:
        #     msg = "Messages limited to 512 bytes including CR/LF"
        #     raise irc.client.MessageTooLong(msg)
        return bytes
