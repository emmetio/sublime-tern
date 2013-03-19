import sys
import os.path
import imp
import re

import sublime, sublime_plugin

BASE_PATH = os.path.abspath(os.path.dirname(__file__))
PACKAGES_PATH = sublime.packages_path() or os.path.dirname(BASE_PATH)
sys.path += [BASE_PATH] + [os.path.join(BASE_PATH, f) for f in ['ternjs']]

# Make sure all dependencies are reloaded on upgrade
if 'ternjs.reloader' in sys.modules:
	imp.reload(sys.modules['ternjs.reloader'])
import ternjs.reloader

import ternjs.pyv8loader as pyv8loader
from ternjs.context import js_file_reader as _js_file_reader
from ternjs.context import Context

# JS context
ctx = None

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
		print('Request contents of %s file' % f)
		if f[0] == '{' and f[-1] == '}':
			# it's unsaved file, locate it 
			buf_id = f[1:-1]
			print('Get buffer %s' % buf_id)
			view = view_for_buffer_id(buf_id)
			if view:
				return view.substr(sublime.Region(0, view.size()))
			else:
				return ''

		return _js_file_reader(f, True)

	contrib = {
		'sublimeReadFile': file_reader,
		'sublimeGetFileNameFromView': file_name_from_view
	}

	globals()['ctx'] = Context(
		reader=js_file_reader,
		contrib=contrib
	)

	ctx.js()

	print('Created context')

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
	

def js_file_reader(file_path, use_unicode=True):
	if hasattr(sublime, 'load_resource'):
		rel_path = file_path
		for prefix in [sublime.packages_path(), sublime.installed_packages_path()]:
			if rel_path.startswith(prefix):
				rel_path = os.path.join('Packages', rel_path[len(prefix) + 1:])
				break

		rel_path = rel_path.replace('.sublime-package', '')
		# for Windows we have to replace slashes
		print('Loading %s' % rel_path)
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


class JSRegistry(sublime_plugin.EventListener):
	def on_activated(self, view):
		if is_js_view(view):
			print('Activating %s' % file_name_from_view(view))
			ctx.js().locals.registerDoc(view)

	def on_query_completions(self, view, prefix, locations):
		if not is_js_view(view):
			return []

		completions = ctx.js().locals.ternHints(view)
		if completions and hasattr(completions, 'list'):
			cmpl = [completion_item(c) for c in completions['list']]
			# print(cmpl)
			return cmpl


		return []

	# def on_deactivated(self, view):
	# 	if is_js_view(view):
	# 		print('Deactivating %s' % file_name_from_view(view))
	# 		ctx.js().locals.unregisterDoc(view)
	
class TernShowHints(sublime_plugin.TextCommand):
	"""Show JS hints for current document"""
	def run(self, edit, **kw):
		view = active_view()
		if is_js_view(view):
			print('Requesting hints')
			ctx.js().locals.ternHints(view, lambda x: print('hints: %s' % x['list']))
		


def plugin_loaded():
	sublime.set_timeout(init, 200)

if not is_st3():
	init()