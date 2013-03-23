import sys
import os.path
import imp
import re
import json
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

	# setup environment for PyV8 loading
	pyv8_paths = [
		os.path.join(PACKAGES_PATH, 'PyV8'),
		os.path.join(PACKAGES_PATH, 'PyV8', pyv8loader.get_arch()),
		os.path.join(PACKAGES_PATH, 'PyV8', 'pyv8-%s' % pyv8loader.get_arch())
	]

	sys.path += pyv8_paths

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
	if f[0] == '{' and f[-1] == '}':
		# it's unsaved file, locate it 
		buf_id = f[1:-1]
		view = view_for_buffer_id(buf_id)
		if view:
			return view.substr(sublime.Region(0, view.size()))
		else:
			return ''

	file_path = f
	if not os.path.exists(file_path) and proj and proj['config']:
		# Unable to find file, it might be a RequireJS module.
		# If project contains "path" option, iterate on it
		proj_path = os.path.dirname(proj['id'])
		config = proj['config']
		if file_path[0] == '/':
			file_path = file_path[1:]

		paths = config['paths'] or []
		for p in paths:
			if not os.path.isabs(p):
				p = os.path.join(proj_path, p)

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
	return view.score_selector(0, 'source.js') > 0

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


def completion_item(item):
	"Returns ST completion representation for given Tern one"
	t = item['type']
	label = item['text']
	value = item['text']
	m = re.match(r'fn\((.*)\)', t)
	if m:
		fn_def = m.group(1) or ''
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

def sync_project(p):
	if not can_run(): return

	print('Syncing project %s' % p['id'])

	config = p.get('config', {})
	# collect libraries for current project
	libs = copy(ternjs.DEFAULT_LIBS);
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
	ctx.js().locals.startServer(json.dumps(p, ensure_ascii=False), resolved_libs)

def sync_all_projects():
	if not can_run(): return

	for p in all_projects():
		sync_project(p)

def reset_project(p):
	if not can_run(): return

	ctx.js().locals.killServer(p['id'])

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
		view.sel().add(sublime.Region(dfn['start'], dfn['end']));

	globals()['_jump_def'] = None

class TernJSEventListener(sublime_plugin.EventListener):
	def on_load(self, view):
		if is_js_view(view):
			apply_jump_def(view)
			p = project.project_for_view(view)
			if p:
				sync_project(p)

	def on_post_save(self, view):
		file_name = view.file_name()
		if file_name and file_name.endswith('.sublime-project'):
			# Project file was updated, re-scan all projects
			return reload_ternjs()

		if is_js_view(view):
			p = project.project_for_view(view)
			if p:
				# currently, there's no easy way to push
				# updated JS file to existing TernJS server
				# so we have to kill it first and then start again
				reset_project(p)
				sync_project(p)
			return


	def on_query_completions(self, view, prefix, locations):
		if not can_run(): return []

		if not is_js_view(view) or view.get_regions(rename_region_key):
			return []

		proj = project.project_for_view(view) or {}
		completions = ctx.js().locals.ternHints(view, proj.get('id', 'empty'))
		if completions and hasattr(completions, 'list'):
			cmpl = [completion_item(c) for c in completions['list']]
			# print(cmpl)
			return cmpl


		return []

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
		dfn = ctx.js().locals.ternJumpToDefinition(view, proj.get('id', 'empty'))
		if dfn:
			target_file = dfn['file']
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
		refs = ctx.js().locals.ternFindRefs(view, proj.get('id', 'empty'))
		
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
			view.sel().clear()
			view.sel().add_all(regions)
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


def plugin_loaded():
	init()

if not is_st3():
	sublime.set_timeout(init, 200)