# Privacy and security

Only initialize your own account and records you are authorized to process.
The bot owner is obtained from the official QR-authenticated channel account;
the local database identity is independently checked against actual contact data.

Credentials, database keys, chats and backups stay in private local directories.
Relevant chat text is sent to the explicitly authorized model provider. Do not
upload personal runtime directories, logs, prompts, crash reports, SQL files or
screenshots to a public issue. Subscription OAuth is not an API key billing exemption.

The reader uses a temporary ad-hoc-signed app copy. This is not a supported WeChat
history export API and may fail or be noticed by WeChat. We do not alter the
original app signature or SIP. Never disable Gatekeeper, SIP or antivirus to
make this package work. Recovery must restore the original app even on failure.

Model tools are restricted to owner-authorized history queries. Chat contents
are untrusted evidence, not executable instructions. The release does not give
the model shell, filesystem-write or other-contact sending capabilities.

Release checksums provide integrity, not independent publisher authenticity.
Inspect the source and fixed tag before running it. Open a public issue only
with sanitized reproduction steps; use GitHub's private vulnerability reporting
when available for an access-control problem. Never post keys or chat content.
