# v1.4.4 — Scoped command menus

- Passengers in groups now only see public commands in Telegram's `/` menu.
- Group administrators see only group setup/operation commands.
- The full management command menu is shown only in configured admins' private chats.
- Existing server-side admin checks remain in place, so hidden management commands are still protected if typed manually.
- Built on v1.4.3 private trip management; no database migration is required for this release.
