# Kazhwan Bot v1.3 — Group Monitor

- Quiet hours every day from 23:00 to 11:00 Iran time for normal members; admins remain unrestricted.
- Restores the group's previous permissions at 11:00.
- Simple welcome message when a new member joins.
- Tracks group activity in PostgreSQL for registered and unregistered participants seen by the bot.
- Admin commands `/inactive30` and `/inactive60`.
- Referral reward changed to 5 points per successful new member.
- Existing group members can complete their profile in the bot's private chat without sending a new Join Request.
- Existing members receive a referral code after registration.

Note: activity tracking begins from the time this version is deployed (or from the time an existing member registers). Telegram bots do not receive a historical list of old member messages.
