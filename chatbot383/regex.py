import multiprocessing
import queue


class RegexTimeout(RuntimeError):
    pass


class RegexServer(object):
    def __init__(self):
        self._request_queue = None
        self._response_queue = None
        self._process = None

    def _launch_process(self):
        assert not self._request_queue
        assert not self._response_queue
        assert not self._process

        self._request_queue = multiprocessing.SimpleQueue()
        self._response_queue = multiprocessing.Queue()

        self._process = multiprocessing.Process(
            target=self._run_server_loop,
            args=(self._request_queue, self._response_queue))
        self._process.daemon = True
        self._process.start()

    @classmethod
    def _run_server_loop(cls, request_queue, response_queue):
        while True:
            pattern, text = request_queue.get()
            match = pattern.search(text)
            response_queue.put(bool(match))

    def _stop_server(self):
        self._process.terminate()
        self._process = None
        self._request_queue = None
        self._response_queue = None

    def search(self, pattern, text):
        if not self._process:
            self._launch_process()

        self._request_queue.put((pattern, text))

        try:
            return self._response_queue.get(timeout=1.0)
        except queue.Empty as error:
            self._stop_server()
            raise RegexTimeout() from error
