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
	# setup environment for PyV8 loading
	pyv8_paths = [
		os.path.join(PACKAGES_PATH, 'PyV8'),
		os.path.join(PACKAGES_PATH, 'PyV8', pyv8loader.get_arch()),
		os.path.join(PACKAGES_PATH, 'PyV8', 'pyv8-%s' % pyv8loader.get_arch())
	]

	sys.path += pyv8_paths

	def file_reader(f):
		if f[0] == '{' and f[-1] == '}':
			# it's unsaved file, locate it 
			buf_id = f[1:-1]
			view = view_for_buffer_id(buf_id)
			if view:
				return view.substr(sublime.Region(0, view.size()))
			else:
				return ''

		return _js_file_reader(f, True)

	contrib = {
		'sublimeReadFile': file_reader,
		'sublimeGetFileNameFromView': file_name_from_view,
		'sublimeViewContents': view_contents
	}

	globals()['ctx'] = ternjs.Context(
		reader=js_file_reader,
		contrib=contrib
	)

	ctx.js()
	sync_all_projects()


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
		rel_path = file_path
		for prefix in [sublime.packages_path(), sublime.installed_packages_path()]:
			if rel_path.startswith(prefix):
				rel_path = os.path.join('Packages', rel_path[len(prefix) + 1:])
				break

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

	return icons[suffix]


def completion_item(item):
	"Returns ST completion representation for given Tern one"
	t = item['type']
	label = item['text']
	m = re.match(r'fn\((.*)\)', t)
	if m:
		fn_def = m.group(1) or ''
		args = [p.split(':')[0].strip() for p in fn_def.split(',')]
		label += '(%s)' % ', '.join(args)
	else:
		label += '\t%s' % completion_hint(t)

	return (label, item['text'])

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
		if is_js_view(view):
			p = project.project_for_view(view)
			if p:
				# currently, there's no easy way to push
				# updated JS file to existing TernJS server
				# so we have to kill it first and then start again
				reset_project(p)
				sync_project(p)
			return

		file_name = view.file_name()
		if file_name and file_name.endswith('.sublime-project'):
			# Project file was updated, re-scan all projects
			reload_ternjs()


	def on_query_completions(self, view, prefix, locations):
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
	sublime.set_timeout(init, 200)

if not is_st3():
	sublime.set_timeout(init, 200)