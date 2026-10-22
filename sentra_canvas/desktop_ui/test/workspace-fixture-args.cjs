'use strict';

// Electron on Windows can reject a bare URL in its native command line before
// loading the application. Keep fixture data in named options instead.
function parseWorkspaceFixtureArgs(argv) {
  const value = name => {
    const prefix = '--' + name + '=';
    const matches = argv.filter(argument => argument.startsWith(prefix));
    if (matches.length !== 1 || matches[0].length === prefix.length)
      throw Error('Exactly one nonempty --' + name + '= value is required');
    return matches[0].slice(prefix.length);
  };
  return { target: value('fixture-target'), output: value('fixture-output') };
}

module.exports = { parseWorkspaceFixtureArgs };
