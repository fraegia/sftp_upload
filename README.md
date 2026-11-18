# sftp_push

Copies the files exported by **SessionAdapter** from one or more local Windows folders to the **CentralSite** server over SFTP (OpenSSH), where they are read by the central application. Every file is copied once, and the script can run unattended from Windows Task Scheduler.

**Main points**

- **Several jobs in one run.** Each job is a pair *local folder -> remote folder*, with its own file-name filter. Jobs are independent and share one server connection.
- **No duplicates.** Copied files are recorded in `state.txt` and are not sent again, unless their content changes or you reset the state.
- **Safe copy.** A file is uploaded as `name.part`, verified, then renamed to `name`: CentralSite never sees a half-written file.
- **Keep or delete.** Local files are kept by default; they can be deleted after a verified copy.
- **One config file** (`config.ini`), one dependency (`paramiko`).

## Quick start

1. Install Python 3.9+ and make `python` work from any folder (section 3).
2. Install the module: `python -m pip install paramiko`.
3. Create an SSH key and ask the CentralSite administrator to install the public key (section 4).
4. Edit `config.ini`: server, options, one `[job ...]` section per folder pair (section 5).
5. Test by hand with `run.bat` (section 6).
6. Create the scheduled task with `install_task.bat` (section 7).

## 1. Files in this folder

| File | Created by | What it is for | Can I delete it? |
| --- | --- | --- | --- |
| `sftp_push.py` | delivered | The transfer script. | No |
| `config.ini` | delivered | All settings: server, general options, jobs. The only file you normally edit. | No |
| `run.bat` | delivered | Starts the script in a visible console window. Use it for manual tests and to see error messages. | Only if you never test by hand |
| `install_task.bat` | delivered | Launcher of `install_task.ps1`: double-click it to create the scheduled task, or run `install_task.bat remove` to delete it. | After the task is created |
| `install_task.ps1` | delivered | Creates the scheduled task that starts `pythonw.exe sftp_push.py` at logon, with no window. Set the path of `pythonw.exe` and the user at the top of the file. | After the task is created |
| `README.md` | delivered | This guide. | Yes |
| `state.txt` | script | List of the files already copied (local path, remote folder, size, date). | Yes: all files are sent again |
| `log` folder | script | Contains `sftp_push.log` (today's log) and the rotated files of previous days (`sftp_push.log.2026-11-16`...). The log is rotated at midnight without restarting the script. Days kept: `log_keep_days`. | Yes, when the script is not running |
| `known_hosts` | script | Identity of the CentralSite server, saved at the first connection (section 9). | Yes: it is learned again |
| `run_hidden.vbs` | old version | Not used any more. | Yes |

`state.txt`, the `log` folder and `known_hosts` are created next to `config.ini` the first time the script runs.

## 2. How it works

1. SessionAdapter writes files into a local folder, for example `C:\SessionAdapter\SessionAdapter\output\csv`.
2. At each check, the script goes through the jobs in the order they appear in `config.ini`. For each job it selects the files that match `pattern` and are new or changed since the last copy.
3. If at least one file has to be sent, it uses the SFTP connection to CentralSite, creates the missing remote folders and uploads the files. The connection is opened once and **kept open** between checks. It is reopened only when it has dropped. A keepalive packet is sent every 30 seconds while the connection is idle, so firewalls and the server do not close it. The keepalive is independent of `interval_seconds`.
4. Each file is uploaded as `name.part`, its size is verified, then it is renamed to `name`. **The CentralSite application must ignore `*.part` files.**
5. Each file copied successfully is recorded in `state.txt`. If `delete_after_copy = yes`, the local file is then deleted. Lines of files that no longer exist locally, or that are older than `ignore_older_than_days`, are removed from `state.txt`. The file is rewritten only when a file is copied or a line is removed, not at every check.
6. Files modified less than `min_age_seconds` ago are skipped (SessionAdapter may still be writing them) and are taken at the next check.
7. If `interval_seconds` is above 0, the script waits and repeats the check forever. Otherwise it exits.

If a local folder cannot be read, that job is skipped with a warning and the other jobs continue. If one file fails, the other files are still sent and the failed file is retried at the next check. If the connection fails, the whole check is repeated at the next interval.

Only files directly inside a local folder are copied; subfolders are ignored.

## 3. Python on Windows

Python 3.9 or newer. Check in a Command Prompt: `python --version`.

If the command is not found and Python is in `C:\PythonXX\`:

1. Win+R, `sysdm.cpl`, **Advanced**, **Environment Variables**.
2. Select **Path** (User or System), **Edit**, **New**, and add `C:\PythonXX\` and `C:\PythonXX\Scripts\`.
3. Move both lines above any line containing `WindowsApps`, click OK, and open a **new** Command Prompt.

If `python` opens the Microsoft Store, switch off the two *python.exe* entries in Settings, Apps, Advanced app settings, **App execution aliases**.

`run.bat` starts the script with `py -3`. If `py` does not exist on this PC (Python copied without the installer), edit `run.bat` and use `python` or the full path `"C:\PythonXX\python.exe"`. `py -0p` lists the Python installations found.

**Dependency.** In an administrator Command Prompt, using the same Python:

```
python -m pip install paramiko
python -c "import paramiko; print(paramiko.__version__)"
```

Without Internet access: on another PC with the same Python version run `python -m pip download paramiko -d wheels`, copy the `wheels` folder here, then run `python -m pip install --no-index --find-links=wheels paramiko`.

## 4. Access to CentralSite

Ask the administrator for: host, port, a dedicated user, and write permission on the destination folders.

1. Create a key with **no passphrase** (the script cannot type one):
   `ssh-keygen -t ed25519 -f C:\Users\user\.ssh\id_ed25519`
2. Give the `.pub` file to the administrator, who appends it to `~/.ssh/authorized_keys` of that user. Keep the private key on this PC only.
3. Test the connection by hand: `sftp -i C:\Users\user\.ssh\id_ed25519 user@host`. If this fails, the script will fail too.

A password can be used instead of a key (`password` in `config.ini`), but then anyone who can read the file can read the password.

## 5. Configuration (`config.ini`)

Plain text file with three kinds of sections: `[server]` (one), `[general]` (one), `[job ...]` (as many as you need).

Rules:

- Windows paths are written as they are: `C:\SessionAdapter\SessionAdapter\output\csv`. No quotes, no doubled backslashes. Spaces are fine. Network paths (`\\server\share\folder`) work too.
- Remote paths are for the OpenSSH server and use `/`: `/data/inbox/sessions`.
- Comments start with `;` or `#` and must be on their own line. A comment after a value becomes part of the value.
- A relative path in `state_file`, `log_file`, `known_hosts` or `key_file` is relative to the folder of `config.ini`.

### [server]

One server for all jobs.

| Option | Default | Meaning |
| --- | --- | --- |
| `host` | required | Name or IP address of CentralSite. |
| `port` | 22 | SSH port. Change only if SSH was moved. |
| `user` | required | Account on the server, for example `transfer`. |
| `key_file` | empty | Full path of the private key. Recommended. |
| `password` | empty | Only if keys are not allowed. Leave `key_file` empty. |

### [general]

| Option | Default | Meaning and when to use it |
| --- | --- | --- |
| `delete_after_copy` | `no` | `no`: local files stay. `yes`: each local file is deleted after its upload is verified. **It applies to all jobs.** Keep `no` while testing; use `yes` when the SessionAdapter folder must not grow. |
| `min_age_seconds` | 5 | Skip files modified more recently than this. Use a value longer than the longest pause SessionAdapter makes while writing one file: 30-60 for large or slow files. Do not use 0 in production. |
| `ignore_older_than_days` | 0 | Only files whose modification date is within the last N days are copied. Older files are ignored and removed from `state.txt`. `0` = no window. A file older than the window is never sent, so choose a value longer than any period CentralSite may be unavailable. |
| `interval_seconds` | 0 | `0`: check once and exit (Task Scheduler must repeat `run.bat` every few minutes). Above `0`: keep running and check every N seconds. **With a task started once at logon (section 7) it must be above 0.** The number is the check period, not a restart. |
| `state_file` | `state.txt` | Files already copied (section 8). |
| `log_file` | `log\sftp_push.log` | Current log file. The `log` folder is created if missing. Usually left as it is. |
| `log_keep_days` | 3 | Number of rotated daily logs to keep. Older ones are deleted automatically. |
| `known_hosts` | `known_hosts` | Server identity (section 9). |

### [job name] - one section per folder pair

The section name must start with `job`; the rest is free (`[job sessions]`, `[job reports]`...). Every job has its own source, destination and filter, and jobs do not affect each other.

| Option | Default | Meaning |
| --- | --- | --- |
| `local` | required | Windows folder to watch. |
| `remote` | required | Destination folder on CentralSite. Missing folders are created, if the server user can write in the parent. |
| `pattern` | `*` | File names to copy: one or more patterns separated by commas, not case sensitive. Examples: `*.csv`, `*.csv, *.xml`, `session_*.csv`. Other files are ignored and never deleted. |

**Example with three jobs**

```ini
[server]
host = centralsite.mycompany.com
port = 22
user = transfer
key_file = C:\Users\user\.ssh\id_ed25519
password =

[general]
delete_after_copy = no
min_age_seconds = 10
ignore_older_than_days = 30
log_keep_days = 3
interval_seconds = 30

; Session files exported by SessionAdapter
[job sessions]
local = C:\SessionAdapter\SessionAdapter\output\csv
remote = /data/centralsite/inbox/sessions
pattern = *.csv

; PDF reports from another folder, to another destination
[job reports]
local = C:\SessionAdapter\SessionAdapter\output\reports
remote = /data/centralsite/inbox/reports
pattern = *.pdf

; Everything else from a third folder
[job misc]
local = D:\Exports\Other
remote = /data/centralsite/inbox/misc
```

Notes on jobs:

- The same local folder can feed two jobs (for example with different patterns, or to two different destinations): copies are tracked per local file **and** remote folder.
- If you change the `remote` of a job, all its files are sent again to the new folder.
- `delete_after_copy`, `min_age_seconds` and the server are the same for every job. If you need different values, use a second copy of the script folder with its own `config.ini` (and its own task).

## 6. First manual test

```
cd /d X:\Script
run.bat
```

One line per copied file is printed, for example `[job sessions] copied C:\...\session1.csv -> /data/.../session1.csv`. Check the files on CentralSite. With `interval_seconds` above 0 the script keeps running: stop it with Ctrl+C.

The first connection saves the server identity in `known_hosts`.

On the first run **everything** already in the local folders is sent: move old files you do not want to send elsewhere first.

## 7. Scheduled task: one task, started at logon, no window

The task starts **once**, 30 seconds after the logon of the `user` account, runs as `user` (no password, no administrator rights) and runs `pythonw.exe sftp_push.py`, so no console window appears. The script then keeps running by itself (`interval_seconds` above 0).

### Automatic

1. Open `install_task.ps1` with Notepad and set `$Pythonw` to the real path of `pythonw.exe` (for example `C:\Python312\pythonw.exe`). Check `$TaskUser` and `$DelaySeconds`.
2. Check that `interval_seconds` in `config.ini` is above 0.
3. Run `install_task.bat`: double-click if you are logged on as `user`, otherwise from a Command Prompt opened as Administrator. Running it again updates the task.
4. To remove the task: `install_task.bat remove`.

The task has no 72-hour limit, never starts a second instance of itself, and is restarted up to 3 times (1 minute apart) if the process stops.

### Manual (`taskschd.msc`, Create Task)

| Tab | Setting |
| --- | --- |
| General | Name `SessionAdapter to CentralSite`; **Run only when user is logged on**. |
| Triggers | New: **At log on**, **Specific user** `user`, **Delay task for** 30 seconds. |
| Actions | Start a program: `C:\PythonXX\pythonw.exe`; Add arguments `X:\Script\sftp_push.py`; Start in `X:\Script`. |
| Settings | Untick **Stop the task if it runs longer than 3 days**; if the task is already running: **Do not start a new instance**. |

## 8. Check, stop, re-send

**Is it running?**

- `taskschd.msc`: the task shows **Running**. Or: `schtasks /Query /TN "SessionAdapter to CentralSite" /V /FO LIST` (`Status: Running`).
- Task Manager, **Details** tab: one `pythonw.exe` running `sftp_push.py`.
- Practical test: copy a file into a watched folder; after `interval_seconds` + `min_age_seconds` it must be on CentralSite and in the log. The log is silent when there is nothing to copy.

**Stop it:** right-click the task, **End**; or end `pythonw.exe` in Task Manager.

**What the log tells you** (`log\sftp_push.log`):

- `=== Started (pid ..., check every N s)`: the script started. Each start is logged, including after a restart.
- `=== Stopped`: the script ended normally, for example after a run-once run or a clean exit.
- `Connection to host:port failed: ... Retrying at each check.`: CentralSite is unreachable (network down, server off, wrong port, firewall, wrong key file). It is logged **once** when the server goes down, not at every attempt, so the log does not fill up. The script keeps retrying at each check, only while there are files to send.
- `Connection to host restored.`: the server is reachable again, and the copies resume.
- `Cycle failed: ...`: an error during a check, for example a connection lost while uploading. The next check reconnects and retries.

**Retries:** with `interval_seconds` above 0 the script retries forever, with no limit on attempts. With `interval_seconds = 0` it makes one attempt and exits with code 1. Files that cannot be sent stay in the local folder and are sent when the server comes back, provided they are within `ignore_older_than_days`.

**Limit:** if the task is **ended** from Task Scheduler or Task Manager, Windows stops the process without giving it time to log: no `=== Stopped` line appears. A `Started` line with no matching `Stopped` after a manual end is normal.

**`0x1` in Last Run Result** means the script exited with an error. Run `run.bat` by hand and read the message (section 10).

**Never run two instances at the same time** (for example `run.bat` while the task is running, or two tasks): they would upload the same files and overwrite each other's `state.txt`.

**Re-sending files.** `state.txt` has one line per copied file. A file is skipped when its local path, remote folder, size and modification date are unchanged.

- All files: stop the task, delete `state.txt`, start the task.
- Some files: stop the task, delete their lines in `state.txt` with Notepad, start the task. Saving a file again also changes its date, so it is sent again.
- A file with the same name but new content is sent again and replaces the old one on the server.
- Lines of files that no longer exist locally, or are older than `ignore_older_than_days`, are removed automatically. You do not need to empty `state.txt` by hand.
- Do not edit `state.txt` while the script is running.

## 9. `known_hosts`

Contains the identity (public key) of the CentralSite server, saved at the first connection, to prevent connecting to a fake server. If the identity later changes, the script refuses to connect (`Host key ... does not match`). If the server was reinstalled on purpose, delete `known_hosts`; otherwise ask the administrator. It contains no passwords or private keys.

## 10. Troubleshooting

Read `log\sftp_push.log` first (older days are in the same folder). With `pythonw.exe` no console is shown, so startup errors are visible only if you run `run.bat` by hand.

| Message or symptom | Cause and solution |
| --- | --- |
| `No module named 'paramiko'` | Installed in a different Python than the one that runs the script (section 3). |
| `'py' is not recognized` | Use `python` or the full path in `run.bat`. |
| `Config file not found` | `config.ini` is not in the same folder as `sftp_push.py`. |
| `KeyError: 'host'` (or `'user'`, `'local'`, `'remote'`) | A required option is missing or misspelled. |
| `No [job ...] section in config` | No section name starts with `job`. |
| `getaddrinfo failed` | Wrong host name. |
| `timed out` | Wrong port, server off, or firewall. |
| `Authentication failed` | Wrong user or password, or public key not installed on the server. |
| `not a valid ... private key` / `encrypted` | `key_file` points to the wrong file (for example the `.pub`) or the key has a passphrase. |
| `Host key ... does not match` | Server identity changed (section 9). |
| `Permission denied` / `FAILED` | The server user cannot write in the remote folder. The file is retried. |
| `cannot read <folder>` | Wrong `local` path, or no access for the user that runs the script. |
| `copied but not deleted` | Windows refused to delete the local file (in use). It will not be sent again; delete it by hand. |
| Nothing is copied, no error | Already in `state.txt`, modified less than `min_age_seconds` ago, not matching `pattern`, or inside a subfolder. |
| `.part` files on the server | An upload was interrupted; the next check completes it. CentralSite must ignore `.part` files. |
| Task shows `0x1` | See section 8. |
