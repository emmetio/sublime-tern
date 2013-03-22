/**
 * Since user can open multiple projects on single ST instance,
 * we have to create individual server for each project
 * @type {Object}
 */
var ternServers = {};
var ternDocs = [];

function startServer(project, libs) {
	if (_.isString(project)) {
		project = JSON.parse(project);
	}

	libs = _.toArray(libs)
	
	log('Staring TernJS server for ' + project.id + ' with ' + libs.length + ' libs');
	
	if (!(project.id in ternServers)) {
		var env = _.map(libs || [], function(v, k) {
			return _.isString(v) ? JSON.parse(v) : v;
		});

		ternServers[project.id] = new tern.Server({
			getFile: getFile, 
			environment: env, 
			debug: true
		});
	}

	if (project.files) {
		var updated = syncFiles(ternServers[project.id], project.files);
		if (updated) {
			// server was updated. Initiate a fake request 
			// to make sure that first completions request won't take
			// too much time
			var fakeRequest = {
				query: {
					type: 'completions',
					end: 0,
					file: '{empty}'
				},
				files: [{
					name: '{empty}',
					type: 'full',
					text: ''
				}]
			};

			ternServers[project.id].request(fakeRequest, function() {});
		}
	}
}

function killServer(project) {
	var serverId = project.id || project;
	var server = ternServers[serverId];
	if (server) {
		server.reset();
		delete ternServers[serverId];
	}
}

function killAllServers() {
	_.each(ternServers, function(server, id) {
		killServer(id);
	});
}

/**
 * Sync project files with active server
 * @param  {tern.Server} server Server instance to update
 * @param  {Array} files  Actual project file list
 */
function syncFiles(server, files) {
	var loadedFiles = [];
	if (server.files) {
		loadedFiles = _.pluck(server.files, 'name');
	}

	var toAdd = _.difference(files, loadedFiles);
	var toRemove = _.difference(loadedFiles, files);

	_.each(toAdd, function(f) {
		server.addFile(f);
	});

	_.each(toRemove, function(f) {
		server.delFile(f);
	});

	if (toRemove.length) {
		server.reset();
	}

	return toAdd.length || toRemove.length;
}

function getFile(file, callback) {
	log('Requesting file ' + file);
	var content = sublimeReadFile(file);
	// if (!/(underscore)\.js$/.test(file)) {
	// 	content = sublimeReadFile(file);
	// }
	return callback(null, content);
}

/**
 * Returns reference to registered document from given
 * view object
 * @param  {sublime.View} view 
 * @return {Objec}
 */
function docFromView(view) {
	var fileName = sublimeGetFileNameFromView(view);
	return _.find(ternDocs, function(d) {
		return d.name == fileName;
	});
}

function buildRequest(view, query, allowFragments) {
	var files = [], offset = 0, startPos, endPos;
	var sel = view.sel()[0];

	if (typeof query == "string") {
		query = {type: query};
	}

	if (query.end == null && query.start == null) {
		query.end = endPos = sel.end();
		if (!sel.empty()) {
			query.start = startPos = sel.begin();
		}
	} else {
		endPos = query.end;
		// query.end = cm.indexFromPos(endPos = query.end);
		if (query.start != null) {
			startPos = query.start;
		}
	}

	if (!startPos) {
		startPos = endPos;
	}
	
	var fileName = sublimeGetFileNameFromView(view);
	query.file = fileName;
	if (view.is_dirty()) {
		files.push({
			name: fileName,
			type: 'full',
			text: sublimeViewContents(view)
		});
	}

	return {
		request: {
			query: query, 
			files: files
		},
		offset: offset
	};
}

function sendRequest(request, projectId) {
	var server = ternServers[projectId];
	var res = null;
	if (!server) {
		log('No sutable server for project "' + projectId + '"');
		return null;
	}

	server.request(request, function(error, data) {
		if (error) {
			throw error;
		}

		res = data;
	});

	return res;
}

function ternHints(view, projectId, callback) {
	var req = buildRequest(view, "completions");
	// log(JSON.stringify(req));
	var res = sendRequest(req.request, projectId);
	if (res) {
		var completions = _.map(res.completions, function(completion) {
			return {
				text: completion.name,
				type: completion.type,
				guess: !!res.guess
			};
		});

		return {
			from: res.from + req.offset,
			to: res.to + req.offset,
			list: completions
		};
	}
}

function ternJumpToDefinition(view, projectId) {
	var req = buildRequest(view, "definition", false);
	return sendRequest(req.request, projectId);
}

function ternFindRefs(view, projectId) {
	var req = buildRequest(view, "refs", false);
	return sendRequest(req.request, projectId);
}