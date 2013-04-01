# TernJS for Sublime Text

[TernJS](http://ternjs.net) is a JavaScript type inference engine written by [Marijn Haverbeke](http://marijnhaverbeke.nl). It analyses your JS code on-the-fly and provides autocompletion, function argument hints, jump-to-definition, and various automatic refactoring operations.

This plugin adds TernJS support into Sublime Text editor.

## How to install

Sublime Tern can be installed as any other plugin with [Package Control](http://wbond.net/sublime_packages/package_control):

1. In ST editor, call “Install Package” command from Command Palette.
2. Find “TernJS” in plugins list and hit Enter to install it.

When installed, Sublime Tern will automatically download PyV8 binary required to run this plugin. If you experience issues with PyV8 loader, you can [install it manually](https://github.com/emmetio/pyv8-binaries#readme).

*Warning*: if you have [Emmet](http://emmet.io/) plugin installed and using Sublime Text 2, you have to make sure you have the latest PyV8 binary. It must be automatically updated within 24 hours (you need to restart ST2 editor), but you can forcibly update it:

1. Quit ST2 editor
2. Completely remove `PyV8` package (remove this folder from ST2’s `Packages` folder)
3. Start ST2 editor. Latest PyV8 should be downloaded and installed automatically.

With old PyV8 binary, you’ll experience a lot of crashes.

## How to use

Read special [blog post](http://emmet.io/blog/sublime-tern/) about how to use and configure TernJS.