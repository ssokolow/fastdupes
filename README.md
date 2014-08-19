# Find Dupes Fast

[![Stories in Ready](https://badge.waffle.io/ssokolow/fastdupes.svg?label=ready&title=Ready)](https://waffle.io/ssokolow/fastdupes)

Find Dupes Fast (A.K.A. fastdupes.py) is a simple script which identifies
duplicate files several orders of magnitude more quickly than
[fdupes](https://packages.debian.org/stable/fdupes) by using smarter
algorithms.

It was originally inspired by Dave Bolton's
[dedupe.py](http://davebolton.net/blog/?p=173) and Reasonable Software's
[NoClone](http://noclone.net/) and has no external dependencies beyond the
Python 2.x standard library.

Full API documentation is available via
[ePyDoc](http://epydoc.sourceforge.net/) and, pending proper end user
documentation, the `--help` option is being constantly improved.

## Algorithm

The default mode of operation is as follows:

1. The given paths are recursively walked (subject to `--exclude` rules) to
   gather a list of files for comparison.
2. Gathered files are grouped by their size in bytes (because `stat()` is fast
   compared to actually reading file content) and any groups containing only
   one entry are discarded.
3. Groups are further subdivided by taking the SHA1 hash of the first `16KiB`
   of each file and, again, discarding groups which now contain only one item.
4. The few files which remain are read in `64KiB` chunks and groups are again
   subdivided based on SHA1 hashes. This time, of their full contents.
5. Any groups which contain more than one item contain sets of duplicated
   files.

This approach provides an excellent compromise between runtime and memory
consumption.

Here are the final status messages from a cold-cache run I did on my machine to
root out cases where my manual approach to backing up things that don't change
left duplicates lying around:

```
$ python fastdupes.py /srv/Burned/Music /srv/Burned_todo/Music /srv/fservroot/music
Found 72052 files to be compared for duplication.
Found 7325 sets of files with identical sizes. (72042 files examined)
Found 1197 sets of files with identical header hashes. (38315 files examined)
Found 1197 sets of files with identical hashes. (2400 files examined)
```

Those `... files examined` numbers should show its merits. The total wall clock
runtime was 280.155 seconds.

## Exact Comparison Mode

If the `-E` switch is provided on the command line, the final full-content SHA1
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
have identical sizes and do not differ in their first `16KiB` of data but are
different elsewhere) is such a tiny risk that very few people will need it.

(Yes, it's a fact that, because files are longer than hashes, collisions are
possible... but only an astronomically small number of the possible
combinations of bytes are meaningful data that you'd find in a file on your
hard drive.)

## The `--delete` option

Like fdupes, fastdupes.py provides a `--delete` option which produces
interactive prompts for removing duplicates.

However, unlike with fdupes, these prompts make it impossible to accidentally
delete every copy of a file. (Bugs excepted, of course. A full unit test suite
to ensure this behaviour is still on the TODO list.)

* The `--delete` UI asks you which files you'd like to *keep* and won't accept an
empty response
* Specifying a directory more than once will not result in a file being listed
  as a duplicate of itself. Nor will specifying a directory and its ancestor.
* A `--symlinks` option will not be added until safety can be guaranteed.

