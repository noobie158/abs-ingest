# Getting books from the Windows PC to the server's `inbox/`

This part is not automated by abs-ingest itself; the tool only watches `inbox/`.
These are the setups that fit it. None of them was tested in the build environment
(it has no Windows PC or Syncthing), so check the first transfer by hand.

## Option A - Syncthing (recommended: fully automatic)

1. Install Syncthing on the PC and on the server; pair the devices.
2. PC folder (e.g. `D:\Audiobooks-Out`): folder type **Send Only**.
3. Server folder: `/srv/audiobooks/inbox`, folder type **Receive Only**.
4. abs-ingest moves each finished book out of `inbox/`. On a Receive Only folder
   those removals are shown as "local changes" and are **not** sent back to the PC,
   so your originals stay put.
   - Do **not** press "Revert Local Changes" on the server; that would download
     the books again and they would be ingested twice.
   - Clean old books out of the PC folder yourself when you are happy.
5. Syncthing's temporary files (`.syncthing.*.tmp`) are ignored by the watcher, and a
   book is only picked up after it has stopped changing for `stable_seconds`.

## Option B - drop folder over SFTP / SMB

Copy books into `/srv/audiobooks/inbox` with WinSCP, an SMB share, or `scp`.
Works as is; the watcher waits for the copy to finish.
Make sure uploaded files end up readable by the ingest user (default ACLs from
`setup-acls.sh` take care of this on the inbox).

## Option C - manual

Copy by hand into `inbox/`. Everything after that is automatic.
