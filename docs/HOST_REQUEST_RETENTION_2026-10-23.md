# Protected host request retention — October 23, 2026

## Policy and scope

The host journal admits at most 250,000 permanent request identities and 256 MiB
of protected content plus reservations per authenticated owner, shared across
that owner's projects and Dots. Each claim reserves 3 MiB for its result and
1 KiB for possible retirement overhead. Completed records retain the 1 KiB
reservation until compaction. Existing requests can always be inspected or
deduplicated even when admission of new requests is blocked by a budget.

These limits bound journal records/content, not SQLite indexes, WAL, backups,
other stores or total disk usage. Pre-policy stores above a limit are preserved
and new effects are refused; opening the store does not delete existing data.

For terminal input, the host records acknowledgement in the same transaction as
removing the exact pending selector. After seven days from the first successful
acknowledgement, a bounded pass (64 records) retires the protected command text.
Passes run on later journal invocations within the same project; acknowledged
records in an inactive project require an explicit maintenance pass. Idle time
alone does not run a background deletion service.

Unacknowledged, uncertain, claimed and asynchronous operations never expire.
A committed outer response is not proof of a completed physical operation.
Generic host operations currently retain their full protected original/result;
they are bounded by admission, not silently aged out.

## Permanent deduplication and inspection

Retirement keeps the original owner, project, request key and fingerprint. The
protected tombstone retains terminal/incarnation identity, delivery/refusal
status, original byte count, and an explicit retired-content explanation. It is
not a task-completion receipt. Original selectors remain inspectable without
reconstructing or storing the deleted command. A repeated matching invocation
returns the receipt; a different intent using the same key is rejected.

No request key is deleted. Reaching the metadata limit therefore requires an
explicit future archival policy or increased storage budget; it cannot be fixed
by pruning deduplication keys and silently permitting old effects to run again.
No input, result or operation is replayed as part of retention.

## Migration and rollback

Migration is transactional and additive. The base journal remains schema version
2; the separate retention extension is version 1. Original protected records are
not decoded or rewritten during migration. Triggers account for writes made by
compatible older applications, and journal identity columns are immutable.

A schema-v2 rollback still finds and returns the retained protected result for
an original invocation. It cannot execute that key again. Old status endpoints
that require reconstructing the complete input payload cannot reconstruct text
already retired by a newer version; the updated status endpoint understands the
tombstone explicitly. Rollback does not promise recovery of retired content.

Retirement does not erase older filesystem backups or promise cryptographic
erasure of SQLite/WAL pages; the removed command was OS-protected at rest.

## Validation

Tests use disposable databases and ConPTY sessions only. They cover exact scope,
lost confirmations, inspection after journal reopening, unchanged permanent keys,
uncertain/asynchronous exclusions, pending cross-device selectors, first-ACK age,
shared concurrent reservations, small-input compaction overhead, compatible older
writes, future-version refusal and full rollback of an injected migration error.
No installed user store is compacted by these qualification commands.
