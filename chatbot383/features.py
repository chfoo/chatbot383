import collections
import random
import re

from chatbot383.roar import gen_roar


class Features(object):
    def __init__(self, bot, help_text):
        self._bot = bot
        self._help_text = help_text
        self._recent_messages = collections.defaultdict(lambda: collections.deque(maxlen=10))

        bot.register_message_handler('pubmsg', self._collect_recent_message)
        bot.register_message_handler('action', self._collect_recent_message)
        bot.register_command(r'!(groudonger)?help$|\s', self._help_command)
        bot.register_command(r'!groudon(ger)?$|\s', self._roar_command)
        bot.register_command(r's/(.+)/(.+)/([gi]*)', self._regex_command)
        bot.register_command(r'!rip (.{,50})$', self._rip_command)
        bot.register_command(r'!klappa$|\s', self._klappa_command)

    def _collect_recent_message(self, session):
        if session.message['event_type'] in ('pubmsg', 'action'):
            channel = session.message['channel']
            self._recent_messages[channel].append(session.message)

    def _help_command(self, session):
        session.reply('{} {}'.format(gen_roar(), self._help_text))

    def _roar_command(self, session):
        session.say('{} {} {}'.format(gen_roar(), gen_roar(), gen_roar().upper()))

    def _regex_command(self, session):
        search_pattern = session.match.group(1)
        replacement = session.match.group(2)
        options = session.match.group(3)
        flags = 0
        count = 1

        if 'i' in options:
            flags |= re.IGNORECASE

        if 'g' in options:
            count = 0

        try:
            pattern = re.compile(search_pattern, flags)
        except re.error as error:
            session.reply('{} {}!'.format(gen_roar(), error.args[0].title()))
            return

        for history_message in reversed(self._recent_messages[session.message['channel']]):
            text = history_message['text']

            if text.startswith('s/'):
                continue

            if pattern.search(text):
                try:
                    new_text = pattern.sub(replacement, text, count=count)
                except re.error as error:
                    session.reply('{} {}!'.format(gen_roar(), error.args[0].title()))
                    return

                if len(new_text) > 400:
                    session.reply('{} Message length exceeds my capabilities!'
                                  .format(gen_roar()))
                    return

                if random.random() < 0.1:
                    new_text = gen_roar()

                session.say(
                    '{user} wishes to correct {target_user}: {text}'.format(
                        user=session.message['nick'],
                        target_user=history_message['nick'],
                        text=new_text
                    )
                )
                return

        session.reply('{} Your request does not apply to any recent messages!'
                      .format(gen_roar()))

    def _rip_command(self, session):
        session.say('{} Rest in peace, {}. Press F to pay your respects.'
                    .format(gen_roar(), session.match.group(1)))

    def _klappa_command(self, session):
        session.say('{}'.format(gen_roar()))
