import tellnext.store
import tellnext.model
import tellnext.generator


class TellnextGenerator(object):
    def __init__(self, database_path):
        self._store = tellnext.store.SQLiteStore(path=database_path)
        self._model = tellnext.model.MarkovModel(store=self._store)
        self._generator = tellnext.generator.Generator(self._model)

    def get_paragraph(self, max_len=300):
        sentences = []

        while True:
            sentence = self._generator.generate_sentence(max_words=50)[:max_len].capitalize() + ' '
            sentences.append(sentence)

            if sum(map(len, sentences)) >= max_len:
                del sentences[-1]

                if sentences:
                    break

        return ''.join(sentences)
