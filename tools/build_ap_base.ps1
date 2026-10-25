# Arguments come from build_config.toml; any passed here override it.
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\build_ap_base.py" @args
