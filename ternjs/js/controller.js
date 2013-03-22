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
		syncFiles(ternServers[project.id], project.files);
	}
}

function killServer(project) {
	var server = ternServers[project.id];
	if (server) {
		server.reset();
		delete ternServers[project.id];
	}
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
}

function getFile(file, callback) {
	log('Requesting file ' + file);
	var content = '';
	if (!/(underscore)\.js$/.test(file)) {
		content = sublimeReadFile(file);
	}
	return callback(null, content);
	// return callback(null, sublimeReadFile(file));


	// var text = sublimeReadFile(file), env = [];
	// var envSpec = /\/\/ environment=(\w+)\n/g, m;
	// while (m = envSpec.exec(text)) {
	// 	env.push(envData[m[1]]);
	// }

	// callback()

	// log()
	// return {
	// 	text: text, 
	// 	name: file, 
	// 	env: env, 
	// 	ast: acorn.parse(text)
	// };
}

function registerDoc(name) {
	if (!_.isString(name)) {
		name = sublimeGetFileNameFromView(name);
	}

	// check if current document already exists
	var hasDoc = !!_.find(ternDocs, function(d) {
		return d.name == name;
	});

	if (hasDoc) {
		log('Document ' + name + ' is already registered');
		return;
	}

	var data = {
		name: name, 
		changed: null
	};

	ternDocs.push(data);
	ternServer.addFile(name);
}

function unregisterDoc(name) {
	if (!_.isString(name)) {
		name = sublimeGetFileNameFromView(name);
	}

	ternServer.delFile(name);

	for (var i = 0; i < ternDocs.length && name != ternDocs[i].name; ++i) {}
	ternDocs.splice(i, 1);

	if (ternServer) {
		ternServer.reset();
	}
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
	
	// var curDoc = docFromView(view);
	// if (!curDoc) {
	// 	throw 'Unable to locate document for given view';
	// }

	// TODO handle incremental doc change
	// query.file = curDoc.name;
	// if (curDoc.changed) {
	// 	if (cm.lineCount() > 100 && allowFragments !== false &&
	// 			curDoc.changed.to - curDoc.changed.from < 100 &&
	// 			curDoc.changed.from <= startPos.line && curDoc.changed.to > endPos.line) {
	// 		files.push(getFragmentAround(cm, startPos, endPos));
	// 		query.file = "#0";
	// 		offset = files[0].offset;
	// 		if (query.start != null) query.start -= offset;
	// 		query.end -= offset;
	// 	} else {
	// 		files.push({type: "full",
	// 								name: curDoc.name,
	// 								text: cm.getValue()});
	// 		query.file = curDoc.name;
	// 		curDoc.changed = null;
	// 	}
	// } else {
	// 	query.file = curDoc.name;
	// }


	// for (var i = 0; i < docs.length; ++i) {
	// 	var doc = docs[i];
	// 	if (doc.changed && doc != curDoc) {
	// 		files.push({type: "full", name: doc.name, text: doc.doc.getValue()});
	// 		doc.changed = null;
	// 	}
	// }
	var fileName = sublimeGetFileNameFromView(view);
	query.file = fileName;
	if (view.is_dirty()) {
		files.push({
			name: fileName,
			type: 'full',
			text: sublimeViewContents(view)
		});
	}
	// files.push({
	// 	name: fileName,
	// 	type: 'full',
	// 	text: sublimeReadFile(fileName)
	// });

	return {
		request: {
			query: query, 
			files: files
		},
		offset: offset
	};
}

function ternHints(view, projectId, callback) {
	log('Get hints for ' + projectId);
	var req = buildRequest(view, "completions");
	// log(JSON.stringify(req));
	var res = null;
	var server = ternServers[projectId];
	if (!server) {
		log('No sutable server for project "' + projectId + '"');
		return null;
	}

	server.request(req.request, function(error, data) {
		log('Resp: ' + error);
		if (error) {
			throw error;
		}

		var completions = _.map(data.completions, function(completion) {
			return {
				text: completion.name,
				type: completion.type,
				guess: !!data.guess
			};
		});

		res = {
			from: data.from + req.offset,
			to: data.to + req.offset,
			list: completions
		};

		if (callback) {
			callback(res);
		}
	});

	return res;
}