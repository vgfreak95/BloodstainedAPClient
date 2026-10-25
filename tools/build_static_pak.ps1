# Arguments come from build_config.toml; any passed here override it.
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\build_static_pak.py" @args
