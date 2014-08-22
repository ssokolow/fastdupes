#!/usr/bin/env python
"""Basic setup.py needed to use tox"""

__author__ = "Stephan Sokolow (deitarion/SSokolow)"
__license__ = "GNU GPL 2.0 or later"

if __name__ == '__main__':
    from setuptools import setup

    setup(
        name="fastdupes",
        version="0.3.6",
        description="High-efficiency tool for finding sets of duplicate files",
        long_description="""\
Find Dupes Fast (A.K.A. fastdupes.py) is a simple script which identifies
duplicate files several orders of magnitude more quickly than fdupes by using
smarter algorithms.""",
        author="Stephan Sokolow",
        author_email="http://www.ssokolow.com/ContactMe",  # No spam harvesting
        url="https://github.com/ssokolow/fastdupes/",
        #download_url="https://github.com/ssokolow/fastdupes/",
        py_modules=['fastdupes'],

        entry_points={
            'console_scripts': [
                'fastdupes = fastdupes:main',
            ],
        },
    )
