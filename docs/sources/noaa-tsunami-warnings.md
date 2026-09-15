# NOAA tsunami warnings

DisasterMonitor reads the public Atom feeds published by NOAA's two U.S. tsunami warning centers and admits linked CAP-TSU documents as warning artifacts. CAP identity, sender, lifecycle references, areas, validity, profile, and XML-signature presence are preserved. Signature presence is not shown as cryptographic verification unless a verifier has actually succeeded.

The adapter uses an HTTPS host allowlist, rejects redirects, and applies response-byte and record limits. A tsunami warning never establishes that a physical tsunami occurred; observations and the causative seismic event remain separate evidence.

Attribution: Source: NOAA U.S. Tsunami Warning System. U.S. federal government source data is public domain, with NOAA attribution retained.
