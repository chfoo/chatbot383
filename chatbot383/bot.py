import logging
import queue
import random
import re
import itertools
import sched
import time

import collections
import irc.strings
from typing import Optional

from chatbot383.client import Client
from chatbot383.util import split_utf8, grouper
import chatbot383.discord.gateway
import chatbot383.util

_logger = logging.getLogger(__name__)


class InboundMessageSession(object):
    def __init__(self, message: dict, bot: 'Bot', client: Client):
        self._message = message
        self._bot = bot
        self._client = client
        self.match = None
        self.skip_rate_limit = False

    @property
    def message(self) -> dict:
        return self._message

    @property
    def bot(self) -> 'Bot':
        return self._bot

    @property
    def client(self) -> Client:
        return self._client

    def reply(self, text, me=False, multiline=False, escape_links=False):
        if self.get_platform_name() == 'discord':
            reply_to = self._message['user_id']
        else:
            reply_to = self._message['nick']

        self._bot.send_text(self._message['channel'], text, me=me,
                            reply_to=reply_to,
                            multiline=multiline,
                            discord_reply=self.get_platform_name() == 'discord',
                            escape_links=escape_links
                            )

    def whisper(self, text):
        if self.get_platform_name() == 'discord':
            self._bot.send_discord_private_message(
                self._message['user_id'], text
            )
        else:
            self._bot.send_whisper(self._message['username'], text)

    def say(self, text, me=False, multiline=False):
        self._bot.send_text(self._message['channel'], text, me=me,
                            multiline=multiline)

    def get_platform_name(self) -> str:
        if self.message['channel'].startswith(chatbot383.discord.gateway.CHANNEL_PREFIX):
            return 'discord'
        else:
            return 'twitch'


RegisteredCommandInfo = collections.namedtuple(
    'RegisteredCommandInfo', [
        'command_regex', 'func', 'ignore_rate_limit'
    ]
)


class Bot(object):
    def __init__(self, channels, main_client: Client,
                 inbound_queue: queue.Queue,
                 ignored_users=None, lurk_channels=(),
                 discord_client: Optional[Client]=None):
        self._channels = frozenset(irc.strings.lower(channel) for channel in channels)
        self._lurk_channels = frozenset(irc.strings.lower(channel) for channel in lurk_channels)
        self._main_client = main_client
        self._discord_client = discord_client
        self._inbound_queue = inbound_queue
        self._ignored_users = frozenset(ignored_users or ())
        self._user_limiter = Limiter(min_interval=3)
        self._channel_spam_limiter = Limiter(min_interval=0.2)
        self._scheduler = sched.scheduler()

        self._commands = []
        self._message_handlers = []

        self.register_message_handler('welcome', self._join_channels)

        assert self._main_client.inbound_queue == inbound_queue

    def register_command(self, command_regex, func, ignore_rate_limit=False):
        self._commands.append(RegisteredCommandInfo(command_regex, func, ignore_rate_limit))

    def register_message_handler(self, event_type, func):
        self._message_handlers.append((event_type, func))

    @property
    def scheduler(self) -> sched.scheduler:
        return self._scheduler

    @classmethod
    def is_group_chat(cls, channel_name: str) -> bool:
        return channel_name.startswith('#_')

    @property
    def user_limiter(self) -> 'Limiter':
        return self._user_limiter

    @property
    def channel_spam_limiter(self) -> 'Limiter':
        return self._channel_spam_limiter

    @classmethod
    def is_text_safe(cls, text: str, allow_command_prefix: bool=False,
                     max_length: int=400, max_byte_length: int=450) -> bool:
        if text == '':
            return True

        if len(text) > max_length or len(text.encode('utf-8', 'replace')) > max_byte_length:
            return False

        if text[0] in './!`_' and not allow_command_prefix:
            return False

        if re.search(r'[\x00-\x1f]', text):
            return False

        return True

    @property
    def twitch_char_limit(self) -> bool:
        return self._main_client.twitch_char_limit

    @classmethod
    def strip_unsafe_chars(cls, text: str) -> str:
        return re.sub(r'[\x00-\x1f]', '', text)

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
                  multiline=False, discord_reply=False, escape_links=False):
        channel = irc.strings.lower(channel)

        if self._discord_client and self.get_platform_name(channel) == 'discord':
            client = self._discord_client
        else:
            client = self._main_client

        if escape_links and client == self._discord_client:
            text = chatbot383.util.escape_links(text)

        if reply_to:
            if discord_reply:
                text = '<@{}>, {}'.format(reply_to, text)
            else:
                text = '@{}, {}'.format(reply_to, text)

        if client == self._discord_client:
            max_length = 2000
            max_byte_length = max_length * 4
        elif client.twitch_char_limit:
            max_length = 500
            max_byte_length = 1800
        else:
            max_length = 400
            max_byte_length = 400

        if multiline:
            if client.twitch_char_limit:
                lines = self.split_multiline(text, max_length - 100,
                                             split_bytes=False)
            else:
                lines = self.split_multiline(text, max_byte_length)
        else:
            lines = (text,)

        del text

        for line in lines:
            line = self.strip_unsafe_chars(line)

            if not self.is_text_safe(
                    line, max_length=max_length,
                    max_byte_length=max_byte_length) or \
                    channel not in self._channels:
                _logger.info('Discarded message %s %s',
                             ascii(channel), ascii(line))
                return

            client.privmsg(channel, line, action=me)

    def send_whisper(self, username, text, allow_command_prefix=False):
        text = self.strip_unsafe_chars(text)

        if not self.is_text_safe(text, allow_command_prefix=allow_command_prefix):
            _logger.info('Discarded message %s %s', ascii(username), ascii(text))
            return

        text = '/w {} {}'.format(username, text)

        self._main_client.privmsg('#jtv', text)

    def send_discord_private_message(self, username, text, allow_command_prefix=False):
        text = self.strip_unsafe_chars(text)

        if not self.is_text_safe(text, allow_command_prefix=allow_command_prefix):
            _logger.info('Discarded message %s %s', ascii(username), ascii(text))
            return

        self._discord_client.privmsg(username, text)

    def set_discord_presence(self, game_text: str):
        if self._discord_client:
            self._discord_client.privmsg(
                chatbot383.discord.gateway.PRESENCE_CHANNEL, game_text)

    @classmethod
    def split_multiline(cls, text, max_length=400, split_bytes=True):
        if split_bytes:
            parts = split_utf8(text, max_length)
        else:
            parts = [''.join(part) for part in grouper(text, max_length, '')]

        for index, part in enumerate(parts):
            if index == 0:
                yield part
            else:
                yield '(...) ' + part

    def join(self, channel):
        if self.get_platform_name(channel) == 'discord':
            client = self._discord_client
        else:
            client = self._main_client

        client.join(channel)

    def _process_message(self, message, client):
        session = InboundMessageSession(message, self, client)

        self._process_message_handlers(session)

        event_type = message['event_type']

        if event_type in ('pubmsg', 'action'):
            self._process_text_commands(session)

    def _process_text_commands(self, session: InboundMessageSession):
        message = session.message
        text = message['text']
        username = message['username']
        channel = message['channel']
        our_username = session.client.get_nickname(lower=True)

        if username in self._ignored_users:
            return

        if channel in self._lurk_channels:
            return

        if username == our_username:
            return

        for registered_command_info in self._commands:
            pattern = registered_command_info.command_regex
            command_func = registered_command_info.func
            ignore_rate_limit = registered_command_info.ignore_rate_limit
            match = re.match(pattern, text)

            if match:
                if not ignore_rate_limit:
                    if not self._user_limiter.is_ok(username):
                        return
                    if not self._channel_spam_limiter.is_ok(channel):
                        return

                session.match = match
                command_func(session)

                if not session.skip_rate_limit and not ignore_rate_limit:
                    self._user_limiter.update(username)
                    self._channel_spam_limiter.update(channel)

                break

    def _process_message_handlers(self, session: InboundMessageSession):
        event_type = session.message['event_type']

        for command_event_type, command_func in self._message_handlers:
            if event_type == command_event_type:
                command_func(session)

    def _join_channels(self, session: InboundMessageSession):
        channels = self._channels | self._lurk_channels

        if session.client == self._discord_client:
            channels = filter(
                lambda chan: self.get_platform_name(chan) == 'discord',
                channels
            )
        else:
            channels = filter(
                lambda chan: self.get_platform_name(chan) == 'twitch',
                channels
            )

        grouped_channels = (
            ','.join(channel for channel in group if channel)
            for group in grouper(channels, 10)
        )

        for channel in grouped_channels:
            session.bot.join(channel)

    @classmethod
    def get_platform_name(cls, channel: str) -> str:
        if channel.startswith(chatbot383.discord.gateway.CHANNEL_PREFIX):
            return 'discord'
        else:
            return 'twitch'


class Limiter(object):
    def __init__(self, min_interval: float=5):
        self._min_interval = min_interval
        self._table = {}

    def is_ok(self, key) -> bool:
        if key not in self._table:
            return True

        time_now = time.time()

        return time_now - self._table[key] > self._min_interval

    def update(self, key, offset=0.0):
        self._table[key] = time.time() + offset

        if len(self._table) > 500:
            key = random.choice(self._table)
            del self._table[key]
