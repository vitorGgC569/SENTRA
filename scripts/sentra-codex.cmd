@echo off
rem Launches Codex CLI through the SENTRA HTTP/SSE profile.
rem This avoids Codex's built-in WebSocket transport, which the SENTRA Gateway does not expose.
codex -p sentra %*
