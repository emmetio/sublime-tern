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

_cache = None

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
	if project and os.path.exists(project):
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
	project_path = None
	if isinstance(project, dict):
		project_path = project['id']
		config = project['config']
	else:
		project_path = project

	if config is None:
		config = get_ternjs_config(project_path)

	proj_dir = config.get('dir', os.path.dirname(project_path))
	fileset = FileSet(directory=proj_dir,
					  include=config.get('include', ['**/*.js']),
					  exclude=config.get('exclude', None))

	return [resolve_project_file_path(f, proj_dir) for f in fileset.qualified_files()]

def resolve_project_file_path(f, project_dir):
	if f.startswith(project_dir):
		return os.path.relpath(f, project_dir)

	return f
		

def projects_from_opened_files(window=None):
	"Returns list of projects for all opened files in editor"
	if window is None:
		windows = sublime.windows()
	else:
		windows = [window]

	result = set()
	for wnd in windows:
		for view in wnd.views():
			proj = None
			if hasattr(view, 'project_file_name'):
				# ST3 API: get project file from opened view
				proj = view.project_file_name()
			else:
				f = view.file_name()
				if f:
					proj = locate_project(f, result)
			if proj:
				result.add(proj)

	return list(result)

def all_projects(no_cache=False):
	"""
	Returns data about all available projects
	for current ST instance
	"""
	if _cache and not no_cache:
		return _cache

	result = [info(p) for p in projects_from_opened_files()]

	globals()['_cache'] = result
	return result

def info(project_id):
	config = get_ternjs_config(project_id)
	return {
		'id': project_id,
		'dir':  config.get('dir', os.path.dirname(project_id)),
		'config': config,
		'files': get_ternjs_files(project_id, config)
	}

def project_for_view(view):
	"Returns project info for given view"
	file_name = view.file_name()

	projects = all_projects()

	if not file_name:
		# for new files, try to map it to any opened
		# project file of current window
		wnd_projects = projects_from_opened_files(view.window())
		if wnd_projects:
			project_id = wnd_projects[0]
			for p in projects:
				if p['id'] == project_id:
					return p

		return None

	# check if file inside project
	for p in projects:
		proj_dir = p.get('dir')
		proj_files = p['files']
		if proj_dir:
			proj_files = [os.path.join(proj_dir, pfile) for pfile in proj_files]

		if file_name in proj_files:
			return p

	# file is not inside any known project: it might be a new file
	# check if it matches project patterns
	for p in projects:
		files = get_ternjs_files(p)
		if file_name in files:
			p['files'] = files
			return p

	return None

def reset_cache():
	globals()['_cache'] = None

def in_cache(project_id):
	"Check if given project is in cache"
	if _cache:
		if isinstance(project_id, dict):
			project_id = project_id.get('id')

		for p in _cache:
			if p['id'] == project_id:
				return True

	return False

def add_to_cache(project_id):
	if isinstance(project_id, dict):
		project_id = project_id.get('id')

	if not in_cache(project_id):
		if not _cache:
			globals()['_cache'] = []

		globals()['_cache'].append(info(project_id))

