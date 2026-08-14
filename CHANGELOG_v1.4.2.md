# Kazhwan Bot v1.4.2

## Membership split

- Existing `KZH-xxxxxx` member codes are preserved exactly as Kazhwan membership codes.
- BTC membership is now separate and stored in `btc_memberships`.
- Existing approved BTC members automatically receive a new `BTC-xxxxxx` code on first startup after deployment.
- Kazhwan users who are not BTC members do not receive a BTC code.
- A Kazhwan user who later joins BTC keeps the same KZH code and receives an additional BTC code after accepting BTC rules.
- Referral codes remain Kazhwan-wide (`KZH-Rxxxxxx`).

## Referral points

- Successful referral reward remains 5 points.
- Referral reward is now Kazhwan-wide and no longer requires the referred user to join BTC.
- The migration prevents previously rewarded referrals from receiving duplicate points.

## Trip categories and points

- Domestic one-day: 5 points.
- Domestic multi-day: 15 points.
- International: 100 points.
- The trip's points value is stored on the trip record at creation time.
- Points are awarded only after an admin marks the passenger as `attended`.
- Each passenger can receive the trip points only once, even if `tripattend` is run repeatedly.
- Existing legacy domestic trips are migrated to `domestic_multi` (15 points) until redefined with `/settrip`.

## Tour-group registration

- BTC membership is not required to record a tour.
- Membership in `@Kazhwantravel` is required.
- Existing Kazhwan users are checked for channel membership when confirming a trip.
- New trip users complete the Kazhwan profile + channel check without being forced to join BTC or accept BTC group rules.

## Reports

- BTC code is included separately in member profile/admin output.
- Excel member export includes separate Kazhwan and BTC codes.
- Domestic trip history includes one-day/multi-day labels and awarded points.
- International history remains a separate column.
