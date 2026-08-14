# v1.4.6

- Fix private trip management crash when Railway runtime exposes a Database object without `list_trips`.
- Added a compatibility query in the admin handler using the existing async session factory.
- Added an explicit v1.4.6 startup fingerprint to Railway logs.
- Keeps v1.4.4 scoped command menus and v1.4.3 private trip management.
