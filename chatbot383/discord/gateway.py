"""Gateway to Discord via a IRC server proxy"""
# Using old Python 3.4 asyncio syntax for backwards compatibility :(

import asyncio
import enum

import logging
import re
import string

import discord


_logger = logging.getLogger(__name__)

CHANNEL_PREFIX = '&'
PRESENCE_CHANNEL = '&#+!presence'


class IRCServer:
    def __init__(self, port: int=10006):
        self._port = port
        self._stop_event = asyncio.Event()

    @asyncio.coroutine
    def run(self):
        server_coro = asyncio.start_server(self._handler, '127.0.0.1', self._port)
        yield from server_coro
        yield from self._stop_event.wait()

    @asyncio.coroutine
    def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        _logger.info('Connected to client.')

        session = IRCSession(reader, writer)
        try:
            yield from session.handle()
        except ConnectionError:
            _logger.info('Connection closed.')
        except Exception:
            _logger.exception('Server handler error. Closing.')
            writer.close()
            self._stop_event.set()

        _logger.info('Client disconnect')
        writer.close()


class IRCSession:
    class State(enum.Enum):
        wait_for_login = 'wait_for_login'
        logged_in = 'logged_in'

    class ClientCommand:
        def __init__(self, line: str):
            self.line = line
            self.args = line.split(' ')
            self.command = self.args[0].lower()
            self.text = line.split(' :', 1)[-1]

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._state = self.State.wait_for_login
        self._discord_client = discord.Client()
        self._channel_ids = set()
        self._username = None
        self._password = None
        self._discord_connect_task = None

    @asyncio.coroutine
    def handle(self):
        futures = set()
        futures.add(self._reader.readline())

        while True:
            done, pending = yield from asyncio.wait(futures, return_when=asyncio.FIRST_COMPLETED)
            futures = set(pending)

            for future in done:
                result = yield from future

                if isinstance(result, bytes):
                    line = result.decode('utf8', 'replace').strip('\r\n')

                    if not line:
                        _logger.info('Disconnected from client.')
                        if not self._discord_client.is_closed:
                            self._discord_client.close()
                        return

                    command = self.ClientCommand(line)

                    if self._state == self.State.wait_for_login:
                        success = yield from self._handle_login(command)

                        if success:
                            futures.add(self._discord_client.wait_for_message())
                    else:
                        yield from self._handle_message_command(command)

                    futures.add(self._reader.readline())
                else:
                    message = result

                    yield from self._handle_discord_message(message)
                    futures.add(self._discord_client.wait_for_message())

            futures.update(pending)

    @classmethod
    def escape_tag_value(cls, text: str) -> str:
        return text.replace('\\', '\\\\').replace('\r', '\\r')\
            .replace('\n', '\\n').replace(' ', '\\s').replace(';', '\\:')

    @asyncio.coroutine
    def _reply(self, *args, tags=None, username=None):
        str_args = (str(arg) for arg in args)
        if tags:
            tag_str = ';'.join(
                '{}={}'.format(
                    self.escape_tag_value(key), self.escape_tag_value(value))
                for key, value in tags.items()
            )
            self._writer.write(b'@')
            self._writer.write(tag_str.encode('utf8', 'replace'))
            self._writer.write(b' ')

        source = 'server.local'
        if username:
            if username is True:
                username = self._username
            source = '{}!{}@{}'.format(username, username, source)

        text = ':{} {}'.format(source, ' '.join(str_args))

        if '\n' in text or '\r' in text:
            raise ValueError('Naughty newlines found')

        self._writer.write(text.encode('utf8', 'replace'))
        self._writer.write(b'\r\n')
        yield from self._writer.drain()

    @asyncio.coroutine
    def _handle_login(self, command: ClientCommand) -> bool:
        if command.command == 'nick':
            self._username = command.args[1]

        elif command.command == 'pass':
            self._password = command.args[1]

        elif command.command == 'user':
            pass
        else:
            yield from self._reply('421', command.command, ':Unknown command')

        if self._username and self._password:
            _logger.info('Logging into Discord.')

            try:
                yield from self._discord_client.login(self._password)
            except discord.LoginFailure:
                yield from self._reply('464', ':Login error')
                self._writer.close()
                return False

            _logger.info('Waiting for Discord client..')
            self._discord_connect_task = asyncio.get_event_loop().create_task(self._discord_client.connect())
            yield from self._discord_client.wait_until_ready()

            _logger.info('Discord login success!')
            self._state = self.State.logged_in

            yield from self._reply('001', self._username, ':')
            yield from self._reply('002', self._username, ':')
            yield from self._reply('003', self._username, ':')
            yield from self._reply('004', self._username, ':')
            yield from self._reply('375', self._username, ':')
            yield from self._reply('376', self._username, ':')

            return True

        return False

    @asyncio.coroutine
    def _handle_message_command(self, command: ClientCommand):
        command_table = {
            'ping': self._ping_command,
            'join': self._join_command,
            'part': self._part_command,
            'privmsg': self._privmsg_command
        }

        func = command_table.get(command.command)

        if func:
            yield from func(command)
        else:
            yield from self._reply('421', command.command, ':Unknown command')

    @asyncio.coroutine
    def _ping_command(self, command: ClientCommand):
        yield from self._reply('PONG', ':' + command.text)

    @asyncio.coroutine
    def _join_command(self, command: ClientCommand):
        channels = command.args[1].split(',')

        for channel in channels:
            if not channel.startswith(CHANNEL_PREFIX):
                yield from self._reply(
                    '403', ':Channel name must start with & symbol'
                )
            else:
                channel = channel.replace(CHANNEL_PREFIX, '', 1)
                _logger.info('Join channel %s', channel)
                self._channel_ids.add(channel)
                yield from self._reply(
                    'JOIN', CHANNEL_PREFIX + channel, username=True
                )

    @asyncio.coroutine
    def _part_command(self, command: ClientCommand):
        channel = command.args[1]
        channel = channel.replace(CHANNEL_PREFIX, '', 1)
        _logger.info('Part channel %s', channel)
        self._channel_ids.remove(channel)
        yield from self._reply(
            'PART', CHANNEL_PREFIX + channel, username=True
        )

    @asyncio.coroutine
    def _privmsg_command(self, command: ClientCommand):
        channel = command.args[1]

        if channel == PRESENCE_CHANNEL:
            yield from self._presence_command(command)
        elif channel.startswith(CHANNEL_PREFIX):
            channel = channel.replace(CHANNEL_PREFIX, '', 1)

            if channel not in self._channel_ids:
                yield from self._reply('442', ':Not joined in that channel')
            else:
                yield from self._discord_client.send_message(
                    self._discord_client.get_channel(channel),
                    command.text
                )
        else:
            try:
                user = yield from self._discord_client.get_user_info(channel)
            except discord.NotFound:
                yield from self._reply('401', ':User not found')
            else:
                yield from self._discord_client.send_message(
                    user, command.text
                )

    @asyncio.coroutine
    def _presence_command(self, command: ClientCommand):
        if command.text:
            game = discord.Game(name=command.text)
        else:
            game = None
        try:
            yield from self._discord_client.change_presence(game=game)
        except discord.DiscordException:
            _logger.error('Could not update game "%s"', game)

    @asyncio.coroutine
    def _handle_discord_message(self, message: discord.Message):
        if not message.channel:
            return

        if message.channel.id not in self._channel_ids:
            return

        yield from self._reply(
            'PRIVMSG', CHANNEL_PREFIX + message.channel.id,
            ':' + message.content.replace('\n', ' ').replace('\r', ' '),
            tags={
                'display-name': message.author.display_name,
                'user-id': message.author.id
            },
            username=self.escape_username(message.author.name)
        )

    @classmethod
    def escape_username(cls, name: str) -> str:
        name = cls.escape_tag_value(re.sub(r'[\x00-\x1f]', '', name))
        name = re.sub(r'[:!@]', '_', name)

        if name and name[0] not in string.ascii_letters + string.digits:
            name = name[1:]

        return name


def main():
    logging.basicConfig(level=logging.INFO)

    gateway = IRCServer()

    event_loop = asyncio.get_event_loop()
    event_loop.run_until_complete(gateway.run())


if __name__ == '__main__':
    main()
