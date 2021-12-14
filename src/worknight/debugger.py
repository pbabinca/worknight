"""Module with debug statements"""

from __future__ import annotations

import pdb


def post_mortem(traceback):
    pdb.post_mortem(traceback)
