import sys
import os.path
import imp
import re
import json
import threading
import fnmatch
from copy import copy

import sublime, sublime_plugin

BASE_PATH = os.path.abspath(os.path.dirname(__file__))
PACKAGES_PATH = sublime.packages_path() or os.path.dirname(BASE_PATH)
sys.path += [BASE_PATH] + [os.path.join(BASE_PATH, f) for f in ['ternjs']]

# Make sure all dependencies are reloaded on upgrade
if 'ternjs.reloader' in sys.modules:
	imp.reload(sys.modules['ternjs.reloader'])
import ternjs.reloader

import ternjs.pyv8loader as pyv8loader
import ternjs.tern_plugin as plugin
import ternjs.project as project
import ternjs.context as ternjs
from ternjs.context import js_file_reader as _js_file_reader

# JS context
ctx = None

# Default ST settings
user_settings = None

_jump_def = None
_rename_session = None

rename_region_key = 'ternjs-rename-region'

icons = {
	'object':  '{}',
	'array':   '[]',
	'number':  '(num)',
	'string':  '(str)',
	'bool':    '(bool)',
	'fn':      'fn()',
	'unknown': '(?)'
}

def is_st3():
	return sublime.version()[0] == '3'

def init():
	globals()['user_settings'] = sublime.load_settings('Preferences.sublime-settings')
	globals()['settings'] = sublime.load_settings('TernJS.sublime-settings')

	# setup environment for PyV8 loading
	pyv8_paths = [
		os.path.join(PACKAGES_PATH, 'PyV8'),
		os.path.join(PACKAGES_PATH, 'PyV8', pyv8loader.get_arch()),
		os.path.join(PACKAGES_PATH, 'PyV8', 'pyv8-%s' % pyv8loader.get_arch())
	]

	sys.path += pyv8_paths

	# unpack recently loaded binary, is exists
	for p in pyv8_paths:
		pyv8loader.unpack_pyv8(p)

	contrib = {
		'sublimeReadFile': ternjs_file_reader,
		'sublimeGetFileNameFromView': file_name_from_view,
		'sublimeViewContents': view_contents
	}

	delegate = SublimeLoaderDelegate()
	globals()['ctx'] = ternjs.Context(
		reader=js_file_reader,
		contrib=contrib,
		logger=delegate.log
	)

	pyv8loader.load(pyv8_paths[1], delegate) 

	if can_run():
		sync_all_projects()

class SublimeLoaderDelegate(pyv8loader.LoaderDelegate):
	def __init__(self, settings=None):
		if settings is None:
			settings = {}
			for k in ['http_proxy', 'https_proxy', 'timeout']:
				if user_settings.has(k):
					settings[k] = user_settings.get(k, None)

		pyv8loader.LoaderDelegate.__init__(self, settings)
		self.state = None
		self.message = 'Loading PyV8 binary, please wait'
		self.i = 0
		self.addend = 1
		self.size = 8

	def on_start(self, *args, **kwargs):
		self.state = 'loading'

	def on_progress(self, *args, **kwargs):
		if kwargs['progress'].is_background:
			return
			
		before = self.i % self.size
		after = (self.size - 1) - before
		msg = '%s [%s=%s]' % (self.message, ' ' * before, ' ' * after)
		if not after:
			self.addend = -1
		if not before:
			self.addend = 1
		self.i += self.addend

		sublime.set_timeout(lambda: sublime.status_message(msg), 0)

	def on_complete(self, *args, **kwargs):
		self.state = 'complete'
		def _c():
			sublime.status_message('PyV8 binary successfully loaded')
			if can_run():
				sync_all_projects()

		sublime.set_timeout(_c, 0)

	def on_error(self, exit_code=-1, thread=None):
		self.state = 'error'
		sublime.set_timeout(lambda: show_pyv8_error(exit_code), 0)

	def setting(self, name, default=None):
		"Returns specified setting name"
		return self.settings.get(name, default)

	def log(self, message):
		print('TernJS: %s' % message)

def show_pyv8_error(exit_code):
	if 'PyV8' not in sys.modules:
		sublime.error_message('Error while loading PyV8 binary: exit code %s \nTry to manually install PyV8 from\nhttps://github.com/emmetio/pyv8-binaries' % exit_code)

def ternjs_file_reader(f, proj=None):
	# print('request file %s' % f)
	if f[0] == '{' and f[-1] == '}':
		# it's unsaved file, locate it 
		buf_id = f[1:-1]
		view = view_for_buffer_id(buf_id)
		if view:
			return view.substr(sublime.Region(0, view.size()))
		else:
			return ''

	file_path = f
	if not os.path.isabs(file_path) and proj and proj['dir']:
		file_path = os.path.join(proj['dir'], file_path)

	if not os.path.exists(file_path) and proj and proj['config']:
		# are we using NodeJS plugin? If so, try to resolve it
		# with different extensions
		found = False
		for ext in ['.js', '.json']:
			if os.path.exists(file_path + ext):
				found = True
				file_path += ext
				break

		if not found:
			# Unable to find file, it might be a RequireJS module.
			# If project contains "path" option, iterate on it
			proj_path = os.path.dirname(proj['id'])
			if file_path[0] == '/':
				file_path = file_path[1:]


			lookup_paths = [proj_path]

			config = proj['config']
			if hasattr(config, 'paths'):
				for p in config['paths']:
					if not os.path.isabs(p):
						p = os.path.join(proj_path, p)
					lookup_paths.append(p)


			for p in lookup_paths:
				target_path = os.path.join(p, file_path)
				if os.path.exists(target_path):
					file_path = target_path
					break

	try:
		return _js_file_reader(file_path, True)
	except Exception as e:
		print(e)
		return None

def file_name_from_view(view):
	name = view.file_name()
	if name is None:
		name = '{%s}' % view.buffer_id()

	return name

def view_for_buffer_id(buf_id):
	for w in sublime.windows():
		for v in w.views():
			if str(v.buffer_id()) == buf_id:
				return v

	return None

def view_contents(view):
	return view.substr(sublime.Region(0, view.size()))

def js_file_reader(file_path, use_unicode=True):
	if hasattr(sublime, 'load_resource'):
		rel_path = None
		for prefix in [sublime.packages_path(), sublime.installed_packages_path()]:
			if file_path.startswith(prefix):
				rel_path = os.path.join('Packages', file_path[len(prefix) + 1:])
				break

		if rel_path:
			rel_path = rel_path.replace('.sublime-package', '')
			# for Windows we have to replace slashes
			# print('Loading %s' % rel_path)
			rel_path = rel_path.replace('\\', '/')
			return sublime.load_resource(rel_path)

	return _js_file_reader(file_path, use_unicode)

def is_js_view(view):
	return view.score_selector(0, settings.get('syntax_scopes', 'source.js')) > 0

def can_run():
	return ctx and ctx.js()

def active_view():
	return sublime.active_window().active_view()

def completion_hint(t):
	suffix = ''
	if t == '?':
		suffix = 'unknown'
	elif t == "number" or t == "string" or t == "bool":
		suffix = t
	elif re.match(r'fn\(', t):
		suffix = 'fn'
	elif re.match(r'\[', t):
		suffix = 'array'
	else:
		suffix = 'object'

	return icons.get(suffix, suffix)

def sanitize_func_def(fn):
	"""
	Parses function definition from given completion.
	The function might be quite complex, something like this:
	fn(arg1 : str, arg2 : fn(arg3 : str, arg4 : str))
	"""
	m = re.match(r'fn\(', fn)
	if not m: return None

	args_str = re.sub(r'->\s*[^\)]*$', '', fn).strip()
	args_str = args_str[3:-1]
	sanitized_args = ''
	i = 0
	ln = len(args_str)
	braces_stack = 0

	while i < ln:
		ch = args_str[i]
		if ch == '(':
			braces_stack += 1
			j = i + 1
			while j < ln:
				ch2 = args_str[j]
				if   ch2 == '(': braces_stack += 1
				elif ch2 == ')': braces_stack -= 1
				if braces_stack == 0: break
				j += 1

			i = j
		else:
			sanitized_args += ch
		
		i += 1

	return sanitized_args



def completion_item(item):
	"Returns ST completion representation for given Tern one"
	t = item['type']
	label = item['text']
	value = item['text'].replace('$', '\\$')
	fn_def = sanitize_func_def(t)
	if fn_def is not None:
		args = [p.split(':')[0].strip() for p in fn_def.split(',')]
		label += '(%s)' % ', '.join(args)

		# split args into mandatory and optional lists
		opt_pos = len(args)
		for i, a in enumerate(args):
			if a and a[-1] == '?':
				opt_pos = i
				break

		mn_args = args[0:opt_pos]
		opt_args = args[opt_pos:]
		value += '(' + ', '.join(['${%d:%s}' % (i + 1, v) for i, v in enumerate(mn_args)])
		if opt_args:
			offset = len(mn_args)
			opt_args_str = ', '.join(['${%d:%s}' % (offset + i + 2, v[:-1]) for i, v in enumerate(opt_args)])
			value += '${%d:, %s}' % (offset + 1, opt_args_str)

		value += ')'
	else:
		label += '\t%s' % completion_hint(t)

	return (label, value)

def all_projects():
	proj = copy(project.all_projects())
	proj.append({'id': 'empty'})
	return proj

def sync_project(p, check_exists=False):
	if not can_run(): return

	with ctx.js() as c:
		if check_exists and c.locals.hasServer(p['id']):
			return

	print('Syncing project %s' % p['id'])

	config = p.get('config', {})
	# collect libraries for current project
	libs = copy(settings.get('default_libs', []));
	for l in config.get('libs', []):
		if l not in libs:
			libs.append(l)

	# resolve all libraries
	resolved_libs = []
	project_dir = os.path.dirname(p['id'])
	for l in libs:
		if l in ctx.default_libs:
			resolved_libs.append(ctx.default_libs[l])
		else:
			# it's not a predefined library, try lo read it from disk
			lib_path = l
			if not os.path.isabs(lib_path):
				lib_path = os.path.normpath(os.path.join(project_dir, lib_path))

			if os.path.isfile(lib_path):
				resolved_libs.append(_js_file_reader(lib_path))

	# pass data as JSON string to ensure that all
	# data types are valid
	with ctx.js() as c:
		c.locals.startServer(json.dumps(p, ensure_ascii=False), resolved_libs)

class ProjectSyncThread(threading.Thread):
	def __init__(self, projects):
		self.projects = projects
		threading.Thread.__init__(self)

	def run(self):
		print('Start syncing')
		for p in self.projects:
			sync_project(p)


def sync_all_projects():
	if not can_run(): return

	# thread = ProjectSyncThread(all_projects())
	# thread.start()

	for p in all_projects():
		sync_project(p)

def reset_project(p):
	if not can_run(): return
	with ctx.js() as c:
		c.locals.killServer(p['id'])

def reset_all_projects():
	if not can_run(): return
	for p in all_projects():
		reset_project(p)

def reload_ternjs():
	reset_all_projects()
	project.reset_cache()
	sync_all_projects()

def apply_jump_def(view, dfn=None):
	if not dfn:
		dfn = _jump_def

	if not dfn: return

	if dfn['file'] == file_name_from_view(view):
		view.sel().clear()
		r = sublime.Region(int(dfn['start']), int(dfn['end']))
		view.sel().add(r);
		sublime.set_timeout(lambda: view.show(view.sel()), 1)

	globals()['_jump_def'] = None

def completions_allowed(view):
	"Check if TernJS completions allowed for given view"
	caret_pos = view.sel()[0].begin()
	if not is_js_view(view) or not view.score_selector(caret_pos, '-string -comment'):
		return False

	proj = project.project_for_view(view)
	if proj and 'disable_completions' in proj['config']:
		patterns = proj['config']['disable_completions']
		if not isinstance(patterns, list):
			patterns = [patterns]

		for p in patterns:
			if fnmatch.fnmatch(view.file_name(), p):
				return False

	return True

class TernJSEventListener(sublime_plugin.EventListener):
	def on_load(self, view):
		if is_js_view(view):
			apply_jump_def(view)
			p = project.project_for_view(view)
			if p:
				sync_project(p, True)

	def on_post_save(self, view):
		file_name = view.file_name()
		if file_name and file_name.endswith('.sublime-project'):
			# Project file was updated, re-scan all projects
			return reload_ternjs()

		if is_js_view(view):
			p = project.project_for_view(view)
			if p:
				def _callback():
					with ctx.js() as c:
						c.locals.forceFileUpdate(view, p['id'])

				sublime.set_timeout(_callback, 1)
			return


	def on_query_completions(self, view, prefix, locations):
		if not completions_allowed(view) or view.get_regions(rename_region_key) or not can_run():
			return None

		proj = project.project_for_view(view) or {}
		with ctx.js() as c:
			completions = c.locals.ternHints(view, proj.get('id', 'empty'))
			if completions and hasattr(completions, 'list'):
				cmpl = [completion_item(_c) for _c in completions['list']]
				# print(cmpl)
				return cmpl


		return None

	def on_query_context(self, view, key, op, operand, match_all):
		if key == 'ternjs.rename':
			r = view.get_regions(rename_region_key)
			if r and _rename_session:
				return True

		return None


class TernjsReload(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		active_view().erase_regions(rename_region_key)
		reload_ternjs()

class TernjsJumpToDefinition(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		if not can_run(): return
		view = active_view()

		proj = project.project_for_view(view) or {}
		with ctx.js() as c:
			dfn = c.locals.ternJumpToDefinition(view, proj.get('id', 'empty'))
			if dfn:
				target_file = dfn['file']

				# resolve target file
				if not os.path.isabs(target_file) and proj.get('id', 'empty')  != 'empty':
					target_file = os.path.join(proj['dir'], target_file)
					dfn['file'] = target_file

				if target_file != file_name_from_view(view):
					target_view = view.window().open_file(target_file)

					if not target_view.is_loading():
						apply_jump_def(target_view, dfn)
					else:
						globals()['_jump_def'] = dfn
						return
				else:
					apply_jump_def(view, dfn)

class TernjsRenameVariable(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		if not can_run(): return
		view = active_view()

		proj = project.project_for_view(view) or {}
		with ctx.js() as c:
			refs = c.locals.ternFindRefs(view, proj.get('id', 'empty'))
			
			# do rename for local references only
			regions = []
			file_name = file_name_from_view(view)
			caret_pos = view.sel()[0].begin()
			ctx_region = None

			for r in refs['refs']:
				if file_name == r['file']:
					rg = sublime.Region(r['start'], r['end'])
					if rg.contains(caret_pos):
						ctx_region = len(regions)
					regions.append(rg)

			if regions:
				sel = view.sel()
				sel.clear()
				for r in regions:
					sel.add(r)
				view.add_regions(rename_region_key, regions, 'string', flags=sublime.HIDDEN)

				# create rename session
				globals()['_rename_session'] = {
					'old_name': view.substr(view.sel()[0]),
					'ctx_region': ctx_region,
					'caret_pos': caret_pos
				}

class TernjsCommitRename(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		view = active_view()
		regions = view.get_regions(rename_region_key)
		view.erase_regions(rename_region_key)
		if regions:
			ctx_region = _rename_session['ctx_region']
			if ctx_region < len(regions):
				r = regions[ctx_region]
				view.sel().clear()
				view.sel().add(sublime.Region(r.b, r.b))

		globals()['_rename_session'] = None

class FindOccurance(sublime_plugin.TextCommand):
	def get_regions(self, direction='next'):
		if not can_run(): return
		view = active_view()

		proj = project.project_for_view(view) or {}
		with ctx.js() as c:
			refs = c.locals.ternFindRefs(view, proj.get('id', 'empty'))

			# use local references only
			regions = []
			file_name = file_name_from_view(view)

			for r in refs['refs']:
				if file_name == r['file']:
					regions.append(sublime.Region(r['start'], r['end']))

			return regions

class TernjsNextOccurance(FindOccurance):
	def run(self, edit, **kw):
		view = active_view()
		caret_pos = view.sel()[0].begin()

		for r in self.get_regions():
			if r.begin() > caret_pos:
				view.sel().clear()
				view.sel().add(r)
				view.show(r)
				return

class TernjsPreviousOccurance(FindOccurance):
	def run(self, edit, **kw):
		view = active_view()
		caret_pos = view.sel()[0].begin()

		for r in reversed(self.get_regions()):
			if r.begin() < caret_pos:
				view.sel().clear()
				view.sel().add(r)
				view.show(r)
				return

def plugin_loaded():
	init()

if not is_st3():
	sublime.set_timeout(init, 200)