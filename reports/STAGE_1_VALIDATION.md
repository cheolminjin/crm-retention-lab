# Stage 1 implementation validation

Written 2026-11-08. Historical validation of synthetic generation, eligibility, costs, and storage; **not marketing-effect analysis**.

| Item | Result |
| --- | --- |
| Python | Dedicated 3.14.3 environment; additional 3.10.7 compatibility |
| Tests | All 67 passed in each environment |
| Profile | `configs/smoke_v0_1.json`, seed 101, base scenario |
| Observation | Deliveries 2025-01-01–2025-06-30; cutoff 2025-07-01 |
| Customers | 1,000 |
| Observed tables | 8, totaling 27,200 rows |
| Contracts | Valid, 0 errors |
| Saved-file validation | Configuration/source hashes and contracts passed |
| Public sample | 20 customers, no oracle files |

Run ID: `sim-dc3916ec02ce89a5`. Local outputs are Git-excluded under `data/generated/smoke-v0.1/`; manifests/configuration snapshots support reproduction.

| Table | Rows |
| --- | ---: |
| customers | 1,000 |
| orders | 1,892 |
| order_events | 3,832 |
| order_ledger | 11,544 |
| customer_events | 6,906 |
| assignments | 676 |
| contacts | 429 |
| eligibility_audit | 921 |

There were 79 customers before D+14. Of 921 assessed, 676 were assigned: control 247, information 208, coupon 221. Only 324 assignments completed 90-day outcome/settlement. **Immature outcomes were not finalized as zero profit or no repurchase.** These counts validate denominators/observation, not arm effects or policy superiority.

## Hand-calculated costs

A 500g order priced at KRW 28,000 uses a KRW 3,000 coupon and pays KRW 3,000 shipping:

```text
Discounted items 25,000 + customer shipping 3,000
− product cost 12,000 − outbound shipping 3,000
− fulfillment 700 − payment fee 700
= order contribution profit 11,600 KRW
− CRM send cost 20 KRW
= customer contribution profit 11,580 KRW
```

Do not deduct the KRW 3,000 coupon again. Unused coupons cost no discount; failed/unopened attempts still cost KRW 20. Refund cases return actual item/shipping payments and separately account for inventory recovery and return handling.

## Risks checked

Eligibility uses pre-assignment records; later refunds/withdrawals do not alter ITT. Purchase windows include starts and exclude ends, and labels exclude records at/after freeze. Later execution dates cannot mature outcomes beyond saved observation. Purchases/events/delivery/ledger after cutoff are hidden. Checks detect repeated/cross-customer/expired coupons and duplicate discounts, enforce observed-field/table allowlists, preserve seeds and existing-customer streams when expanding populations, preserve product costs in A/A, and retain organic discount costs under zero behavioral effect. Storage preserves types and rejects tampering/overwrites.

Restricted Windows temporary-directory access required project-local `.test-tmp/`. It is ignored by Git and cleanup verifies that paths stay inside the project.

## Unverified at this stage

Real-consumer fit, final power, survival/uplift performance, policy incrementality, and long-run demand were unverified. Actions was prepared but not remotely run. Assignment-time marts, mature outcomes/censoring, and cohort/survival analysis were the next stage, with separate fixed assumptions/evaluation windows.
