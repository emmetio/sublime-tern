"TernJS plugin definition"
import os.path
import json
from copy import copy

_plugin_registry = set()

try:
	isinstance("", basestring)
	def isstr(s):
		return isinstance(s, basestring)
except NameError:
	def isstr(s):
		return isinstance(s, str)

def get_plugin(plugin, ctx, project=None):
	"Factory method that returns plugin instance for given spec"
	plugin = parse_plugin_def(plugin, ctx, project)
	p = TernPlugin(plugin)
	if p.id not in _plugin_registry:
		path = p.path
		if not isinstance(path, list):
			path = [path]

		try:
			for _p in path:
				ctx.eval_js_file(_p)
				p.path = _p
				_plugin_registry.add(_p)
				break
		except Exception as e:
			print(e)

	return p

def get_plugins_from_project(project, ctx):
	"Returns list of plugins from project definition"
	config = project.get('config', None)
	result = []
	if 'plugins' in config:
		for k, v in enumerate(config['plugins']):
			v = copy(v)
			v['pluginId'] = k
			plugin = get_plugin(v, ctx, project)
			if plugin:
				result.append(plugin)

	return result

def parse_plugin_def(plugin, ctx, project=None):
	"Parses plugin definition into normalized object"
	if isstr(plugin):
		plugin = json.loads(plugin)
	
	plugin_file = os.path.join('%s.js' % plugin['pluginId'])
	paths = []

	project_path = None
	if project and project['id'] != 'empty':
		project_path = os.path.dirname(project['id'])

	# look for plugin by specified path
	if 'pluginPath' in plugin:
		if project_path:
			paths.append(os.path.join(project_path, plugin['pluginPath']))
		else:
			paths.append(plugin['pluginPath'])

	# look for local plugin
	paths.append('plugin')

	# look for plugin in project
	if project_path:
		paths.append(project_path)

	plugin['pluginPath'] = [os.path.join(p, plugin_file) for p in paths]

	# try to find plugin
	# for p in paths:
	# 	try:
	# 		plugin_path = os.path.join(p, plugin_file)
	# 		ctx.eval_js_file(plugin_path, True)
	# 		plugin['pluginPath'] = plugin_path
	# 		break
	# 	except Exception as e:
	# 		continue

	return plugin


class TernPlugin():
	"""
	Tern plugin instance.
	You should not use this class directly, `get_plugin` or
	`get_plugins_from_project` instead
	"""
	def __init__(self, plugin):
		self.plugin = copy(plugin)
		self.id = plugin['pluginId']
		self.path = plugin['pluginPath']
		self.definitions = None

		plugin = copy(plugin)
		for k in ['pluginId', 'pluginPath']:
			if k in plugin:
				del plugin[k]

		self.config = plugin

