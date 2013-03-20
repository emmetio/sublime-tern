"""
Methods to work with and locate active projects
"""
import sys
import os
import os.path
import fnmatch
import glob
import json
import sublime
from formic import FileSet

is_python3 = sys.version_info[0] > 2

try:
	isinstance("", basestring)
	def isstr(s):
		return isinstance(s, basestring)
except NameError:
	def isstr(s):
		return isinstance(s, str)

def locate_project(file_path, lookup=[]):
	"""
	Locates project for given file: tries to find .sublime-project
	file in directory structure
	@param file_path: Absolute file path
	@param lookup: Hint with located projects to speed-up look-ups
	@returns: Project path if given file is inside project or None otherwise
	"""

	file_path = os.path.abspath(file_path)

	# check out located projects first
	for p in lookup:
		proj_dir = os.path.dirname(p)
		if file_path.startswith(proj_dir):
			return p
		
	previous_parent = ''
	parent = os.path.dirname(file_path)
	while parent and os.path.exists(parent) and parent != previous_parent:
		proj_file = find_project_in_dir(parent)
		if proj_file:
			return os.path.join(parent, proj_file)
		
		previous_parent = parent
		parent = os.path.dirname(parent)
	
	return None

def find_project_in_dir(dir_path):
	"Tries to locate .sublime-project file in given dir"
	for f in os.listdir(dir_path):
		if fnmatch.fnmatch(f, '*.sublime-project'):
			return f

def get_ternjs_config(project):
	"Returns TernJS config from project file"
	if os.path.exists(project):
		conf = json.load(open(project))
		return conf.get('ternjs', {})

	return {}

def get_ternjs_files(project, config=None):
	"""
	Returns list of absolute paths of .js files that matches
	given TernJS config. This method locates all .js files in
	project dir and applies "include" and "exclude" patterns
	from TernJS config
	"""
	if config is None:
		config = get_ternjs_config(project)

	proj_dir = os.path.dirname(project)
	fileset = FileSet(directory=proj_dir,
					  include=config.get('include', ['**/*.js']),
					  exclude=config.get('exclude', None))

	return [f for f in fileset.qualified_files()]


def projects_from_opened_files(window=None):
	"Returns list of projects for all opened files in editor"
	if window is None:
		windows = sublime.windows()
	else:
		windows = [window]

	result = set()
	for wnd in windows:
		for view in wnd.views():
			f = view.file_name()
			if f:
				result.add(locate_project(f, result))

	return list(result)





