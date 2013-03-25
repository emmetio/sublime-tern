import sys
import imp

# Dependecy reloader for Emmet plugin
# The original idea is borrowed from 
# https://github.com/wbond/sublime_package_control/blob/master/package_control/reloader.py 

reload_mods = []
for mod in sys.modules:
	if mod.startswith('ternjs') and sys.modules[mod] != None:
		reload_mods.append(mod)

mods_load_order = [
	'ternjs.tern_plugin',
	'ternjs.pyv8loader',
	'ternjs.context',
	'ternjs.formic',
	'ternjs.project'
]

for mod in mods_load_order:
	if mod in reload_mods:
		imp.reload(sys.modules[mod])