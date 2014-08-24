.. image:: https://landscape.io/github/ssokolow/fastdupes/master/landscape.png
   :target: https://landscape.io/github/ssokolow/fastdupes/master
   :alt: Code Health
.. image:: https://readthedocs.org/projects/fastdupes/badge/?version=latest
   :target: https://readthedocs.org/projects/fastdupes/?badge=latest
   :alt: Documentation Status
.. image:: https://badge.waffle.io/ssokolow/fastdupes.svg?label=ready&title=Ready
   :target: https://waffle.io/ssokolow/fastdupes
   :alt: 'Stories in Ready'

Find Dupes Fast (A.K.A. ``fastdupes.py``) is a simple script which identifies
duplicate files several orders of magnitude more quickly than
`fdupes`_ by using smarter algorithms.

It was originally inspired by Dave Bolton's `dedupe.py`_ and Reasonable
Software's `NoClone`_ and has no external dependencies beyond the Python 2.x
standard library.

Full API documentation is available on ReadTheDocs and, `pending proper end user
documentation <https://github.com/ssokolow/fastdupes/issues/24>`_, the
``--help`` option is being constantly improved.

.. _fdupes: https://packages.debian.org/stable/fdupes
.. _dedupe.py: http://davebolton.net/blog/?p=173
.. _NoClone: http://noclone.net/

Algorithm
=========

The default mode of operation is as follows:

1. The given paths are recursively walked (subject to ``--exclude``) to
   gather a list of files.
2. Files are grouped by size (because ``stat()`` is fast compared to
   ``read()``)
   and single-entry groups are pruned away.
3. Groups are subdivided and pruned by hashing the first ``16KiB`` of each
   file.
4. Groups are subdivided and pruned again by hashing full contents.
5. Any groups which remain are sets of duplicates.

Because this multi-pass approach eliminates files from consideration as early
as possible, it reduces the amount of disk I/O that needs to be performed by
at least an order of magnitude, greatly speeding up the process.

Here are the final status messages from a cold-cache run I did on my machine to
root out cases where my manual approach to backing up things that don't change
left duplicates lying around::

  $ python fastdupes.py /srv/Burned/Music /srv/Burned_todo/Music /srv/fservroot/music
  Found 72052 files to be compared for duplication.
  Found 7325 sets of files with identical sizes. (72042 files examined)
  Found 1197 sets of files with identical header hashes. (38315 files examined)
  Found 1197 sets of files with identical hashes. (2400 files examined)

Those ``... files examined`` numbers should show its merits. The total wall
clock runtime was 280.155 seconds.

Memory efficiency is also kept high by building full-content hashes
incrementally in ``64KiB`` chunks so that full files never need to be loaded
into memory.

Exact Comparison Mode
=====================

If the ``-E`` switch is provided on the command line, the final full-content SHA1
hashing will be omitted. Instead, all of the files in each group will be read
from the disk in parallel, comparing chunk-by-chunk and subdividing the group
as differences appear.

This greatly increases the amount of disk seeking and offers no benefits in
the vast majority of use cases. However, if you are storing many equally-sized
files on an SSD and their headers are identical but they do vary, the
incremental nature of this comparison may save you time by allowing the
process to stop reading a given file as soon as it becomes obvious that it's
unique.

The other use for this (avoiding the risk of hash collisions in files that
have identical sizes and do not differ in their first ``16KiB`` of data but
are different elsewhere) is such a tiny risk that very few people will need it.

(Yes, it's a fact that, because files are longer than hashes, collisions are
possible... but only an astronomically small number of the possible
combinations of bytes are meaningful data that you'd find in a file on your
hard drive.)

The ``--delete`` option
=============================

Like fdupes, fastdupes.py provides a ``--delete`` option which produces
interactive prompts for removing duplicates.

However, unlike with fdupes, these prompts make it impossible to accidentally
delete every copy of a file. (Bugs excepted, of course. A full unit test suite
to ensure this behaviour is still on the TODO list.)

* The ``--delete`` UI asks you which files you'd like to *keep* and won't
  accept an empty response.
* Specifying a directory more than once on the command line will not result in
  a file being listed as a duplicate of itself. Nor will specifying a directory
  and its ancestor.
* A ``--symlinks`` option will not be added until safety can be
  guaranteed.

The ``--prefer`` and ``--noninteractive`` options
-------------------------------------------------------------

Often, when deduplicating with ``--delete``, you already know that files
in one directory tree should be preferred over files in another.

For example, if you have a folder named ``To Burn`` and another named
``Burned``, then you shouldn't have to tell your deduplicator that files in the
former should be deleted.

By specifying ``--prefer=*/Burned`` on the command-line, you can skip the
prompts in such a situation while still receiving prompts for other files.

Furthermore, if you'd like a fully unattended deduplication run, include the
``--noninteractive`` option and fastdupes will assume that you want to
keep all copies (do nothing) when it would otherwise prompt.

Finally, a ``--dry-run`` option is provided in case you need to test the
effects of a ``--delete`` setup without risk to your files.

