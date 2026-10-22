# SENTRA Electron display — provenance

Design and security review references: Chat On Steroids 2.1.31,
https://github.com/totec448-spec/chat-on-steroids, commit 151e7ef,
MIT license. This implementation does **not** bundle or execute the upstream
Electron application or its privileged main process. It renders SENTRA's own
Canvas with no Electron IPC tool/OS authority; Electron is a display only.
The original upstream tree and LICENSE remain in third_party/chat-on-steroids.
Electron itself and transitive dependencies retain their own notices/licenses.

## Coucou island

Original island styles, geometry, animation, state machine, icons and ticker
from https://github.com/Louis-CFM/coucou at commit
`1e5180921c1326fc72e41d313e3e2855e9c10162`.
Only SENTRA characters and protected display projections are used by the adapter.
No Mochi assets, fonts or recorded sounds are included.

MIT License

Copyright (c) 2026 Louis Raillé

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
