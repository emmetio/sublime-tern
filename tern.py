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

# Project info cache
projects_cache = None

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
	sync_projects()


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
	if not globals()['projects_cache']:
		p = project.all_projects()
		p.append({'id': 'empty'})
		globals()['projects_cache'] = p

	return projects_cache

def sync_projects():
	if not ctx or not ctx.js(): return

	for p in all_projects():
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

def project_for_view(view):
	file_name = view.file_name()
	if file_name:
		for p in all_projects():
			proj_dir = os.path.dirname(p['id'])
			if file_name.startswith(proj_dir):
				return p
	
	return None
	

class JSRegistry(sublime_plugin.EventListener):
	def on_load(self, view):
		print('Loaded %s' % view.file_name())

# 	def on_activated(self, view):
# 		if is_js_view(view):
# 			print('Activating %s' % file_name_from_view(view))
# 			ctx.js().locals.registerDoc(view)

	def on_query_completions(self, view, prefix, locations):
		if not is_js_view(view):
			return []

		proj = project_for_view(view) or {}
		completions = ctx.js().locals.ternHints(view, proj.get('id', 'empty'))
		if completions and hasattr(completions, 'list'):
			cmpl = [completion_item(c) for c in completions['list']]
			# print(cmpl)
			return cmpl


		return []

	# def on_deactivated(self, view):
	# 	if is_js_view(view):
	# 		print('Deactivating %s' % file_name_from_view(view))
	# 		ctx.js().locals.unregisterDoc(view)
	
# class TernShowHints(sublime_plugin.TextCommand):
# 	"""Show JS hints for current document"""
# 	def run(self, edit, **kw):
# 		view = active_view()
# 		if is_js_view(view):
# 			print('Requesting hints')
# 			ctx.js().locals.ternHints(view, lambda x: print('hints: %s' % x['list']))
		
class TernGetProjects(sublime_plugin.TextCommand):
	def run(self, edit, **kw):
		projects = project.projects_from_opened_files()
		print(projects)
		if projects:
			print(project.get_ternjs_files(projects[0]))

def plugin_loaded():
	sublime.set_timeout(init, 200)

if not is_st3():
	init()