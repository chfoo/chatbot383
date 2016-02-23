import argparse
import json
import logging
import multiprocessing

from chatbot383.app import App


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('config_file')
    arg_parser.add_argument('--debug', action='store_true')
    args = arg_parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    with open(args.config_file, 'r') as file:
        config = json.load(file)

    # Using 'spawn' to avoid safe forking multithreaded process issue
    multiprocessing.set_start_method('spawn')

    app = App(config)
    app.run()


if __name__ == '__main__':
    main()
