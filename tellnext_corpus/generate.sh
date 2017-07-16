#!/bin/sh

set -e
set -x

PYPY=python3
#PYPY=pypy3
PYTHON=python3
PYTHONPATH="$PYTHONPATH:../../autocomplete/"
OUTPUTTEXT=/tmp/tn_corpus.txt

export PYTHONPATH

cat corpus/*.txt | grep -v -e '^#' | tr '[A-Za-z]' '[N-ZA-Mn-za-m]' > $OUTPUTTEXT
$PYPY -m tellnext --database model.db train $OUTPUTTEXT
$PYTHON -m tellnext --database model.db generate --lines 10
echo Done
