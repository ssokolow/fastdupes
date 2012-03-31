#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Find Dupes Fast
By Stephan Sokolow (ssokolow.com)

Inspired by Dave Bolton's dedupe.py (http://davebolton.net/blog/?p=173) and
Reasonable Software's NoClone.

A simple script which identifies duplicate files several orders of magnitude
more quickly than fdupes by using smarter algorithms. Most importantly, rather
than calculating the MD5 sums for all files with non-unique sizes, this script
groups files by their size and then does incremental comparisons.

As such, files can be read in 4KiB chunks and the script will only read as many
chunks as it needs in order to confirm that a file is unique. (There is no way
to avoid reading the entire file if it does have duplicates)

In addition, this script eliminates the tiny but present risk of hash collisions
causing false positives by doing byte-by-byte comparison rather than hashing the
files and then comparing hashes. This doesn't slow the process down because
each chunk is only read from the disk once and duplicate-finding is an I/O-bound
operation.

Grouping by size is used to limit both the memory consumption and the number of
open file handles when doing the byte-by-byte comparison.

Finally, unlike with fdupes, under no circumstances will the --delete option
allow you to accidentally delete every copy of a file. (No --symlinks option is
supported and this script will not be confused by specifying the same directory
multiple times on the command line or specifying a directory and its parent.)

@todo:
 - Decide what to do in the face of my discovery of https://github.com/sahib/rmlint
 - Rewrite this to put the grouping logic in a single groupByKey(paths, keymaker)
   function.
 - As I understand it, fnmatch.fnmatch uses regexes internally and doesn't cache
   them. Given how many times it gets called, I should try using re.compile with
   fnmatch.translate instead.
 - When in hash comparison mode, skip the second comparison for files small
   enough to be fully-compared by the header comparison.
 - Look into the performance effect of checking whether excludes contain
   metacharacters and using simple string matching if they don't.
 - Group files by stat().st_ino to avoid reading from the same inode more than
   once and to allow advanced handling of hardlinks in --delete mode.
   - Offer a switch to automatically hardlink all duplicates found which share a
     common partition.
 - Identify the ideal values for CHUNK_SIZE and HEAD_SIZE... or
   how about dynamically tuning the read increment size based on the number of
   files being compared and possibly the available RAM? (To minimize seeking)
   block_size = min(max_block_size, max_consumption / file_count)
   Maybe a 64K maximum block size, 4K minimum block size,  an an 8MB max
   consumption? (subordinate to minimum block size when in conflict)
   - Is there such a thing as a disk access profiler that I could use with this?
 - The result groups should be sorted by their first entry and the entries within
   each group should be sorted too.
 - Confirm that the byte-by-byte comparison's short-circuit evaluation is working
   properly and efficiently.
 - Run this through a memory profiler and look for obvious bloat to trim.
 - Look into possible solutions for pathological cases of thousands of files with
   the same exact size and same pre-filter results. (File handle exhaustion)
 - Add a mode which caches hashes indexed by (path,size,mtime/ctime) so users can
   trade away a bit of accuracy for a lot more speed.
 - Look into supporting gettext localization.
 - Support displaying duplicated directory trees as single results.
 - Once ready, announce this in a comment at
   http://ubuntu.wordpress.com/2005/10/08/find-duplicate-copies-of-files/
"""

#TODO: <mauke> feature request: if you could make it output compatible with http://www.ioccc.org/1998/schweikh3.hint , that would be sweet (http://www.ioccc.org/1998/schweikh3.c)

# TODO:
# <mauke> I don't like the way fdupes works. samefile's interface is superior
# <mauke> it says if you specify a directory twice, it will list files as their own duplicates
# <mauke> wtf was the author thinking?
# <deitarion> mauke: Lazy, I guess. I believe I fixed that in fastdupes.

#TODO: Add support for \n and \x00-separated stdin file lists.

#TODO: http://docs.python.org/library/stdtypes.html#string-formatting
# <mauke> wow, a dynamic format string
# <mauke> "%%%ds: %%s" confused me for a second there :-)
# <mauke> doesn't python know about "%*d"?
# <deitarion> Not sure. I've never heard of it.
# <mauke> er, "%*s"
# <deitarion> The dynamic format string is a trick I first picked up when doing string substitution on optparse usage lines where you have to escape %prog if you use it.
# <mauke> well, in Perl I'd just do something like: my $max = max(map length, keys %DEFAULTS); ... printf "%*s: %s\n", $max, $key, $value;
# <mauke> (or in C, but then I'd have to write my own max() and stuff)
# <deitarion> Given that Google doesn't search punctuation, mind explaining what %*s does?
# <mauke> see http://perldoc.perl.org/functions/sprintf.html for details, but:
# <mauke> you can use * instead of a hardcoded width (and .* instead of precision)
# <mauke> printf will then take an (integer) argument and substitute it
# <mauke> so printf("%*s", 10, "foo") is equivalent to printf("%10s", "foo")
# <deitarion> Hmm. It does support %*s. Another thing to make a TODO note for.
# <mauke> this is more important in C because dynamically generated format strings are much more painful there and the compiler can't check your args anymore, but it's still nice to have

__appname__ = "Find Dupes Fast"
__author__  = "Stephan Sokolow (deitarion/SSokolow)"
__version__ = "0.3.5"
__license__ = "GNU GPL 2.0 or later"

import fnmatch, os, sets, stat, sys

# Default settings
DEFAULTS = {
          'delete' : False,
         'exclude' : ['*/.svn', '*/.bzr'],
        'min_size' : 25, # Only check files this big or bigger.
}
CHUNK_SIZE = 65536 # Chunked file reads will operate on this many bytes at a time.
HEAD_SIZE  = 65536 # Header comparison will compare this many bytes per file.

# According to the hard drive data sheets I examined, the average latency to
# acquire a specific block (seek time, rotational latency, etc.) ranges from
# roughly 14ms to 3ms. Assuming that the average uncached, seekless throughput
# for a modern disk drive ranges from 60MB/s (as Google and hdparm seem to agree
# on for 7200 RPM drives) and 73MB/s (lower bound for 15K RPM drives according
# to manufacturer data sheets), then the point where read time overtakes seek time
# in best-case scenarios for pseudo-parallel reads is at:
# 73 * (3.0 / 1000) = 0.219
# As such, 220K (round to a multiple of 4K) should be a good rule-of-thumb lower
# bound for chunk sizes. (Actual chunk size must take available RAM into account
# since, theoretically, a user may use this on a system with tons of dupes of a
# single file)

IDEAL_MIN_CHUNK_SIZE = 220 * 1024 #TODO: Actually use this value.
#TODO: Gather statistical information on the characteristics of
# commonly-duplicated files to further tune this.

# We need os.lstat so we can skip symlinks, but we want Windows portability too.
try: _stat = os.lstat
except: _stat = os.stat

# Note: In my `python -m timeit` tests, the difference between MD5 and SHA1 was
# negligible, so there is no meaningful reason not to take advantage of the
# reduced potential for hash collisions SHA-1's greater hash size offers.
try:
    import hashlib
    hasher = hashlib.sha1
except:
    # Backwards-compatibility for pre-2.5 Python.
    import sha
    hasher = sha.new

def getPaths(roots, ignores=DEFAULTS['exclude'], min_size=DEFAULTS['min_size']):
    """
    Given a list of directories, walk them and return a list of absolute paths.

    Ignores files matched by ignore patterns.
    Doesn't descend into directories matched by ignore patterns.

    @todo: Try to optimize the ignores matching. Running a regex on every
    filename is a fairly significant percentage of the time taken according to
    the profiler.
    """
    paths, count = [], 0

    # Prepare the ignores list for most efficient use
    # TODO: Check how much of the following should actually be used
    #pats, frag_pats, abs_pats = [], []
    #for pat in ignores:
    #    if '*' in pat or '?' in pat or '[' in pat:
    #        pats.append(re.compile(fnmatch.translate(pat)))
    #    elif pat.startswith(os.sep) or os.altsep and pat.startswith(os.altsep):
    #        abs_pats.append(pat)
    #    else:
    #        frag_pats.append(pat)

    for root in roots:
        # For safety, only use absolute, real paths.
        root = os.path.realpath(root)

        # Handle directly-referenced filenames properly
        # (And override ignores to "do as I mean, not as I say")
        if os.path.isfile(root):
            paths.append(root)
            continue

        for fldr in os.walk(root):
            sys.stderr.write("\rGathering file paths to compare... (%d files examined)" % count)

            # Don't even descend into IGNOREd directories.
            for subdir in fldr[1]:
                dirpath = os.path.join(fldr[0], subdir)
                if [x for x in ignores if fnmatch.fnmatch(dirpath, x)]:
                    fldr[1].remove(subdir)

            for filename in fldr[2]:
                filepath = os.path.join(fldr[0], filename)
                if [x for x in ignores if fnmatch.fnmatch(filepath,x)]:
                    continue # Skip IGNOREd files.

                paths.append(filepath)
                count += 1

    sys.stderr.write("\rFound %s files to be compared for duplication.      \n" % (len(paths), count))
    return paths


def groupBySize(paths, min_size=DEFAULTS['min_size']):
    """
    Given a list of paths, return a dict of lists where the keys are filesizes
    and the values are lists of files with those sizes.

    Ignores symlinks.

    @todo: Rework the calling of stat() to minimize the number of calls. It's a
    fairly significant percentage of the time taken according to the profiler.
    """
    filesBySize, count = {}, 0
    for path in paths:
        sys.stderr.write("\rFinding files with identical sizes... (%d files examined)" % count)

        # If this is gonna run on every single file, let's make it only do
        # a single lstat() call outside os.walk().
        filestat = _stat(path)
        if stat.S_ISLNK(filestat.st_mode):
            continue # Skip symlinks.

        if filestat.st_size >= min_size:
            if not filestat.st_size in filesBySize:
                # Use sets.Set() to avoid accidentally counting a given path twice.
                # (Reinforces the use of os.path.realpath in getPaths for safety)
                filesBySize[filestat.st_size] = sets.Set()
            filesBySize[filestat.st_size].add(path)
            count += 1

    # Return only the sizes with more than one file.
    filesBySize = dict([(x, filesBySize[x]) for x in filesBySize if len(filesBySize[x]) > 1])
    sys.stderr.write("\rFound %s sets of files with identical sizes. (%d files examined)          \n" % (len(filesBySize), count))
    return filesBySize

def subgroupByHeaders(fileGroups, head_size=HEAD_SIZE):
    """Given a dict mapping file sizes (or anything, really) to iterables of
    paths, use hash comparison of the first head_size bytes to re-group them and
    eliminate files that are obviously not duplicates.

    This serves one of two purposes depending on run-mode:
    - Minimize the number of files checked by full-content hashing
    - Minimize the chances of file handle exhaustion and limit seeking when
      doing exact comparisons.

    Returns a dict mapping head hashes to Set()s of paths.
    """
    groupsByHead, count, total = {}, 0, len(fileGroups)
    for key in fileGroups:
        sys.stderr.write("\rFinding files with identical heads... %d of %d sets examined" % (count, total))
        for path in fileGroups[key]:
            headHash = hasher(file(path,'rb').read(head_size)).digest()
            if not headHash in groupsByHead:
                groupsByHead[headHash] = sets.Set()
            groupsByHead[headHash].add(path)
        count += 1

    groupsByHead = dict([(x, groupsByHead[x]) for x in groupsByHead if len(groupsByHead[x]) > 1])
    sys.stderr.write("\rFound %s sets of files with identical heads. (%d sets examined)\n" % (len(groupsByHead), count))
    return groupsByHead

def hashFile(handle, want_hex=False):
    """Generate an SHA1 hash for a potentially long file.
    Accepts paths and file-like objects.

    If passed a file-like object, digesting will obey CHUNK_SIZE to conserve
    memory.

    If you pass in a file-like object, it is your responsibility to close it.
    """
    if isinstance(handle, basestring):
        handle = file(handle, 'rb')
    fhash = hasher()

    # Chunked digest generation (conserve memory)
    for block in iter(lambda: handle.read(CHUNK_SIZE), ''):
        fhash.update(block)

    return want_hex and fhash.hexdigest() or fhash.digest()

def subgroupByHashes(fileGroups):
    """
    Given a dict from a function like subGroupByHeaders, return a list of lists
    with each sublist representing a group of duplicate files.

    Reads and hashes files block-by-block, but reads files serially to minimize
    seeking. As with all hash comparison, there is an extremely remote
    possibility of hash collision causing false positives.
    """
    dupeGroups, processed = [], 0
    for key in fileGroups:
        sys.stderr.write("\rScanning for real duplicates... %s of %s sets processed" % (processed, len(fileGroups)))
        raise NotImplementedError("TODO: Finish implementing this")
        #dupeGroups.extend(compareFiles(fileGroups[key]))
        #processed += 1

    results = [x for x in dupeGroups if len(x) > 1]
    sys.stderr.write("\rFound %s sets of duplicate files. (processed %s potential sets)\n" % (len(results), len(fileGroups)))
    return results

def subgroupByContents(fileGroups):
    """
    Given a dict from a function like subGroupByHeaders, return a list of lists
    with each sublist representing a group of duplicate files.

    Compares block-by-block using parallel reads. Lacks the remote potential of
    hash collisions present with hash comparison... but is heavy on disk seeks.
    """
    dupeGroups, processed = [], 0
    for key in fileGroups:
        sys.stderr.write("\rScanning for real duplicates... %s of %s sets processed" % (processed, len(fileGroups)))
        # By doing it this way, I minimize the number of file handles open at
        # any given time. (group by group)
        dupeGroups.extend(compareFiles(fileGroups[key]))
        processed += 1

    results = [x for x in dupeGroups if len(x) > 1]
    sys.stderr.write("\rFound %s sets of duplicate files. (processed %s potential sets)\n" % (len(results), len(fileGroups)))
    return results

def compareFiles(paths):
    """
    Do a byte-by-byte comparison of an arbitrary number of files without
    doing any more disk I/O than a regular SHA1 or MD5 hash comparison would
    take. (Does do a lot of seeking though. Best for SSD-based storage)

    Takes a list of paths as input and returns a list of lists of paths as
    output.
    """
    handles, results = [], []

    # Silently ignore files we don't have permission to read.
    hList = []
    for path in paths:
        try:
            hList.append((path, open(path, 'rb'), ''))
        except IOError:
            pass #TODO: Verbose-mode output here.
    handles.append(hList)

    # While there are handles that are neither EOFed nor known to be unique...
    while handles:
        # Process more blocks.
        #FIXME: Start examining this to figure out how to minimize thrashing in
        #       situations where read-ahead caching is active. Compare savings
        #       by read-ahead to savings due to eliminating false positives as
        #       quickly as possible. This is a 2-variable min/max problem.
        more, done = compareChunks(handles.pop(0))

        # Add the results to the top-level lists.
        handles.extend(more)
        results.extend(done)
    return results

def compareChunks(handles, chunkSize=CHUNK_SIZE):
    """
    Given a list of (path, handle, "") tuples, read a chunk from each handle,
    compare them, and return two sets of lists:
    - One containing more lists to be fed back into this function individually.
    - One containing finished groups of duplicate paths. (includes unique files
      as single-file lists)

    File handles will be automatically closed when they're no longer necessary.

    @todo: Discard the chunk contents immediately once they're no longer needed.
    """
    chunks = [(path, fh, fh.read(chunkSize)) for path, fh, data in handles]
    more, done = [], []

    # While there are combinations not yet tried...
    while chunks:
        # Compare the first chunk to all successive chunks
        matches, non_matches = [chunks[0]], []
        for chunk in chunks[1:]:
            if matches[0][2] == chunk[2]:
                matches.append(chunk)
            else:
                non_matches.append(chunk)
        # Check for EOF or obviously unique files
        if len(matches) == 1 or matches[0][2] == "":
            for x in matches:
                x[1].close()
            done.append([x[0] for x in matches])
        else:
            more.append(matches)
        chunks = non_matches

    return more, done

def pruneUI(dupeList, mainPos, mainLen):
    """Prompt the user for which files they want to keep (impossible to choose
    "none of them") using a number-driven console menu and then return a list
    of filenames to be deleted.

    The user may enter "all" or one or more numbers separated by spaces and/or
    commas.

    Arguments:
    - dupeList (a list of paths to duplicate files)
    - mainPos (Used to display "set X of Y")
    - mainLen (Used to display "set X of Y")"""
    dupeList = sorted(dupeList)
    print
    for pos, val in enumerate(dupeList):
        print "%d) %s" % (pos+1, val)
    while True:
        choice = raw_input("[%s/%s] Keepers: " % (mainPos, mainLen)).strip()
        if not choice:
            print "You must specify at least one file to keep."
            continue
        elif choice.lower() == 'all':
            return []
        try:
            result = [int(x)-1 for x in choice.replace(',',' ').split()]
            return [path for pos, path in enumerate(dupeList) if not pos in result]
        except:
            print "Invalid choice. Please enter a space/comma-separated list of numbers or 'all'."

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser(usage="%prog [options] <folder path> ...",
            version="%s v%s" % (__appname__, __version__))
    parser.add_option('-D', '--defaults', action="store_true", dest="defaults",
        default=False, help="Display the default values for options which take"
        " arguments and then exit.")
    parser.add_option('-d', '--delete',  action="store_true", dest="delete",
        help="Prompt the user for files to preserve and delete all others.")
    parser.add_option('-E', '--exact', action="store_true", dest="exact",
        default=False, help="There is a vanishingly small chance of false"
        " positives when comparing files using sizes and hashes. This option"
        " enables exact comparison. However, exact comparison requires a lot of"
        " disk seeks, so, on traditional moving-platter media, this trades a"
        " LOT of performance for a very tiny amount of safety most people don't"
        " need.")
    parser.add_option('-e', '--exclude', action="append", dest="exclude",
        metavar="PAT", help="Specify a globbing pattern to be"
        " added to the internal blacklist. This option can be used multiple"
        " times. Provide a dash (-) as your first exclude to override the"
        " pre-programmed defaults.")
    parser.add_option('--min-size', action="store", type="int", dest="min_size",
        metavar="X", help="Specify a non-default minimum size"
        ". Files below this size (default: %s bytes) will be ignored."
        "" % DEFAULTS['min_size'])
    #XXX: Should I add --verbose and/or --quiet?
    parser.set_defaults(**DEFAULTS)

    opts, args = parser.parse_args()

    if '-' in opts.exclude:
        opts.exclude = opts.exclude[opts.exclude.index('-') + 1:]
    opts.exclude = [x.rstrip(os.sep + (os.altsep or '')) for x in opts.exclude]
    # This line is required to make it match directories

    if opts.defaults:
        formatStr = "%%%ds: %%s" % max([len(x) for x in DEFAULTS])
        for key in DEFAULTS:
            value = DEFAULTS[key]
            if isinstance(value, (list, sets.Set)):
                value = ', '.join(value)
            print formatStr % (key, value)
        sys.exit()

    groups = getPaths(args, opts.exclude)
    groups = groupBySize(groups, opts.min_size)
    groups = subgroupByHeaders(groups)

    if opts.exact:
        groups = subgroupByContents(groups)
    else:
        groups = subgroupByHashes(groups)

    if opts.delete:
        for pos, val in enumerate(groups):
            #TODO: Add a secondary check for symlinks for safety.
            pruneList = pruneUI(val, pos+1, len(groups))
            for path in pruneList:
                os.remove(path)
    else:
        for dupeSet in groups:
            for filename in dupeSet:
                print filename
            print
