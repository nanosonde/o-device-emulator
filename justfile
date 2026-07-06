# Show the available development commands.
default:
    @just --list --unsorted

# Show command descriptions and common workflows.
help:
    @echo 'Controller development commands:'
    @echo '  just controller-start  # Start the Docker controller in the background'
    @echo '  just proxy-start       # Start the HTTP controller proxy in the background'
    @echo '  just proxy-stop        # Stop the HTTP controller proxy'
    @echo '  just emulator-start    # Start the device emulator in the background'
    @echo '  just emulator-stop     # Stop the device emulator'
    @echo '  just controller-stop   # Stop the Docker controller without deleting its data'
    @echo '  just run-all           # Start the controller, proxy, and emulator'
    @echo '  just stop-all          # Stop the emulator, proxy, and controller'
    @echo '  just decryptcfg FILE.cfg  # Decrypt and decompress to FILE.json'
    @echo '  just encryptcfg FILE.json # Compress and encrypt to FILE.cfg'
    @echo
    @just --list --unsorted

# Start the controller, HTTP proxy, and device emulator.
run-all: controller-start proxy-start emulator-start

# Stop the device emulator, HTTP proxy, and controller.
stop-all: emulator-stop proxy-stop controller-stop

# Start the controller container in the background.
controller-start:
    docker compose -f tools/docker-compose.yml up -d

# Stop the controller container while preserving its data volumes.
controller-stop:
    docker compose -f tools/docker-compose.yml stop

# Display the controller's Docker Compose log output.
controller-logs:
    docker compose -f tools/docker-compose.yml logs

# Follow the controller's Docker Compose log output until interrupted.
controller-logs-follow:
    docker compose -f tools/docker-compose.yml logs --follow

# Start the controller HTTP proxy in the background at http://127.0.0.1:8090.
proxy-start:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/controller-proxy.pid'
    log_file='data/controller-proxy.log'
    mkdir -p data
    if [[ -f "$pid_file" ]]; then
        pid="$(<"$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            echo "Proxy is already running (PID $pid): http://127.0.0.1:8090"
            exit 0
        fi
        rm -f "$pid_file"
    fi
    nohup python3 tools/controller_proxy.py 8090 >"$log_file" 2>&1 < /dev/null &
    pid=$!
    echo "$pid" > "$pid_file"
    echo "Proxy started (PID $pid): http://127.0.0.1:8090"
    echo "Log: $log_file"

# Stop the background controller HTTP proxy.
proxy-stop:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/controller-proxy.pid'
    if [[ ! -f "$pid_file" ]]; then
        echo 'Proxy is not running.'
        exit 0
    fi
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "Proxy stopped (PID $pid)."
    else
        echo "Removed stale proxy PID file (PID $pid)."
    fi
    rm -f "$pid_file"

# Display the controller HTTP proxy log output.
proxy-logs:
    cat data/controller-proxy.log

# Follow the controller HTTP proxy log output until interrupted.
proxy-logs-follow:
    tail --follow data/controller-proxy.log

# Display the saved proxy PID and recent log output.
proxy-status:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/controller-proxy.pid'
    log_file='data/controller-proxy.log'
    if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
        echo "Proxy is running (PID $(<"$pid_file")): http://127.0.0.1:8090"
    else
        echo 'Proxy is not running.'
    fi
    if [[ -f "$log_file" ]]; then
        echo
        echo "Recent log output ($log_file):"
        tail -n 20 "$log_file"
    fi

# Start the device emulator daemon in the background with config.yaml.
emulator-start:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/device-emulator.pid'
    log_file='data/device-emulator.log'
    config_file='config.yaml'
    python='.venv/bin/python'
    if [[ ! -f "$config_file" ]]; then
        echo "Missing $config_file; copy config.example.yaml and configure it first." >&2
        exit 1
    fi
    if [[ ! -x "$python" ]]; then
        echo "Missing $python; create the virtual environment first." >&2
        exit 1
    fi
    mkdir -p data
    if [[ -f "$pid_file" ]]; then
        pid="$(<"$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            echo "Emulator is already running (PID $pid)."
            exit 0
        fi
        rm -f "$pid_file"
    fi
    nohup "$python" device_emulator_daemon.py --config "$config_file" >"$log_file" 2>&1 < /dev/null &
    pid=$!
    echo "$pid" > "$pid_file"
    echo "Emulator started (PID $pid)."
    echo "Log: $log_file"

# Stop the background device emulator daemon.
emulator-stop:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/device-emulator.pid'
    if [[ ! -f "$pid_file" ]]; then
        echo 'Emulator is not running.'
        exit 0
    fi
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "Emulator stopped (PID $pid)."
    else
        echo "Removed stale emulator PID file (PID $pid)."
    fi
    rm -f "$pid_file"

# Display the emulator daemon log output.
emulator-logs:
    cat data/device-emulator.log

# Follow the emulator daemon log output until interrupted.
emulator-logs-follow:
    tail --follow data/device-emulator.log

# Display the saved emulator PID and recent log output.
emulator-status:
    #!/usr/bin/env bash
    set -euo pipefail
    pid_file='data/device-emulator.pid'
    log_file='data/device-emulator.log'
    if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
        echo "Emulator is running (PID $(<"$pid_file"))."
    else
        echo 'Emulator is not running.'
    fi
    if [[ -f "$log_file" ]]; then
        echo
        echo "Recent log output ($log_file):"
        tail -n 20 "$log_file"
    fi

# Decrypt and decompress a controller .cfg backup to a plain .json file.
decryptcfg cfg:
    #!/usr/bin/env bash
    set -euo pipefail
    input={{quote(cfg)}}
    if [[ "$input" != *.cfg ]]; then
        echo "Expected a .cfg input file: $input" >&2
        exit 2
    fi
    output="${input%.cfg}.json"
    .venv/bin/python tools/decrypt_backup.py "$input" --output "$output"

# Compress and encrypt a plain .json file as a controller .cfg backup.
encryptcfg json:
    #!/usr/bin/env bash
    set -euo pipefail
    input={{quote(json)}}
    if [[ "$input" != *.json ]]; then
        echo "Expected a .json input file: $input" >&2
        exit 2
    fi
    output="${input%.json}.cfg"
    .venv/bin/python tools/encrypt_backup.py "$input" --output "$output"