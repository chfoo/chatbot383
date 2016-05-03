import logging
import queue
import random
import re
import itertools
import sched
import time

import irc.strings

from chatbot383.util import split_utf8

_logger = logging.getLogger(__name__)


class InboundMessageSession(object):
    def __init__(self, message, bot, client):
        self._message = message
        self._bot = bot
        self._client = client
        self.match = None
        self.skip_rate_limit = False

    @property
    def message(self):
        return self._message

    @property
    def bot(self):
        return self._bot

    @property
    def client(self):
        return self._client

    def reply(self, text, me=False, multiline=False):
        self._bot.send_text(self._message['channel'], text, me=me,
                            reply_to=self._message['nick'],
                            multiline=multiline)

    def say(self, text, me=False, multiline=False):
        self._bot.send_text(self._message['channel'], text, me=me,
                            multiline=multiline)


class Bot(object):
    def __init__(self, channels, main_client, inbound_queue,
                 ignored_users=None, lurk_channels=()):
        self._channels = frozenset(irc.strings.lower(channel) for channel in channels)
        self._lurk_channels = frozenset(irc.strings.lower(channel) for channel in lurk_channels)
        self._main_client = main_client
        self._inbound_queue = inbound_queue
        self._ignored_users = frozenset(ignored_users or ())
        self._user_limiter = Limiter(min_interval=5)
        self._channel_spam_limiter = Limiter(min_interval=1)
        self._scheduler = sched.scheduler()

        self._commands = []
        self._message_handlers = []

        self.register_message_handler('welcome', self._join_channels)

        assert self._main_client.inbound_queue == inbound_queue

    def register_command(self, command_regex, func):
        self._commands.append((command_regex, func))

    def register_message_handler(self, event_type, func):
        self._message_handlers.append((event_type, func))

    @property
    def scheduler(self):
        return self._scheduler

    @classmethod
    def is_group_chat(cls, channel_name):
        return channel_name.startswith('#_')

    @classmethod
    def is_text_safe(cls, text):
        if text == '':
            return True

        if len(text) > 400 or len(text.encode('utf-8', 'replace')) > 450:
            return False

        if text[0] in './!`_':
            return False

        if re.search(r'[\x00-\x1f]', text):
            return False

        return True

    def run(self):
        while True:
            self._scheduler.run(blocking=False)

            try:
                item = self._inbound_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            else:
                client = item['client']
                _logger.debug('Process inbound queue item %s %s',
                              client.connection.server_address, item)
                self._process_message(item, client)

    def send_text(self, channel, text, me=False, reply_to=None,
                  multiline=False):
        channel = irc.strings.lower(channel)
        client = self._main_client

        if reply_to:
            text = '@{}, {}'.format(reply_to, text)

        if multiline:
            lines = self.split_multiline(text)
        else:
            lines = (text,)

        del text

        for line in lines:
            if not self.is_text_safe(line) or channel not in self._channels:
                _logger.info('Discarded message %s %s',
                             ascii(channel), ascii(line))
                return

            client.privmsg(channel, line, action=me)

    def send_whisper(self, username, text):
        if not self.is_text_safe(text):
            _logger.info('Discarded message %s %s', ascii(username), ascii(text))
            return

        text = '/w {} {}'.format(username, text)

        self._main_client.privmsg('#jtv', text)

    @classmethod
    def split_multiline(cls, text, max_length=400):
        for index, part in enumerate(split_utf8(text, max_length)):
            if index == 0:
                yield part
            else:
                yield '(...) ' + part

    def join(self, channel):
        client = self._main_client

        client.join(channel)

    def _process_message(self, message, client):
        session = InboundMessageSession(message, self, client)

        self._process_message_handlers(session)

        event_type = message['event_type']

        if event_type in ('pubmsg', 'action'):
            self._process_text_commands(session)

    def _process_text_commands(self, session):
        message = session.message
        text = message['text']
        username = message['username']
        channel = message['channel']
        our_username = session.client.get_nickname(lower=True)

        if username in self._ignored_users:
            return

        if channel in self._lurk_channels:
            return

        if username != our_username:
            if not self._user_limiter.is_ok(username):
                return
            if not self._channel_spam_limiter.is_ok(channel):
                return

            for pattern, command_func in self._commands:
                match = re.match(pattern, text)

                if match:
                    session.match = match
                    command_func(session)

                    if not session.skip_rate_limit:
                        self._user_limiter.update(username)
                        self._channel_spam_limiter.update(channel)

                    break

    def _process_message_handlers(self, session):
        event_type = session.message['event_type']

        for command_event_type, command_func in self._message_handlers:
            if event_type == command_event_type:
                command_func(session)

    def _join_channels(self, session):
        channels = self._channels | self._lurk_channels

        for channel in channels:
            session.bot.join(channel)


class Limiter(object):
    def __init__(self, min_interval=5):
        self._min_interval = min_interval
        self._table = {}

    def is_ok(self, key):
        if key not in self._table:
            return True

        time_now = time.time()

        return time_now - self._table[key] > self._min_interval

    def update(self, key):
        self._table[key] = time.time()

        if len(self._table) > 500:
            key = random.choice(self._table)
            del self._table[key]
