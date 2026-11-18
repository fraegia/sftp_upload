"""sftp_push - copy new files from local folders to a remote server via SFTP.

Usage:  python sftp_push.py [config.ini]
"""
import configparser
import fnmatch
import logging
import os
import posixpath
import sys
import time
from logging.handlers import TimedRotatingFileHandler

import paramiko

log = logging.getLogger("sftp_push")


# ---------------------------------------------------------------- state file
# One line per copied file: local_path <TAB> remote_dir <TAB> size <TAB> mtime_ns
# Delete the file (or single lines) to copy files again.

def load_state(path):
    state = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 4:
                    state[(parts[0], parts[1])] = (parts[2], parts[3])
    return state


def append_state(path, key, fp):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{key[0]}\t{key[1]}\t{fp[0]}\t{fp[1]}\n")


def compact_state(path, state, cutoff_ns=None, force=False):
    """Drop entries of files that no longer exist locally or are older than the cutoff.
    Files older than the cutoff are never copied again (see pending_files), so their
    entries are not needed. Rewrites the file only if something was removed or force is set."""
    stale = [k for k in state
             if not os.path.exists(k[0])
             or (cutoff_ns is not None and int(state[k][1]) < cutoff_ns)]
    for key in stale:
        del state[key]
    if not (stale or force):
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for (local, remote), (size, mtime) in state.items():
            f.write(f"{local}\t{remote}\t{size}\t{mtime}\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- local scan

def pending_files(job, state, min_age, cutoff):
    """Return files of a job that are new or changed since the last copy.
    Files modified before `cutoff` (epoch seconds, or None) are ignored."""
    try:
        entries = list(os.scandir(job["local"]))
    except OSError as e:
        log.warning("[%s] cannot read %s: %s", job["name"], job["local"], e)
        return []
    now = time.time()
    out = []
    for e in entries:
        if not e.is_file():
            continue
        if not any(fnmatch.fnmatch(e.name.lower(), p) for p in job["patterns"]):
            continue
        st = e.stat()
        if now - st.st_mtime < min_age:          # still being written
            continue
        if cutoff is not None and st.st_mtime < cutoff:   # too old: outside the window
            continue
        fp = (str(st.st_size), str(st.st_mtime_ns))
        if state.get((e.path, job["remote"])) == fp:
            continue
        out.append((e.path, e.name, fp))
    return sorted(out, key=lambda x: x[0])


# ---------------------------------------------------------------- remote side

def connect(srv, known_hosts, base):
    client = paramiko.SSHClient()
    if not os.path.exists(known_hosts):
        open(known_hosts, "a").close()
    client.load_host_keys(known_hosts)            # changed host key -> error
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # first connect only
    key_file = srv.get("key_file", "").strip()
    client.connect(
        srv["host"],
        port=srv.getint("port", 22),
        username=srv["user"],
        password=srv.get("password", "").strip() or None,
        key_filename=os.path.join(base, key_file) if key_file else None,
        timeout=30,
    )
    client.save_host_keys(known_hosts)
    return client, client.open_sftp()


def ensure_remote_dir(sftp, path, done):
    if path in done:
        return
    cur = "/" if path.startswith("/") else ""
    for part in [p for p in path.split("/") if p]:
        cur = posixpath.join(cur, part) if cur else part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)
    done.add(path)


def upload(sftp, local, remote_dir, name):
    """Upload to <name>.part, verify size, then rename: the remote app never sees partial files."""
    final = posixpath.join(remote_dir, name)
    tmp = final + ".part"
    sftp.put(local, tmp, confirm=True)
    try:
        sftp.posix_rename(tmp, final)             # atomic overwrite (OpenSSH)
    except IOError:
        try:
            sftp.remove(final)
        except IOError:
            pass
        sftp.rename(tmp, final)


# ---------------------------------------------------------------- main

_server = {"up": True}   # remembers if the last connection attempt failed
_conn = {"client": None, "sftp": None}   # one connection kept open between checks


def get_connection(srv, known_hosts, base):
    """Return the open connection, reconnecting only if it is missing or has dropped."""
    client = _conn["client"]
    if client is not None and client.get_transport() is not None and client.get_transport().is_active():
        return client, _conn["sftp"]
    if client is not None:
        client.close()
    client, sftp = connect(srv, known_hosts, base)
    client.get_transport().set_keepalive(30)   # keeps the connection alive through idle periods
    _conn["client"], _conn["sftp"] = client, sftp
    return client, sftp


def run_cycle(cfg, jobs, opts, state, base):
    # Computed at every cycle, so a long-running script keeps a moving window.
    days = opts["ignore_days"]
    cutoff = time.time() - days * 86400 if days > 0 else None
    cutoff_ns = int(cutoff * 1e9) if cutoff is not None else None

    work = [(job, pending_files(job, state, opts["min_age"], cutoff)) for job in jobs]
    work = [(job, files) for job, files in work if files]
    if not work:
        compact_state(opts["state_file"], state, cutoff_ns)
        return 0

    srv = cfg["server"]
    try:
        client, sftp = get_connection(srv, opts["known_hosts"], base)
    except (OSError, EOFError, paramiko.SSHException) as e:
        # One line when the server goes down, not one per attempt.
        if _server["up"]:
            log.error("Connection to %s:%s failed: %s. Retrying at each check.",
                      srv["host"], srv.get("port", "22"), e)
            _server["up"] = False
        return 1
    if not _server["up"]:
        log.info("Connection to %s restored.", srv["host"])
        _server["up"] = True

    errors = 0
    copied = 0
    dirs = set()
    for job, files in work:
        ensure_remote_dir(sftp, job["remote"], dirs)
        for local, name, fp in files:
            try:
                upload(sftp, local, job["remote"], name)
            except Exception as e:
                errors += 1
                log.error("[%s] FAILED %s: %s", job["name"], local, e)
                if not client.get_transport().is_active():
                    raise
                continue
            key = (local, job["remote"])
            state[key] = fp
            append_state(opts["state_file"], key, fp)
            copied += 1
            log.info("[%s] copied %s -> %s/%s", job["name"], local, job["remote"], name)
            if opts["delete"]:
                try:
                    os.remove(local)
                except OSError as e:
                    log.warning("[%s] copied but not deleted %s: %s", job["name"], local, e)
    compact_state(opts["state_file"], state, cutoff_ns, force=copied > 0)
    return errors

def main():
    ini = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"))
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(ini, encoding="utf-8"):
        sys.exit(f"Config file not found: {ini}")
    base = os.path.dirname(ini)

    def path(value):
        return value if os.path.isabs(value) else os.path.join(base, value)

    g = cfg["general"]
    opts = {
        "delete": g.getboolean("delete_after_copy", False),
        "min_age": g.getint("min_age_seconds", 5),
        "ignore_days": g.getint("ignore_older_than_days", 0),   # 0 = no window
        "interval": g.getint("interval_seconds", 0),
        "state_file": path(g.get("state_file", "state.txt")),
        "known_hosts": path(g.get("known_hosts", "known_hosts")),
    }

    log_path = path(g.get("log_file", os.path.join("log", "sftp_push.log")))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    # Rotates at local midnight without restarting; keeps log_keep_days old files.
    file_handler = TimedRotatingFileHandler(log_path, when="midnight",
                                            backupCount=g.getint("log_keep_days", 3),
                                            encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    logging.getLogger("paramiko").setLevel(logging.WARNING)

    jobs = []
    for sec in cfg.sections():
        if sec.lower().startswith("job"):
            s = cfg[sec]
            jobs.append({
                "name": sec,
                "local": s["local"],
                "remote": s["remote"].rstrip("/") or "/",
                "patterns": [p.strip().lower() for p in s.get("pattern", "*").split(",") if p.strip()],
            })
    if not jobs:
        sys.exit("No [job ...] section in config")

    state = load_state(opts["state_file"])
    mode = f"check every {opts['interval']} s" if opts["interval"] > 0 else "run once"
    log.info("=== Started (pid %s, config %s, %s)", os.getpid(), ini, mode)
    try:
        while True:
            try:
                errors = run_cycle(cfg, jobs, opts, state, base)
            except Exception as e:
                log.error("Cycle failed: %s", e)
                errors = 1
            if opts["interval"] <= 0:
                sys.exit(1 if errors else 0)
            time.sleep(opts["interval"])
    finally:
        if _conn["client"] is not None:
            _conn["client"].close()
        log.info("=== Stopped")


if __name__ == "__main__":
    main()
