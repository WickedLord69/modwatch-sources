# ModWatch source catalog

Public GTA V / LSPDFR filename-to-release-page references, with a moderated contribution queue.

## Submit a source

Use **Submit source** in ModWatch, or open **Issues > New issue > Submit a mod source** here. Sign in to GitHub, review the public filename, mod name, author and source URL, check the confirmation, then submit. Your personal ModWatch source works immediately; sharing does not happen until the catalog owner approves it. Never upload DLLs, private file paths, credentials or file hashes.

## Owner: review the queue

Open **Issues**. The workflow adds a readable review receipt and a `pending` label. Review that the page belongs to the expected author and actually supplies the named plugin, not a vehicle/add-on that requires it. Automated checks verify structure and supported page categories; they do not certify authenticity, plugin safety or compatibility.

Copy the appropriate complete command from the bot receipt into a new comment:

- **Approve:** `/approve <review fingerprint>`
- **Reject:** `/reject <review fingerprint>`
- **Needs information:** `/needs-info <review fingerprint>`
- **Replace a different existing mapping:** `/replace <review fingerprint>`

The bot supplies the complete command, including the fingerprint. You do not need to type or understand the fingerprint. Only the repository owner can publish. A changed submission requires a new receipt and approval. External websites require the explicit `approve-external` or `replace-external` command shown in the receipt.

An approved command updates `catalog.json` automatically, adds `published`, and closes the proposal. Rejected proposals never enter the catalog. Questions can remain pending as long as needed. Editing the issue refreshes its review receipt. Duplicate approvals are idempotent, and concurrent catalog updates use GitHub's SHA conflict protection and retries.

## Catalog delivery

ModWatch reads the stable raw `catalog.json` URL from this repository, caching it for up to six hours when Find source is used. A new reference remains a suggestion until a user saves it for the installed file. A source mapping is not an automatic declaration that a mod is current.

The earlier ModWatch Gist remains a legacy snapshot. WL Editor's separate Gist is unrelated and is not changed by this repository.

## Implementation

The workflow runs trusted code from `main` and parses submission data as text/JSON. It never executes submitted code, downloads submitted binaries, or requests submitted URLs. GitHub's repository-scoped Actions token stays in the workflow; ModWatch clients contain no write token. Run `python3 -m unittest -v test_moderate.py` for offline moderation tests.
