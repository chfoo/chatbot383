import queue

from chatbot383.bot import Bot
from chatbot383.client import Client, ClientThread
from chatbot383.features import Features, Database


class App(object):
    def __init__(self, config):
        self._config = config
        inbound_queue = queue.Queue(100)
        self._main_client = Client(inbound_queue=inbound_queue)
        self._group_client = Client(inbound_queue=inbound_queue)
        self._main_client_thread = ClientThread(self._main_client)
        self._group_client_thread = ClientThread(self._group_client)
        channels = self._config['channels']
        self._bot = Bot(channels, self._main_client, self._group_client,
                        inbound_queue,
                        ignored_users=self._config.get('ignored_users'))
        database = Database(self._config['database'])
        self._features = Features(self._bot, self._config['help_text'],
                                  database, self._config)

    def run(self):
        username = self._config['username']
        password = self._config.get('password')
        main_address = self._config['main_server'].rsplit(':', 1)
        group_address = self._config['group_server'].rsplit(':', 1)
        main_address[1] = int(main_address[1])
        group_address[1] = int(group_address[1])

        self._main_client.async_connect(
            main_address[0], main_address[1], username, password=password
        )
        self._group_client.async_connect(
            group_address[0], group_address[1], username, password=password
        )

        self._main_client_thread.start()
        self._group_client_thread.start()

        self._bot.run()
