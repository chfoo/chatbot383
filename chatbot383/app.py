import queue

from chatbot383.bot import Bot
from chatbot383.client import Client, ClientThread
from chatbot383.features import Features, Database


class App(object):
    def __init__(self, config):
        self._config = config
        inbound_queue = queue.Queue(100)
        self._main_client = Client(
            inbound_queue=inbound_queue,
            twitch_char_limit='.twitch.tv:' in config['main_server'])
        self._main_client_thread = ClientThread(self._main_client)

        if 'discord_gateway_server' in config:
            self._discord_client = Client(
                inbound_queue=inbound_queue,
                twitch_char_limit=True)
            self._discord_client_thread = ClientThread(self._discord_client)
        else:
            self._discord_client = None
            self._discord_client_thread = None

        channels = self._config['channels']
        self._bot = Bot(channels, self._main_client,
                        inbound_queue,
                        ignored_users=self._config.get('ignored_users'),
                        lurk_channels=self._config.get('lurk_channels'),
                        discord_client=self._discord_client
                        )
        database = Database(self._config['database'])
        self._features = Features(self._bot, self._config['help_text'],
                                  database, self._config)

    def run(self):
        username = self._config['username']
        password = self._config.get('password')
        main_address = self._config['main_server'].rsplit(':', 1)
        main_address[1] = int(main_address[1])

        main_connect_factory = Client.new_connect_factory(
            hostname=main_address[0], use_ssl=self._config.get('ssl'))

        self._main_client.async_connect(
            main_address[0], main_address[1], username, password=password,
            connect_factory=main_connect_factory
        )

        self._main_client_thread.start()

        if 'discord_gateway_server' in self._config:
            discord_password = self._config['discord_token']
            discord_address = self._config['discord_gateway_server'].rsplit(':', 1)
            discord_address[1] = int(discord_address[1])
            self._discord_client.async_connect(
                discord_address[0], discord_address[1], username,
                password=discord_password,
            )

            self._discord_client_thread.start()

        self._bot.run()
