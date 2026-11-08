# Data and simulation design

Historical stage-1 design snapshot: observed-data generation, eligibility, and ledger validation were complete; analysis marts were still planned. Later implementation status is documented in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Scale, distributions, prices, and effects are project assumptions, not measurements. The [design configuration](../configs/design_v0_1.json) holds key values and the [generator assumptions](../configs/generator_v0_1.json) hold coefficients.

## 1. Scale and observation

- Initial design: 60,000 first-delivery customers, not a power-derived experiment sample.
- Stage 1 actually generated a development profile of 1,000 customers delivered in January–June 2025, observed through 2025-07-01.
- Full-design first deliveries: 2025-01-01 through 2026-07-31; observation cutoff: 2026-08-01 00:00:00, Asia/Seoul.
- Monetary values are integer KRW; timestamps are timezone-aware.
- Each order has one SKU and integer quantity. Multi-SKU baskets are a future extension.
- Deliveries and D+14 assignments use daily 09:00 slots. Allocate budget using only features of customers already confirmed in that batch.
- Generate early repurchasers, customers without consent, recent arrivals with short observation, and customers with additional payments before their first delivery. The last group is excluded from the D+14 experiment.

Final evaluation size follows eligibility and time splitting. Generated-customer counts are not assignment counts.

## 2. Three data layers

| Layer | Location | Rules |
| --- | --- | --- |
| Observed sources | `data/generated/<run>/observed/` | Orders, behavior, and assignments collectible in real systems; stage-1 JSONL |
| Analysis marts | `data/generated/<run>/marts/` | Planned assignment-time features, window outcomes, and splits |
| Simulator truth | `data/oracle/<run>/` | Only latent traits implemented at this stage; potential outcomes planned; excluded from analysis inputs |

Oracle data are internal synthetic-generator state, not confidential customer information. Public source exposes the generator, so the safeguard is **restricted and validated analysis inputs**, not complete information concealment.

## 3. Observed-table contracts

All source tables contain `simulation_id` and `schema_version`. Distinguish event time (`occurred_at`) from availability (`recorded_at`), with `recorded_at >= occurred_at`. Features require both times before assignment.

Eligibility-related payment, delivery, cancellation/refund, consent/withdrawal, and contactability records are immediate operational logs. Only analytics logs such as sessions, tip views, carts, and opens can be delayed by up to 7 days. V1 does not retrospectively exclude customers assigned because a repurchase record arrived late.

| Table / row unit | Required fields | Notes |
| --- | --- | --- |
| `customers` / customer | `customer_id`, `created_at`, `acquisition_channel`, `acquisition_recorded_at` | No names, contact details, or national IDs; preserve consent history |
| `orders` / paid order | `order_id`, `customer_id`, `paid_at`, `paid_recorded_at`, `delivered_at`, `delivery_recorded_at`, `sku`, `quantity`, `list_subtotal_krw`, `other_discount_krw`, `crm_coupon_discount_krw`, `item_revenue_after_discount_krw`, `coupon_assignment_id` | Order-time price snapshot; includes first orders; refunds do not delete payments |
| `order_events` / status event | `order_event_id`, `order_id`, `event_type`, `occurred_at`, `recorded_at` | Delivery, cancellation, full refund; reconstruct eligibility from then-known states |
| `order_ledger` / financial entry | `entry_id`, `order_id`, `entry_type`, `amount_krw`, `occurred_at`, `recorded_at` | Revenue positive, costs/refunds negative, inventory recovery separately positive |
| `customer_events` / behavior event | `event_id`, `customer_id`, `event_type`, `occurred_at`, `recorded_at`, nullable `order_id` | Sessions, tips, carts, consent, withdrawal, contactability; preserve history |
| `assignments` / assignment | `assignment_id`, `customer_id`, `first_order_id`, `first_delivered_at`, `assigned_at`, `arm`, `p_control`, `p_info`, `p_coupon`, `eligibility_version` | At most one per customer; all three probabilities sum to 1; independent of delivery success |
| `contacts` / send attempt | `contact_id`, `assignment_id`, `attempted_at`, `delivered_at`, `opened_at`, `clicked_at`, `send_cost_krw`, `coupon_issued_at`, `coupon_expires_at` | No control rows; retain failed/unopened sends; costs assumed per attempt |
| `eligibility_audit` / D+14 decision | `customer_id`, `evaluated_at`, `eligible`, `reason_codes`, `latest_available_record_at` | Customers not yet at D+14 remain pending, without an eligibility decision |

`coupon_assignment_id` links redemption orders to issuance. Validate one use per customer, minimum item subtotal KRW 25,000, and payment within validity. Issuance without an order remains in `contacts`.

### Ledger

Positive entry types: `net_item_revenue`, `customer_shipping_charge`, `cogs_recovery`. Negative types: `refund`, `cogs`, `outbound_shipping`, `fulfillment`, `payment_fee`, `return_handling`.

`net_item_revenue` is already net of every discount. Coupon amounts in orders explain spending and are not deducted again in the ledger. Inventory recovery records recovered value, separate from refunds. V1 assumes every financial adjustment occurs and is recorded within 30 days of payment, allowing settlement at `outcome_end_at + 30 days`. Modeling longer lags would require revising this cap and metric definitions.

## 4. Analysis marts

### `features_at_assignment`

One row per assigned customer. Metadata (`customer_id`, `assignment_id`, `feature_cutoff_at`, `feature_version`) are separate from model inputs.

| Feature | Meaning |
| --- | --- |
| `first_pack_grams`, `first_quantity` | First package size and quantity |
| `first_paid_amount_krw`, `first_discount_rate` | Initial payment and discount experience |
| `delivery_lead_days` | Days from first payment to delivery |
| `acquisition_channel` | Acquisition channel |
| `sessions_d0_d13`, `tip_views_d0_d13`, `cart_events_d0_d13` | Behavior from delivery until immediately before assignment |
| `days_since_last_session` | Recency before assignment; explicit missingness for no sessions |
| `first_delivery_month` | Seasonality diagnostic/model candidate |

RFM frequency offers little separation among first buyers. Use initial purchases and pretreatment behavior instead of end-of-observation RFM. Exclude treatment arm, opens/clicks, redemption, post-assignment visits/purchases, final total revenue, future refund status, latent price sensitivity, and true effects. Treatment arm only separates T-learner training groups.

### `outcomes_after_assignment`

One row per assignment; final outcomes remain `null` until their windows mature.

| Field | Definition |
| --- | --- |
| `outcome_start_at` | `assigned_at` |
| `outcome_end_at` | `assigned_at + 60 days` |
| `settlement_end_at` | `outcome_end_at + 30 days` |
| `is_outcome_mature`, `is_profit_settled` | Outcome/settlement windows complete before observation cutoff |
| `repeat_paid_within_60d` | Additional payment within window; remains 1 after refund |
| `days_to_first_repeat_paid`, `repeat_event_observed` | Time to first additional payment or censoring, and event indicator |
| `order_count_60d` | Orders paid within window |
| `contribution_profit_60d_krw` | Settled profit on window orders minus send costs |
| `refund_amount_krw`, `refund_customer_flag` | Refund amount/customer indicator for those orders through settlement |
| `unsubscribe_60d` | Unsubscribe within window |
| `actual_campaign_spend_krw` | Send costs plus redeemed discounts; separate explanatory spending metric |

All intervals are **start inclusive, end exclusive**. Include only orders paid within the outcome window and ledger entries with `recorded_at < settlement_end_at`; exclude later new orders. Every final label records `label_freeze_at = settlement_end_at`. Non-ledger outcomes also require `recorded_at < label_freeze_at` as well as valid event timing. Freeze times cannot exceed split-specific availability or the overall observation cutoff. Historical analyses cannot use records collected afterward.

With real-time payment/consent logs, provisional survival censoring is `min(assignment+60 days, analysis time)`. Delayed analytics events are usable only if already available; do not backfill late pre-assignment sessions into old features. Non-repurchasers contribute observed follow-up to survival analysis, while final 60-day profit/rate analyses use prespecified mature cohorts.

## 5. Generation process

1. Generate arrival/channel and latent consumption speed, preferences, and price sensitivity.
2. Generate first products, quantities, discounts, and delivery, with only partial relationships between observed features and latent traits.
3. Generate early behavior and natural repurchases. Daily purchase hazard depends on consumption, elapsed time, season, and customer differences.
4. Assess eligibility immediately before D+14 and randomize 1:1:1 with an independent random stream.
5. Generate delivery, responses, purchase times/amounts, redemption, returns, and unsubscribes, including failed and unopened sends.
6. Write only assigned-action observations to analysis sources; separate latent state and other potential outcomes into oracle storage.
7. Build ledgers/marts and validate contracts, eligibility, timing, and finances.

Baseline repurchase propensity and intervention response are distinct. Do not force positive coupon effects for everyone. Apply discounts to organic purchases too. Effect/noise settings are design assumptions and must not be tuned after seeing results to make a model win. Short-run purchase gains do not establish long-run demand gains. Unsubscribes do not censor purchases. First-order refunds are assumed unaffected by CRM; changing this assumption would require a metric including first-order adjustments.

## 6. Prespecified scenarios

| ID | Change | Failure mode |
| --- | --- | --- |
| `base` | Noisy heterogeneous effects partly related to observed features | Can segments/models support useful decisions? |
| `no_behavior_effect` | Zero purchase-behavior effects; redemption/send costs remain | False claims of profit improvement |
| `uniform_effect` | Small between-customer effect differences | Unnecessary personalization replacing simple policies |
| `cost_stress` | Product costs +20%, shipping +20% | Revenue-focused decisions vulnerable to costs |
| `response_shift` | Feature/effect relationships weaken or reverse in final period | Failure of learned targeting rules to transfer |
| `lower_demand` | Baseline daily purchase odds ×0.7 | Profit and uncertainty under weaker demand |

`no_behavior_effect` has zero **purchase-behavior** effects, not necessarily zero profit effects because discounts/send costs remain. The separate `a_a_zero_cost` validation scenario equalizes both behavior and costs.

The base JSON is a project-wide reference; profiles combine it with generator coefficients, dates, counts, and seeds. Stage 1 implemented `base`, `no_behavior_effect`, and `a_a_zero_cost`, fixing their coefficients in generator JSON. Other scenarios remain future work. The [development profile](../configs/smoke_v0_1.json) links design and generation settings.

The current generator simulates initial purchases and transactions through 60 days after D+14. Absence of later transactions is not churn evidence. Incremental coupon purchase effects require unused, delivered, valid coupons. Stage-1 oracle stores latent customer traits, not action-specific potential outcomes yet.

## 7. Randomness, oracle, and limitations

Record the base seed and separate customer, assignment, purchase, contact, and refund streams so changes in one process do not shift all others. One realized potential-outcome difference is not a customer's deterministic mean treatment effect. Repeated simulation should assess policy value; an oracle policy using latent state would be an unattainable reference upper bound.

Disclose generation formulas, assumptions, and sensitivity results. Independent-seed and structurally different evaluations are complementary; neither validates real-market effects.
