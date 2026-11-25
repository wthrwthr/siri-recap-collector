# Siri Recap Collector

Archive the Siri Recaps that have synced to your Mac, including expiring recaps that you haven't bookmarked. The collector reads the local Siri database and saves the title, summary, section headings, key points, start time, duration, and capture ID to SQLite. Everything runs locally with Python's standard library.

On a Mac running macOS 27.3, titles, summaries, headings, and bullets were compared with the iPhone Recaps screen. The dedicated recap table was empty. The matching records were session attachments with the source `com.apple.MindPalace` and content type `com.apple.mindpalace.capture`. This is an undocumented Apple storage format and may change. The collector can only archive content present on the Mac when it runs.

## Check your Mac

You'll need Python 3.9 or later and an account with Siri Recaps synced to this Mac. From the repository directory, run:

```sh
python3 -B collector.py
```

If you used **Choose Folders** in macOS Privacy & Security, select the specific `AgentSessionKit` directory for the app running the collector. Pass `--source-folder "/path/to/AgentSessionKit"` to every collect or install command. This opens the database in that folder without listing other containers. The parent directory and launching context can have different permissions.

This reads the live SQLite store with `mode=ro`, collects into memory twice, and prints counts. For an unchanged, nonempty source, the first line shows `inserted` and the second shows `unchanged`. No archive is created by this check.

**If macOS reports “Operation not permitted” for `~/Library/Daemon Containers`, stop here.** The process launching Python lacks access to the source directory. Check the launching app's access in System Settings → Privacy & Security. Terminal and a background LaunchAgent can receive different decisions. Full Disk Access is a broad permission. The installer does not change privacy settings. [Apple's guide to file access](https://support.apple.com/guide/mac-help/mchld5a35146/mac)

## Save recaps

```sh
python3 -B collector.py --archive "$HOME/Library/Application Support/SiriRecapCollector/recaps.sqlite3"
```

Repeated runs update records by capture ID. Recaps that disappear from the source remain in the archive. The database is plaintext and new archive files are created with owner-only permissions. Run `python3 -B collector.py --watch` to collect immediately and then hourly while that foreground process stays open.

## Install hourly collection

```sh
python3 -B install.py
```

The installer first tests foreground access and saves a local copy. It then verifies two runs from a per-user LaunchAgent. Only the final **Two background runs verified** message confirms successful background setup. If background access fails, the foreground archive is still available. A newly loaded job that fails verification is disabled and unloaded. An existing job is left available for diagnosis.

The job runs at login and hourly while logged in. The archive and count-only run log live in `~/Library/Application Support/SiriRecapCollector/`. Failures go to `errors.log`. Check the job, or stop it while keeping the archive:

```sh
launchctl print "gui/$(id -u)/local.siri-recap-collector"
# To stop collection and disable it at future logins:
launchctl disable "gui/$(id -u)/local.siri-recap-collector"
launchctl bootout "gui/$(id -u)/local.siri-recap-collector"
```

Run the installer again to resume collection. If it reports a changed existing file, review that file before replacing it.

## Export for a local model

This creates a new JSON Lines file in the current folder. Each line is one recap. Choose an unused filename to protect any previous export.

```sh
(umask 077; set -C; /usr/bin/sqlite3 -readonly \
  "$HOME/Library/Application Support/SiriRecapCollector/recaps.sqlite3" \
  "SELECT document FROM recaps ORDER BY json_extract(document, '$.start_utc')" > siri-recaps.jsonl)
```

## Tests

```sh
python3 -B -m unittest -v
```

The tests use synthetic SQLite databases in memory. They cover source filtering, malformed attachments, repeat runs, changed and expired records, and revision ordering.
