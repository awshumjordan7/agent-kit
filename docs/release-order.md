# Layered release order

Release changes that affect the private overlay in this order:

1. Merge the agent-kit change and tag the core release.
2. Update the overlay's `requires_agent_kit` pin to that exact tag.
3. Run `python3 install.py update` from the overlay checkout.
4. Verify the installed Forge files match the tagged core plus the overlay allowlist, and run doctor.

Never bump the overlay pin before the core tag exists. The installer resolves the pin during update, so reversing the order can leave an installation on stale core files while presenting current overlay documentation.
