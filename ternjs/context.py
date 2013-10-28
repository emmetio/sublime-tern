# coding=utf-8
import sys
import os
import os.path
import codecs
import json
import gc
import imp
import re
import tern_plugin

is_python3 = sys.version_info[0] > 2

BASE_PATH = os.path.abspath(os.path.dirname(__file__))
LIBS_PATH = os.path.join(BASE_PATH, 'defs')
TERNJS_LIBS = ['ecma5.json', 'browser.json', 'jquery.json', 'underscore.json']

# Default libraries that should be loaded for every project
DEFAULT_LIBS = ['ecma5']

TERNJS_FILES = ['js/bootstrap.js',
			  'js/acorn.js', 'js/acorn_loose.js', 'js/walk.js',
			  'lib/signal.js', 'lib/tern.js', 'lib/comment.js','lib/def.js', 'lib/jsdoc.js', 'lib/infer.js',
			  'js/lodash.js', 'js/controller.js']

try:
	isinstance("", basestring)
	def isstr(s):
		return isinstance(s, basestring)
except NameError:
	def isstr(s):
		return isinstance(s, str)

def should_use_unicode():
	"""
	WinXP unable to eval JS in unicode object (while other OSes requires it)
	This function checks if we have to use unicode when reading files
	"""
	ctx = PyV8.JSContext()
	ctx.enter()
	use_unicode = True
	try:
		ctx.eval(u'(function(){return;})()')
	except:
		use_unicode = False

	ctx.leave()

	return use_unicode

def make_path(filename):
	return os.path.normpath(os.path.join(BASE_PATH, filename))

def js_log(message):
	print(message)

def js_file_reader(file_path, use_unicode=True):
	if use_unicode:
		f = codecs.open(file_path, 'r', 'utf-8')
	else:
		f = open(file_path, 'r')

	content = f.read()
	f.close()

	return content

def import_pyv8():
	# Importing non-existing modules is a bit tricky in Python:
	# if we simply call `import PyV8` and module doesn't exists,
	# Python will cache this failed import and will always
	# throw exception even if this module appear in PYTHONPATH.
	# To prevent this, we have to manually test if
	# PyV8.py(c) exists in PYTHONPATH before importing PyV8
	if 'PyV8' in sys.modules and 'PyV8' not in globals():
		# PyV8 was loaded by ST2, create global alias
		globals()['PyV8'] = __import__('PyV8')
		return

	loaded = False
	f, pathname, description = imp.find_module('PyV8')
	bin_f, bin_pathname, bin_description = imp.find_module('_PyV8')
	if f:
		try:
			imp.acquire_lock()
			globals()['_PyV8'] = imp.load_module('_PyV8', bin_f, bin_pathname, bin_description)
			globals()['PyV8'] = imp.load_module('PyV8', f, pathname, description)
			imp.release_lock()
			loaded = True
		finally:
			# Since we may exit via an exception, close fp explicitly.
			if f:
				f.close()
			if bin_f:
				bin_f.close()

	if not loaded:
		raise ImportError('No PyV8 module found')


class Context():
	"""
	Creates Emmet JS core context.
	Before instantiating this class, make sure PyV8
	is available in `sys.path`

	@param files: Additional files to load with JS core
	@param path: Path to Emmet extensions
	@param contrib: Python objects to contribute to JS execution context
	@param pyv8_path: Location of PyV8 binaries
	"""
	def __init__(self, files=[], contrib=None, logger=None, reader=js_file_reader):
		self.logger = logger
		self.reader = reader

		try:
			import_pyv8()
		except ImportError as e:
			pass

		self._ctx = None
		self._contrib = contrib

		# detect reader encoding
		self._use_unicode = None
		self._core_files = [] + TERNJS_FILES + files
		self.default_libs = self._create_env()

	def log(self, message):
		if self.logger:
			self.logger(message)

	def _create_env(self):
		"Creates environment for TernJS server"
		libs = {}
		for file_name in TERNJS_LIBS:
			name, ext = os.path.splitext(file_name)
			libs[name] = self.read_js_file(os.path.join(LIBS_PATH, file_name))

		return libs

	def load_plugin(self, p, project=None):
		"""
		Loads and initiates TernJS plugin. Returns additional defs
		that plugin requires to operate properly
		"""
		return tern_plugin.get_plugin(p, self, project)

	def js(self):
		"Returns JS context"
		if not self._ctx:
			try:
				import_pyv8()
			except ImportError as e:
				return None

			if 'PyV8' not in sys.modules:
				# Binary is not available yet
				return None

			if self._use_unicode is None:
				self._use_unicode = should_use_unicode()

			class JSContext(PyV8.JSContext):
				def __enter__(self):
					if not hasattr(self, '_counter'):
						self._counter = 0
					if not self._counter:
						self.lock = PyV8.JSLocker()
						self.lock.enter()
						self.enter()
						# print('Enter JS context')

					self._counter += 1
					return self

				def __exit__(self, exc_type, exc_value, traceback):
					self._counter -= 1
					if self._counter < 1 or exc_type is not None:
						# print('Exit JS context')
						self._counter = 0
						if self:
							self.leave()
						if self.lock:
							self.lock.leave()
							self.lock = None

			self._ctx = JSContext()

			for f in self._core_files:
				self.eval_js_file(f)

			# expose some methods
			with self._ctx as ctx:
				self._ctx.locals.log = js_log
				self._ctx.locals.loadPlugin = self.load_plugin

				if self._contrib:
					for k in self._contrib:
						self._ctx.locals[k] = self._contrib[k]

		return self._ctx

	def reset(self):
		"Resets JS execution context"
		if self._ctx:
			self._ctx = None
			try:
				PyV8.JSEngine.collect()
				gc.collect()
			except:
				pass


	def read_js_file(self, file_path, resolve_path=False):
		full_path = make_path(file_path) if resolve_path else file_path
		return self.reader(full_path, self._use_unicode)

	def eval(self, source):
		with self.js() as ctx:
			ctx.eval(source)

	def eval_js_file(self, file_path, resolve_path=True):
		with self.js() as ctx:
			ctx.eval(self.read_js_file(file_path, resolve_path), name=file_path, line=0, col=0)

