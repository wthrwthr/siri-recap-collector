# Siri Recap Collector

[![Tests](https://github.com/wthrwthr/siri-recap-collector/actions/workflows/tests.yml/badge.svg)](https://github.com/wthrwthr/siri-recap-collector/actions/workflows/tests.yml)

Apple Watch Siri Recaps expire after seven days unless you save or export them. If you remember a decision two weeks later, the recap that recorded it may already be gone. Siri Recap Collector keeps a searchable copy of recaps that sync to your Mac. It preserves summaries, section headings and key points in SQLite, even after the original expires. [Apple's Siri Recap guide](https://support.apple.com/en-us/148354)

The included **Siri Recaps** agent skill lets you ask questions like *“What did the volunteer handoff recap say about Saturday setup?”* It searches the archive, opens the matching recap, and gives the assistant a title and date to cite.

## Try it in 30 seconds

Requires Git and Python 3.9 or later. The demo uses two fictional records in memory and works without an Apple Watch, access to Siri, or an AI account.

```sh
git clone https://github.com/wthrwthr/siri-recap-collector.git
cd siri-recap-collector
python3 -B examples/demo.py
```

```text
Search for 'Saturday setup' in two fictional recaps
2026-01-16 | Volunteer handoff | demo-2
Agreed to move Saturday setup to 9 AM. The welcome team will bring signs.
```

## Archive your own recaps

On a Mac where your Siri Recaps have synced, start with a read-only check. It runs twice in memory. On an unchanged source, the first count shows inserts and the second shows those records as unchanged.

```sh
python3 -B collector.py
```

Save the accessible recaps to the default archive used by the AI skill:

```sh
python3 -B collector.py --archive "$HOME/Library/Application Support/SiriRecapCollector/recaps.sqlite3"
```

**If macOS reports “Operation not permitted,”** review the launching app's access in System Settings → Privacy & Security. If you use **Choose Folders**, select the specific `AgentSessionKit` folder containing `AgentSessionStore.sqlite`. Pass `--source-folder "/path/to/AgentSessionKit"` to the collector and installer so they open that folder directly. [Apple's file-access guide](https://support.apple.com/guide/mac-help/mchld5a35146/mac)

## Ask an AI assistant

From the checkout, run:

```sh
python3 -B install_skill.py
python3 -B "$HOME/.agents/skills/siri-recaps/scripts/query.py" status
```

The installer places the skill in your local Codex user directory. Inside a checkout, Codex can also discover the repository-scoped copy. In a local session with access to the archive, try:

> Use $siri-recaps to find what we decided about the volunteer handoff last week. Cite the recap title and date, and flag anything that was only proposed.

The helper can report archive coverage, search a literal phrase, list recent recaps by local date, and open one capture ID. Search returns up to five IDs, dates and titles by default. The assistant requests a matching record when it needs the body. Other skill-compatible hosts can use the same [skill directory](.agents/skills/siri-recaps/SKILL.md).

```sh
python3 -B .agents/skills/siri-recaps/scripts/query.py search "handoff" --limit 3
```

The collector and search helper use Python's standard library and make no network requests. The archive is plaintext SQLite with owner-only permissions on newly created files. If you use a hosted model, the selected titles and passages can enter that model's context. Recaps are generated summaries; use the cited source when a detail or speaker attribution matters.

## Collect automatically

For hourly capture while a foreground process stays open, use `python3 -B collector.py --watch`. To run the per-user LaunchAgent while logged in:

```sh
python3 -B install.py
```

The installer saves a foreground archive and then checks two distinct background runs. **Two background runs verified** confirms the job was able to collect. Terminal and the background job have separate access contexts. If only foreground collection succeeds, its archive is still usable. Review `runs.log` and `errors.log` alongside the archive.

Inspect the job:

```sh
launchctl print "gui/$(id -u)/local.siri-recap-collector"
```

To stop it and keep the archive:

```sh
launchctl disable "gui/$(id -u)/local.siri-recap-collector"
launchctl bootout "gui/$(id -u)/local.siri-recap-collector"
```

Run the installer again to resume. Repeated collections update records by capture ID and preserve records that have disappeared from the source.

## Export and compatibility

For tools that accept JSON Lines, export one document per line to an unused filename:

```sh
(umask 077; set -C; /usr/bin/sqlite3 -readonly \
  "$HOME/Library/Application Support/SiriRecapCollector/recaps.sqlite3" \
  "SELECT document FROM recaps ORDER BY json_extract(document, '$.start_utc')" > siri-recaps.jsonl)
```

**Verified on macOS 27.3.** Mac records were checked against the iPhone Recaps screen for matching titles, summaries, headings and bullet points. On that build, the dedicated recap table was empty. The matching attachments used source `com.apple.MindPalace` and type `com.apple.mindpalace.capture`. This is an undocumented Apple format. Collection depends on what has synced to the Mac; an earlier recap that already expired may be unavailable.

Run `python3 -B -m unittest -v` for the synthetic tests. If another macOS build behaves differently, [open a compatibility issue](https://github.com/wthrwthr/siri-recap-collector/issues/new) with the build number, the command used, and counts or a redacted error. Please omit actual recap text, screenshots and device-specific paths.
