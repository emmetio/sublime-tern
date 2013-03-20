###############################################################################
# Formic: An implementation of Apache Ant FileSet globs
# Copyright (C) 2012, Aviser LLP, Singapore.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
###############################################################################

"""An implementation of Ant Globs.

The main entry points for this modules are:

* :class:`FileSet`: A collection of include and exclude globs starting at a specific
  directory.

  * :meth:`FileSet.files()`: A generator returning the matched files as
    directory/file tuples
  * :meth:`FileSet.qualified_files()`: A generator returning the matched files
    as qualified paths

* :class:`Pattern`: An individual glob
"""

from os import path, getcwd, walk
from fnmatch import fnmatch, filter as fnfilter
from itertools import chain
# from pkg_resources import resource_string

# def get_version():
#     """Returns the version of formic.

#     This method retrieves the version from VERSION.txt, and it should be
#     exactly the same as the version retrieved from the package manager"""
#     return resource_string(__name__, "VERSION.txt")

try:
    isinstance("", basestring)
    def isstr(s):
        return isinstance(s, basestring)
except NameError:
    def isstr(s):
        return isinstance(s, str)

class FormicError(Exception):
    """Formic errors, such as misconfigured arguments and internal exceptions"""
    def __init__(self, message=None):
        super(FormicError, self).__init__(message)

class Matcher(object):
    """An abstract class that holds some pattern to be matched;
    ``matcher.match(string)`` returns a boolean indicating whether the string
    matches the pattern.

    The :meth:`Matcher.create()` method is a Factory that creates instances of
    various subclasses."""
    @staticmethod
    def create(pattern):
        """Factory for :class:`Matcher` instances; returns a :class:`Matcher`
        suitable for matching the supplied pattern"""
        if "?" in pattern or "*" in pattern:
            return FNMatcher(pattern)
        else:
            return ConstantMatcher(pattern)

    def __init__(self, pattern):
        self.pattern = pattern

    def match(self, _):
        """:class:`Matcher` is an abstract class - this will raise a
        :exc:`FormicError`"""
        raise FormicError("Match should not be directly constructed")

    def __eq__(self, other):
        return (isinstance(other, type(self)) and
                self.pattern == other.pattern)

    def __ne__(self, other):
        return (not isinstance(other, type(self)) or
                self.pattern != other.pattern)

    def __hash__(self):
        return self.pattern.__hash__()

    def __str__(self):
        return self.pattern


class FNMatcher(Matcher):
    """A :class:`Matcher` that matches simple file/directory wildcards as per
    DOS or Unix.

    * ``FNMatcher("*.py")`` matches all Python files in a given directory.
    * ``FNMatcher("?ed")`` matches bed, fed, wed but not failed

    :class:`FNMatcher` internally uses :func:`fnmatch.fnmatch()` to implement
    :meth:`Matcher.match`"""
    def __init__(self, pattern):
        super(FNMatcher, self).__init__(pattern)

    def match(self, string):
        """Returns True if the pattern matches the string"""
        return fnmatch(string, self.pattern)


class ConstantMatcher(Matcher):
    """A :class:`Matcher` for matching the constant passed in the constructor.

    This is used to more efficiently match path and file elements that
    do not have a wild-card, eg ``__init__.py``"""
    def __init__(self, pattern):
        super(ConstantMatcher, self).__init__(pattern)

    def match(self, string):
        """Returns True if the argument matches the constant."""
        return self.pattern == string


class Section(object):
    """A minimal object that holds fragments of a :class:`Pattern` path.

    Each :class:`Section` holds a list of pattern fragments matching some
    contiguous portion of a full path, separated by ``/**/`` from other
    :class:`Section` instances.

    For example, the :class:`Pattern` ``/top/second/**/sub/**end/*`` is stored
    as a list of three :class:`Section` objects:

    1. ``Section(["top", "second"])``
    2. ``Section(["sub"])``
    3. ``Section(["end"])``
    """
    def __init__(self, elements):
        assert elements
        self.elements    = []
        self.bound_start = False
        self.bound_end   = False
        for element in elements:
            self.elements.append(Matcher.create(element))
        self.length = len(self.elements)
        self.str = "/".join(str(e) for e in self.elements)

    def match_iter(self, path_elements, start_at):
        """A generator that searches over *path_elements* (starting from the
        index *start_at*), yielding for each match.

        Each value yielded is the index into *path_elements* to the first element
        *after* each match. In other words, the returned index has already
        consumed the matching path elements of this :class:`Section`.

        Matches work by finding a contiguous group of path elements that
        match the list of :class:`Matcher` objects in this :class:`Section`
        as they are naturally paired.

        This method includes an implementation optimization that simplifies
        the search for :class:`Section` instances containing a single path
        element. This produces significant performance improvements.
        """
        if self.length == 1:
            return self._match_iter_single(path_elements, start_at)
        else:
            return self._match_iter_generic(path_elements, start_at)

    def _match_iter_generic(self, path_elements, start_at):
        """Implementation of match_iter for >1 self.elements"""

        length = len(path_elements)
        # If bound to start, we stop searching at the first element
        if self.bound_start:
            end = 1
        else:
            end = length - self.length + 1

        # If bound to end, we start searching as late as possible
        if self.bound_end:
            start = length - self.length
        else:
            start = start_at

        if start > end or start < start_at or end > length - self.length + 1:
            # It's impossible to match. Either
            # 1) the search has a fixed start and end, and path_elements
            #    does not have enough elements for a match, or
            # 2) To match the bound_end, we have to start before the start_at,
            #    which means the search is impossible
            # 3) The end is after the last possible end point in path_elements
            return

        for index in range(start, end):
            matched = True
            i = index
            for matcher in self.elements:
                element = path_elements[i]
                i += 1
                if not matcher.match(element):
                    matched = False
                    break
            if matched:
                yield index + self.length


    def _match_iter_single(self, path_elements, start_at):
        """Implementation of match_iter optimized for self.elements of length 1"""

        length = len(path_elements)

        if length == 0:
            return

        # If bound to end, we start searching as late as possible
        if self.bound_end:
            start = length - 1
            if start < start_at:
                return
        else:
            start = start_at

        # If bound to start, we stop searching at the first element
        if self.bound_start:
            end = 1
        else:
            end = length
            if start > end:
                # It's impossible to match
                # the search has a fixed start and end, and path_elements
                # does not have enough elements for a match, or
                return

        for index in range(start, end):
            element = path_elements[index]
            if self.elements[0].match(element):
                yield index + 1

    def __eq__(self, other):
        return isinstance(other, Section) and self.str == other.str

    def __ne__(self, other):
        return not isinstance(other, Section) or self.str != other.str

    def __hash__(self):
        return self.str.__hash__()

    def __str__(self):
        return self.str

class MatchType(object):
    """An enumeration of different match/non-match types to optimize
    the search algorithm.

    There are two special considerations in match results that derive
    from the fact that Ant globs can be 'bound' to the start of the path
    being evaluated (eg bound start: ``/Documents/**``).

    The various match possibilities are bitfields using the members
    starting ``BIT_``."""
    BIT_MATCH              = 1 # M
    BIT_ALL_SUBDIRECTORIES = 2 # A
    BIT_NO_SUBDIRECTORIES  = 4 # N

    # The Match types             -BIT FIELDS-
    #                             X  M   A   N
    NO_MATCH                    = 0
    MATCH                       =    1
    MATCH_ALL_SUBDIRECTORIES    =    1 | 2
    MATCH_BUT_NO_SUBDIRECTORIES =    1     | 4
    NO_MATCH_NO_SUBDIRECTORIES  =            4


class Pattern(object):
    """Represents a single Ant Glob.

    The :class:`Pattern` object compiles the pattern into several components:

    * *file_pattern*: The a pattern for matching files (not directories)
      eg, for ``test/*.py``, the file_pattern is ``*.py``. This is always
      the text after the final ``/`` (if any). If the end of the pattern
      is a ``/``, then an implicit ``**/*`` is added to the end of the pattern.
    * *bound_start*: True if the start of the pattern is 'bound' to the
      start of the path. If the pattern starts with a ``/``, the
      start is bound.
    * *bound_end*: True if the end of the pattern is bound to the immediate
      parent directory where the file matching is occurring. This is True if
      the pattern specifies a directory before the file pattern, eg
      ``**/test/*``
    * *sections*: A list of :class:`Section` instances. Each :class:`Section`
      represents a contiguous series of path patterns, and :class:`Section`
      instances are separated whenever there is a ``**`` in the glob.

    :class:`Pattern` also normalises the glob, removing redundant path elements
    (eg ``**/**/test/*`` resolves to ``**/test/*``) and normalises the case of
    the path elements (resolving difficulties with case insensitive file
    systems)
    """

    def __init__(self, glob):
        glob = glob.replace('\\', '/').replace('//', '/')
        self.sections = []
        self.str      = []

        elements = Pattern._simplify(glob.split('/'))
        self.bound_start = elements[0]  != "**"

        if elements[-1] != "**":
            self.file_pattern = elements[-1]
            del elements[-1]
        else:
            self.file_pattern = "*"

        # Optimization: Set self.file_filter to be a specific pattern
        # validating algorithm for the specific pattern
        if self.file_pattern == "*":
            # The pattern matches everything
            self.file_filter = lambda files: files
        elif "*" in self.file_pattern or "?" in self.file_pattern:
            # The pattern is a glob. Use fnmatch.filter
            self.file_filter = lambda files: fnfilter(files, self.file_pattern)
        else:
            # This is a 'constant' pattern - use comprehension
            self.file_filter = lambda files: [ file for file in files if file == self.file_pattern ]

        if elements:
            self.bound_end = elements[-1] != "**"
        else:
            self.bound_end = self.bound_start

        fragment = []
        for element in elements:
            if element == '**':
                if fragment:
                    self.sections.append(Section(fragment))
                fragment = []
            else:
                fragment.append(element)
        if fragment:
            self.sections.append(Section(fragment))

        # Propagate the bound start/end to the sections
        if self.bound_start and self.sections:
            self.sections[0].bound_start = True
        if self.bound_end and self.sections:
            self.sections[-1].bound_end = True

    @staticmethod
    def _simplify(elements):
        """Simplifies and normalizes the list of elements removing
        redundant/repeated elements and normalising upper/lower case
        so case sensitivity is resolved here."""
        simplified = []
        previous = None
        for element in elements:
            if element == "..":
                raise FormicError("Invalid glob:"
                                  " Cannot have '..' in a glob: {0}".
                                    format("/".join(elements)))
            elif element == ".":
                # . in a path does not do anything
                pass
            elif element == "**" and previous == "**":
                # Remove repeated "**"s
                pass
            else:
                simplified.append(path.normcase(element))
                previous = element

        if simplified[-1] == "":
            # Trailing slash shorthand for /**
            simplified[-1] = "**"

        # Ensure the pattern either:
        #  * Starts with a "**", or
        #  * Starts with the first real element of the glob
        if simplified[0] == "":
            # "" means the pattern started with a slash.
            del simplified[0]
        else:
            if simplified[0] != "**":
                simplified.insert(0, "**")

        return simplified

    def match_directory(self, path_elements):
        """Returns a :class:`MatchType` for the directory, expressed as a list of path
        elements, match for the :class:`Pattern`.

        If ``self.bound_start`` is True, the first :class:`Section` must match
        from the first directory element.

        If ``self.bound_end`` is True, the last :class:`Section` must match
        the last contiguous elements of *path_elements*.
        """

        def match_recurse(is_start, sections, path_elements, location):
            """A private function for implementing the recursive search.

            The function takes the first section from sections and tries to
            match this against the elements in path_elements, starting from
            the location'th element in that list.

            If sections is empty, this is taken to mean all sections have
            been previously matched, therefore a match has been found.
            """
            if sections:
                section = sections[0]
                any_match = False
                for end in section.match_iter(path_elements, location):
                    any_match = True
                    match = match_recurse(False, sections[1:], path_elements, end)
                    if match | MatchType.MATCH:
                        return match

                # No match found
                if is_start and self.bound_start and not any_match:
                    # This this is the start of the recursion AND the pattern
                    # is bound to the start of the path ("/start/**") AND this
                    # did not match, then no subdirectories are possible either

                    # WAS if len(path_elements) >= 1:

                    if len(path_elements) >= len(section.elements):
                        return MatchType.NO_MATCH_NO_SUBDIRECTORIES
                    else:
                        return MatchType.NO_MATCH
                else:
                    return MatchType.NO_MATCH
            else:
                # Termination of the recursion after FINDING the match.
                if len(self.sections) == 1 and self.bound_start and self.bound_end:
                    # If this pattern is of the form "/test/*" it matches
                    # just THIS directory and no subdirectories
                    return MatchType.MATCH_BUT_NO_SUBDIRECTORIES
                elif self.bound_end:
                    # "**/test/*" matches just this directory
                    # and allows subdirectories to also match
                    return MatchType.MATCH
                else:
                    # If the pattern is not bound to the end of the path (eg
                    # NOT "**/term/**") the pattern matches all subdirectories
                    return MatchType.MATCH_ALL_SUBDIRECTORIES
            # End of: def match_recurse(is_start, sections, path_elements, location):

        if self.sections:
            return match_recurse(True, self.sections, path_elements, 0)
        else:
            # Catches directory-less patterns like "*.py" and "/*.py".
            if self.bound_start:
                if len(path_elements) == 0:
                    # Eg "*/*.py" in the root directory
                    return MatchType.MATCH_BUT_NO_SUBDIRECTORIES
                else:
                    # Eg "/*.py" meets directory "/test/" - nothing happening
                    return MatchType.NO_MATCH_NO_SUBDIRECTORIES
            else:
                # Eg "**/*.py" - match all directories
                return MatchType.MATCH_ALL_SUBDIRECTORIES

    def all_files(self):
        """Returns True if the :class:`Pattern` matches all files (in a matched
        directory).

        The file pattern at the end of the glob was `/` or ``/*``"""
        return self.file_pattern == "*"

    def match_files(self, matched, unmatched):
        """Moves all matching files from the set *unmatched* to the set
        *matched*.

        Both *matched* and *unmatched* are sets of string, the strings
        being unqualified file names"""
        this_match = set(self.file_filter(unmatched))
        matched   |= this_match
        unmatched -= this_match

    def _to_string(self):
        """Implemented a function for __str__ and __repr__ to use, but
        which prevents infinite recursion when migrating to Python 3"""
        if self.sections:
            start    = "/" if self.bound_start else "**/"
            sections = "/**/".join(str(section) for section in self.sections)
            end      = "" if self.bound_end else "/**"
        else:
            start    = ""
            sections = ""
            end      = "" if self.bound_end else "**"
        return "{0}{1}{2}/{3}".format(start, sections, end, str(self.file_pattern))

    def __repr__(self):
        return self._to_string()

    def __str__(self):
        return self._to_string()

class PatternSet(object):
    """A set of :class:`Pattern` instances; :class:`PatternSet` provides
     a number of operations over the entire set.

    :class:`PatternSet` contains a number of implementation optimizations and
    is an integral part of various optimizations in :class:`FileSet`.

    This class is *not* an implementation of Apache Ant PatternSet"""
    def __init__(self):
        self.patterns   = []
        self._all_files = False

    def _compute_all_files(self):
        """Handles lazy evaluation of self.all_files"""
        self._all_files = any(pat.all_files() for pat in self.patterns)

    def all_files(self):
        """Returns True if there is any :class:`Pattern` in the
        :class:`PatternSet` that matches all files (see
        :meth:`Pattern.all_files()`)

        Note that this method is implemented using lazy evaluation so direct
        access to the member ``_all_files`` is very likely to result in errors"""
        if self._all_files is None:
            self._compute_all_files()
        return self._all_files

    def append(self, pattern):
        """Adds a :class:`Pattern` to the :class:`PatternSet`"""
        assert isinstance(pattern, Pattern)
        self.patterns.append(pattern)
        if self._all_files is not None:
            self._all_files = self._all_files or pattern.all_files()

    def extend(self, patterns):
        """Extend a :class:`PatternSet` with addition *patterns*

        *patterns* can either be:

        * Another :class:`PatternSet` or
        * A list of :class:`Pattern` instances"""
        assert patterns is not None
        if isinstance(patterns, PatternSet):
            patterns = patterns.patterns
        else:
            assert all(isinstance(pat, Pattern) for pat in patterns)
        self.patterns.extend(patterns)
        self._all_files = None

    def remove(self, pattern):
        """Remove a :class:`Pattern` from the :class:`PatternSet`"""
        assert isinstance(pattern, Pattern)
        self.patterns.remove(pattern)
        self._all_files = None

    def match_files(self, matched, unmatched):
        """Apply the include and exclude filters to those files in *unmatched*,
        moving those that are included, but not excluded, into the *matched*
        set.

        Both *matched* and *unmatched* are sets of unqualified file names."""
        for pattern in self.iter():
            pattern.match_files(matched, unmatched)
            if not unmatched:
                # Optimization: If we have matched all files already
                # simply return at this point - nothing else to do
                break

    def empty(self):
        """Returns True if the :class:`PatternSet` is empty"""
        return len(self.patterns) == 0

    def iter(self):
        """An iteration generator that allows the loop to modify the
        :class:`PatternSet` during the loop"""
        if self.patterns:
            patterns = list(self.patterns)
            for pattern in patterns:
                yield pattern

    def __str__(self):
        return ("PatternSet (All files? {0}) [{1}] ".
                    format(self.all_files(),
                           ", ".join(str(pat) for pat in self.patterns)))


class FileSetState(object):
    """FileSetState is an object encapsulating the :class:`FileSet` in a
    particular directory, caching inheritable Pattern matches.

    This is an internal implementation class and not meant for reuse
    or to be accessed directly

    **Implementation notes:**

    As the FileSet traverses the directories using :func:`os.walk()`, it
    builds two graphs of FileSetState instances mirroring the graph of
    directories - one graph of FileSetState instances is for the **include**
    globs and the other graph of FileSetState instances for the **exclude**.

    FileSetState embodies logic to decide whether to prune whole
    directories from the search, either by detecting the include patterns
    cannot match any file within, or by detecting that an exclude
    matches all files in this directory and sub-directories.

    The constructor has the following arguments:

    1. *label*: A string used only in the :meth:`__str__` method (for debugging)
    2. *directory*: The point in the graph that this FileSetState represents/
       *directory* is relative to the starting node of the graph
    3. *based_on*: A FileSetState from the previous directory traversed by
       :func:`os.walk()`. This is used as the start point in the graph of
       FileSetStates to search for the correct parent of this. This is None
       to create the root node.
    4. *unmatched*: Used only when *based_on* is None  - the set of initial
       :class:`Pattern` instances. This is either the original include
       or exclude globs.

    During the construction of the instance, the instance will evaluate the
    directory patterns in :class:`PatternSet` ``self.unmatched`` and, for
    each :class:`Pattern`, perform of of the following actions:

    1. If a pattern matches, it will be moved into one of the 'matched'
    :class:`PatternSet` instances:

       a. ``self.matched_inherit``: the directory pattern matches all sub
          subdirectories as well, eg ``/test/**``
       b. ``self.matched_and_subdir``: the directory matches this directory
          and *may* match subdirectories as well, eg ``/test/**/more/**``
       c. ``self.matched_no_subdir``: the directory matches this directory,
          **but** cannot match any subdirectory, eg ``/test/*``. This pattern
          will thus not be evaluated in any subdirectory.

    2. If the pattern does not match, either:

       a. It may be valid in subdirectories, so it stays in ``self.unmatched``,
          eg ``**/nomatch/*``
       b. It cannot evaluate to true in any subdirectory, eg ``/nomatch/**``.
          In this case it is removed from all :class:`PatternSet` members
          in this instance.
    """
    def __init__(self, label, directory, based_on=None, unmatched=None):
        self.label = label
        if directory:
            self.path_elements = directory.split(path.sep)
        else:
            self.path_elements = []

        # First find the real parent of this node (the based_on is really the
        # previous return from os.walk, and may be a peer, cousin or completely
        # unrelated to the directory in the argument
        if based_on:
            self.parent = based_on._find_parent(self.path_elements)
        else:
            self.parent = None


        # If we have found a parent, copy the parent's computations here
        # as the start. This is a significant optimization by caching
        # as many directory matches as possible
        self.matched_inherit    = PatternSet() # Matches this directory and all sub
        self.matched_and_subdir = PatternSet() # Matches this directory and poss. sub
        self.matched_no_subdir  = PatternSet() # Matches this directory, discard for sub
        self.unmatched          = PatternSet() # Does no match this directory. but poss. sub
        if self.parent:
            self.unmatched.extend(self.parent.matched_and_subdir)
            self.unmatched.extend(self.parent.unmatched)
            # parent_has_patterns is True if _any_ parent up to root has
            # cached a pattern in matched_inherit
            self.parent_has_patterns = (self.parent.parent_has_patterns or
                                        not self.parent.matched_inherit.empty())
        else:
            # This branch exercised only when constructing the root
            self.parent_has_patterns = False
            if unmatched:
                self.unmatched.extend(unmatched)

        # For this branch, check which patterns match, and the type of the
        # match and thereby move the Patterns to the correct buckets
        for pattern in self.unmatched.iter():
            match = pattern.match_directory(self.path_elements)
            if match & MatchType.BIT_MATCH:
                self.unmatched.remove(pattern)
                if match & MatchType.BIT_ALL_SUBDIRECTORIES:
                    # don't re-evaluate this pattern
                    self.matched_inherit.append(pattern)
                elif match & MatchType.BIT_NO_SUBDIRECTORIES:
                    self.matched_no_subdir.append(pattern)
                else:
                    # mark this pattern as a match, re-evaluate for subdirs
                    self.matched_and_subdir.append(pattern)
            else:
                if match & MatchType.BIT_NO_SUBDIRECTORIES:
                    self.unmatched.remove(pattern)

    def _find_parent(self, path_elements):
        """Recurse up the tree of FileSetStates until we find a parent, i.e.
        one whose path_elements member is the start of the path_element
        argument"""
        if not self.path_elements:
            # Automatically terminate on root
            return self
        elif self.path_elements == path_elements[0:len(self.path_elements)]:
            return self
        else:
            return self.parent._find_parent(path_elements)

    def _matching_pattern_sets(self):
        """Returns an iterator containing all PatternSets that match this
        directory.

        This is build by chaining the this-directory specific PatternSet
        (self.matched_and_subdir), the local (non-inheriting) PatternSet
        (self.matched_no_subdir) with all the inherited PatternSets
        that match this directory and all its parents (self.match_inherit)."""
        gather = []
        if self.matched_and_subdir:
            gather.append(self.matched_and_subdir.iter())
            gather.append(self.matched_no_subdir.iter())
        ref = self
        while ref is not None:
            if ref.matched_inherit:
                gather.append(ref.matched_inherit.iter())
            if ref.parent_has_patterns:
                ref = ref.parent
            else:
                ref = None
        return chain.from_iterable(gather)

    def match(self, files):
        """Given a set of files in this directory, returns all the files that
        match the :class:`Pattern` instances which match this directory."""
        if not files:
            return set()

        if (self.matched_inherit.all_files() or
           self.matched_and_subdir.all_files() or
           self.matched_no_subdir.all_files()):
            # Optimization: one of the matched patterns matches everything
            # So simply return it
            return set(files)

        unmatched = set(files)
        matched   = set()
        for pattern_set in self._matching_pattern_sets():
            pattern_set.match_files(matched, unmatched)
            if not unmatched:
                # Optimization: If we have matched all files already
                # simply return at this point - nothing else to do
                break

        return matched

    def matches_all_files_all_subdirs(self):
        """Returns True if there is a pattern that:

        * Matches this directory, and
        * Matches all sub-directories, and
        * Matches all files (eg ends with "*")

        This acts as a terminator for :class:`FileSetState` instances in the
        excludes graph."""
        return any(pat.all_files() for pat in self.matched_inherit.iter())

    def no_possible_matches_in_subdirs(self):
        """Returns True if there are no possible matches for any
        subdirectories of this :class:`FileSetState`.

        For an 'include', this means we can exclude all subdirectories."""
        return (not self.parent_has_patterns and
                   self.matched_inherit.empty() and
                   self.matched_and_subdir.empty() and
                   self.unmatched.empty())

    def __str__(self):
        return ("FileSetState {0} in {1}/:\n"
               "\tInherit: {2}\n"
               "\tthis&subdir: {3}\n"
               "\tthis-only: {4}\n"
               "\tunmatched: {5}".format(
                    self.label,
                    "/".join(self.path_elements),
                    self.matched_inherit,
                    self.matched_and_subdir,
                    self.matched_no_subdir,
                    self.unmatched
                ))

def get_initial_default_excludes():
    """Returns a the default excludes as a list of Patterns.

     This will be the initial value of :attr:`FileSet.DEFAULT_EXCLUDES`.
     It is defined in the `Ant documentation
     <http://ant.apache.org/manual/dirtasks.html#defaultexcludes>`_.
     Formic adds ``**/__pycache__/**``, with the resulting list being:

        * \*\*/pycache/\*\*
        * \*\*/\*~
        * \*\*/#\*#
        * \*\*/.#\*
        * \*\*/%*%
        * \*\*/._\*
        * \*\*/CVS
        * \*\*/CVS/\*\*
        * \*\*/.cvsignore
        * \*\*/SCCS
        * \*\*/SCCS/\*\*
        * \*\*/vssver.scc
        * \*\*/.svn
        * \*\*/.svn/\*\*
        * \*\*/.DS_Store
        * \*\*/.git
        * \*\*/.git/\*\*
        * \*\*/.gitattributes
        * \*\*/.gitignore
        * \*\*/.gitmodules
        * \*\*/.hg
        * \*\*/.hg/\*\*
        * \*\*/.hgignore
        * \*\*/.hgsub
        * \*\*/.hgsubstate
        * \*\*/.hgtags
        * \*\*/.bzr
        * \*\*/.bzr/\*\*
        * \*\*/.bzrignore
     """
    return [ Pattern(exclude) for exclude in
'''**/__pycache__/**
**/*~
**/#*#
**/.#*
**/%*%
**/._*
**/CVS
**/CVS/**
**/.cvsignore
**/SCCS
**/SCCS/**
**/vssver.scc
**/.svn
**/.svn/**
**/.DS_Store
**/.git
**/.git/**
**/.gitattributes
**/.gitignore
**/.gitmodules
**/.hg
**/.hg/**
**/.hgignore
**/.hgsub
**/.hgsubstate
**/.hgtags
**/.bzr
**/.bzr/**
**/.bzrignore
'''.splitlines() ]


class FileSet(object):
    """An implementation of the Ant FileSet class.

    Arguments to the constructor:

    1. *include*: An Ant glob or list of Ant globs for matching files to include
       in the response. Ant globs can be specified either:

       a. As a string, eg ``"*.py"``, or
       b. As a :class:`Pattern` object

    2. *exclude*: Specified in the same was as *include*, but any file that
       matches an exclude glob will be excluded from the result.
    3. *directory*: The directory from which to start the search; if None,
       the current working directory is used
    4. *default_excludes*: A boolean; if True (or omitted) the
       :attr:`DEFAULT_EXCLUDES` will be combined with the *exclude*.
       If False, the only excludes used are those in the excludes argument
    5. *symlinks*: Sets whether symbolic links are included in the results or not.

    **Usage**

    First, construct a ``FileSet``::

            from formic import FileSet
            fileset = FileSet(directory="/some/where/interesting",
                              include="*.py",
                              exclude=["**/*test*/**", "test*"]
                              )

    There are three APIs for retrieving matches:

    1. FileSet is itself an iterator and returns absolute file names::

            for filename in fileset:
                print filename

    2. For more control, use ``fileset.qualified_files()``. The following
       prints filenames *relative* to the directory::

            for filename in fileset.qualified_files(absolute=False):
                print filename

    3. For absolute control, use the ``fileset.files()`` method and handle the
       returned tuple yourself::

            prefix = fileset.get_directory()
            for directory, file_name in fileset.files():
                sys.stdout.write(prefix)
                if dir:
                    sys.stdout.write(path.sep)
                    sys.stdout.write(directory)
                sys.stdout.write(path.sep)
                sys.stdout.write(file_name)
                sys.stdout.write("\\n")

    Implementation notes:

    * :class:`FileSet` is lazy: The files in the :class:`FileSet` are resolved
      at the time the iterator is looped over. This means that it is very fast
      to set up and (can be) computationally expensive only when results are
      obtained.

    * You can iterate over the same :class:`FileSet` instance as many times
      as you want. Because the results are computed as you iterate over the
      object, each separate iteration can return different results, eg if the
      file system has changed.

    * *include* and *exclude* arguments to the constructor can be given in
      several ways:

      * A string: This will be automatically turned into a :class:`Pattern`
      * A :class:`Pattern`: If you prefer to construct the pattern yourself
      * A list of strings and/or :class:`Pattern` instances (as above)

    * In addition to Apache Ant's default excludes, :class:`FileSet` excludes:

      * ``__pycache__``

    * You can modify the :attr:`DEFAULT_EXCLUDES` class member (it is a list of
      :class:`Pattern` instances). Doing so will modify the behaviour of all
      instances of :class:`FileSet` using default excludes.
    """
    #: Default excludes shared by all instances. The member is a list of
    #: :class:`Pattern` instances. You may modify this member at run time to
    #: modify the behaviour of all instances.
    DEFAULT_EXCLUDES = get_initial_default_excludes()

    def __init__(self,
                 include,
                 exclude=None,
                 directory=None,
                 default_excludes=True,
                 symlinks=True):

        self.include  = FileSet._preprocess(include)
        if not self.include:
            raise FormicError("No include globs have been specified"
                              "- nothing to find")
        self.exclude  = FileSet._preprocess(exclude)
        self.symlinks = symlinks
        if default_excludes:
            self.exclude.extend(FileSet.DEFAULT_EXCLUDES)
        if directory is None:
            self.directory = None
        else:
            self.directory = path.abspath(directory)

    @staticmethod
    def _preprocess(argument):
        """Receives the argument (from the constructor), and normalizes it
        into a list of Pattern objects."""
        pattern_set = PatternSet()
        if argument is not None:
            if not hasattr(argument, "__iter__"):
                argument = [ argument ]
            argument = [ Pattern(pattern) if isstr(pattern) else pattern for pattern in argument ]
            pattern_set.extend(argument)
        return pattern_set

    def get_directory(self):
        """Returns the directory in which the :class:`FileSet` will be run.

        If the directory was set with None in the constructor, get_directory()
        will return the current working directory.

        The returned result is normalized so it never contains a trailing
        path separator"""
        directory = self.directory if self.directory else getcwd()
        while len(directory) > 1 and directory.endswith(path.sep):
            directory = directory[0:-1]
        return directory

    def _receive(self, root, directory, dirs, files, include, exclude):
        """Internal function processing each yield from os.walk."""
        if not self.symlinks:
            where = root + path.sep + directory + path.sep
            files = [ file_name for file_name in files
                        if not path.islink(where + file_name) ]

        include = FileSetState("Include",
                               directory,
                               include,
                               None if include else self.include)
        exclude = FileSetState("Exclude",
                               directory,
                               exclude,
                               None if exclude else self.exclude)

        if exclude.matches_all_files_all_subdirs():
            # Exclude everying and do no traverse any subdirectories
            del dirs[0:]
            matched = set()
        else:
            if include.no_possible_matches_in_subdirs():
            # Do no traverse any subdirectories
                del dirs[0:]
            matched  = include.match(set(files))
            matched -= exclude.match(matched)

        return matched, include, exclude

    def files(self):
        """A generator function for iterating over the individual files of
        the FileSet.

        The generator yields a tuple of ``(rel_dir_name, file_name)``:

        1. *rel_dir_name*: The path relative to the starting directory
        2. *file_name*: The unqualified file name
        """
        directory = self.get_directory()
        extras = 1 if len(directory) > 1 else 0

        include = None
        exclude = None
        for root, dirs, files in walk(directory):
            # Remove the constant part of the path inluding the first path sep
            rel_dir_name = root[len(directory)+extras:]
            matched, include, exclude = self._receive(directory,
                                                      rel_dir_name,
                                                      dirs,
                                                      files,
                                                      include,
                                                      exclude)
            for file_name in matched:
                yield rel_dir_name, file_name

    def qualified_files(self, absolute=True):
        """An alternative generator that yields files rather than
        directory/file tuples.

        If *absolute* is false, paths relative to the starting directory
        are returned, otherwise files are fully qualified."""
        prefix = self.get_directory() if absolute else "."
        for rel_dir_name, file_name in self.files():
            yield path.join(prefix, rel_dir_name, file_name)

    def __iter__(self):
        """A natural iteration of files in the set.

        Files returned are relative, as if iterating ``self.qualified_files()``"""
        class FileSetIterator(object):
            """Gluecode class to return a lazy iterator over the fileset"""
            def __init__(self, file_set):
                self.file_set = file_set
                self.generator = None
            def __iter__(self):
                return self
            def next(self):
                if self.generator is None:
                    self.generator = self.file_set.qualified_files()
                return self.generator.next()
            def __str__(self):
                return "FileSetIterator on {0}".format(self.file_set)
        return FileSetIterator(self)

    def __str__(self):
        return "FileSet [directory={0}, include={1}, exclude={2}, symlinks? {3}]".\
                format(self.directory if self.directory else "CWD ({0})".format(getcwd()),
                       self.include.patterns,
                       self.exclude.patterns,
                       self.symlinks)