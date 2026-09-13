# Formats and verified behavior

## Dependencies

The standard-library helper uses SQLite, JSON, subprocess, and pathlib. HTML parsing invokes `../book-notes-from-kindle/scripts/parse_kindle.py`; `--parser` can select another installed copy. Mapping needs the directory containing `kfxlib`, from John Howell's GPL-3.0 Calibre KFX Input plugin. Obtain it from the maintained [plugin distribution](https://www.mobileread.com/forums/showthread.php?t=291290); keep its license and dependencies (typically Pillow, lxml, pypdf) in an external environment. Pass that directory with `--kfxlib`. Decoder versions can affect support for recent KFX symbol tables. The skill does not vendor it or bypass DRM.

An implementation reference for content positions is [KFX-Highlights](https://github.com/jagajaga/KFX-Highlights). Binary `.yjr` inspection is described by [KRDS](https://github.com/K-R-D-S/KRDS). Neither is the source of truth for current device SQLite queue behavior: capture native samples.

## Input and review contract

JSON accepts either an array or `{"records":[...]}`. Each record has unique `id`, `kind` (`highlight` or `note`), and `text`. Optional `page`, `section`, and source metadata remain in the review report. Optional `created_time` and `modified_time` must be integer Unix milliseconds; otherwise the import time is used. HTML uses the sibling parser's record format.

A note requires `attach_to` pointing to a preceding resolved highlight, or `anchor_text` present in the target book. Attached notes are anchored at the highlight end. Arbitrary note-only page references cannot reliably establish an anchor.

Choices are a JSON object keyed by string record ID, e.g.:

```json
{"1":{"candidate":2},"2":{"attach_to":1},"3":{"anchor_text":"unique passage","candidate":1}}
```

The map stage writes review candidates with exact numeric ranges and surrounding text. If normalized matching spans unrelated intervening text, validation rejects it. Review headings, source pages, and caption context before resolving duplicates. Image positions count in KFX offsets even though the image is not searchable text.

## Native database profile: Kindle 5.19.6

This profile was verified on one device: 44 imported highlights appeared locally, then on the phone after queue insertion and synchronization. It is not an assurance for other firmware.

- `server_view`: native cached records. `dataset=1` is highlight; `dataset=3` is text note. Identity is `(annotation_id,dataset_id)`.
- `dataset_id` comes from `book_state`; for this adapter it is `<asin>-PDOC-<CR!guid>-<owned flag>`. Never invent an ASIN/GUID or use only the display title.
- IDs use `kindle.highlight-<start>` or `kindle.note-<start>`. A different annotation occupying that ID is a conflict, not permission to overwrite it.
- Payload fields: `book_data`, `created_time`, `last_modified`, `start_position`, `end_position`, `position_type=0`, `type`, and `json_metadata` (a JSON string). Notes carry `note_text` in metadata. Existing synced payloads can have an additional escaping layer.
- Positions contain numeric `shortPosition` and base64 `longPosition`. Decode the latter as `<BII`: version byte 1, little-endian uint32 EID, uint32 offset. End positions are inclusive. The `.yjr` representation appends `:<shortPosition>`; the database longPosition does not.
- `local_edit`: pending work, not merely another display cache. Native offline samples had `action=1`, `retry_count=0`, `expiration_timestamp=""`, `sync_behavior=0`. Highlights used `dirty_flag=0`; a new text note used `dirty_flag=1`. Preserve the type distinction. Highlight upload success is user-confirmed; new imported text-note upload remains to be verified end to end.
- Queue payload `last_modified` and row `modified_time` are current Unix milliseconds; preserve source creation time. Existing pending records are left untouched. A prior installed receipt suppresses requeuing consumed entries.

`schema-5.19.6.json` records exact table/column names for compatibility checking. Treat unexpected tables/columns as unsupported; do not delete them to satisfy validation.

## Failure and recovery boundaries

Reject unresolved matches, conflicting IDs, malformed positions, unsupported firmware/schema, active SQLite journal files, changed source DB/KFX, or failed readback. Keep candidate creation offline. Save all backups and receipts outside the repository with restricted directory permissions. The table comparison proves preservation of existing rows, not device or cloud acceptance.

A prior receipt is local evidence of an installation, not evidence of server acceptance. Queue disappearance can also mean rejection or loss. Verification requires phone-visible records, an export comparison, or explicit user confirmation; retain that distinction in the final response.

## Mapping and conflict checks

Mappings carry a fingerprint of their complete source snapshot. Preparation and installation verify that fingerprint, book membership, KFX path membership, and KFX content hash; remap older artifacts without a fingerprint. Unicode matching normalizes complete contiguous text runs using compatibility decomposition and case folding, retains combining marks and source-position provenance, and refuses to cross any missing text position (including an image). A desired span crossing an image must be split into separately reviewed highlights. Existing short and long positions must both match; changed or absent long anchors are conflicts requiring explicit investigation, not automatic reuse.
