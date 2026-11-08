# Project design

Design version: v0.1 / Written: 2026-11-08 / Original status: planning draft, stage 1 generation implemented. This is the initial design snapshot; completed findings are recorded in the stage-specific results documents.

## 1. Portfolio statement

> Diagnose non-repurchase after a first order at a fictional coffee retailer, experimentally estimate the incremental profit of information and coupons, and design customer-level CRM operations.

The target role is **marketing planning**. Python supplies evidence for audience, message, benefit, and budget decisions. The explanation centers on the customer problem and the campaign decision, rather than model accuracy alone.

## 2. Fictional business

| Item | Initial assumption |
|---|---|
| Business | Online D2C coffee retailer |
| Products | 200g trial, 500g standard, and 1,000g large packages |
| Customer information | Acquisition, first product/payment/discount, delivery, consent, and site behavior |
| Channel | One email; no real names, phone numbers, or email addresses are generated |
| Proposed campaign | The same coupon for customers who have not repurchased |
| Decision | Assign no contact, information, or information + coupon to each eligible customer |

Coffee provides a useful scenario in which quantity and consumption can affect repurchase timing and information can be distinguished from a price incentive. This motivates the fictional setting; it does not establish a consumption cycle or a Korean market average.

At the design stage, low repurchase and segment churn are hypotheses, not findings. Generated observed data must establish whether such patterns appear.

## 3. Questions and hypotheses

| Business question | Hypothesis to test | Planning decision |
|---|---|---|
| When do first buyers return? | Timing may differ by quantity and early behavior. | Which journey stage warrants a later experiment? |
| Does every non-repurchaser need a coupon? | Discounts may be paid to customers who would buy anyway. | Retain or narrow blanket coupon targeting. |
| Can information alone help? | Storage/brewing information may improve some customers' experience. | Value proposition and message without a coupon. |
| Should targeting select likely buyers? | Purchase probability may differ from incremental intervention profit. | Audience-selection criterion. |
| Does short-term purchase growth improve profit? | Discounts, shipping, returns, and contact costs may change the net effect. | Expand, modify, or hold. |

All statements in this table are hypotheses. The generator does not force a particular model to win.

## 4. V1 scope

Included: CRM for customers with no additional payment by D+14 after first delivery; a three-arm experiment with the same date/channel; timing diagnosis, average effects, and heterogeneous-effect modeling; policy comparisons under equal budget/contact caps; segment messaging and an operating proposal.

Later work: a separate experiment randomizing sending schedules from a common starting population; repeated sends, subscriptions, recommendations, and advertising allocation; actual CRM integration/sending and dashboard deployment; lifetime value beyond 60 days and additional checks for purchase pull-forward.

## 5. Campaign draft

### Eligibility

Define `t0 = first-order delivery time` and `tA = t0 + 14 days`. Assess all requirements using information available strictly before `tA`:

1. The order is the customer's first paid order and has a delivery record.
2. No additional paid order has occurred since it, regardless of later cancellation/refund.
3. The first order is not already cancelled or fully refunded.
4. Marketing consent is valid and email is enabled.
5. The customer has not already been assigned to this experiment.

Post-assignment unsubscribe, sending failure, or non-redemption does not remove a customer from the assigned-arm denominator. Future refunds do not retrospectively change eligibility.

### Message concepts

| Arm | Draft message | CTA | Conditions |
|---|---|---|---|
| No contact | No additional experimental message | None | Identical essential order/shipping notices |
| Information | “Enjoy the rest of your coffee at its best. Explore storage and brewing tips.” | View storage/brewing tips | Package-size modules under the same template rules |
| Information + coupon | Identical information, plus “KRW 3,000 toward your next coffee order” | Same information page + benefit details | KRW 25,000 minimum; 14 days; one use; no stacked discount |

These are copy concepts. Recommendation logic, base content, sending time, and channel stay identical across active arms; only the coupon is added. Their difference can then be interpreted as the effect of adding the coupon package. V1 does not separately estimate copy effects. Later personalized copy must be defined as a new treatment or a prespecified content rule.

## 6. Planning success criteria

**Primary outcome:** the no-contact-relative difference in customer-level contribution profit from orders paid within 60 days after assignment, less CRM sending costs.

Non-purchasers remain in the denominator. Every redeemed discount enters accounting, including discounts used by customers who would otherwise buy. First-order profit is excluded because that order precedes assignment.

The fictional rollout assumptions are KRW 3,000,000 in reserved variable cost per 10,000 eligible customers, a 30% contact cap, and KRW 100,000 in separate fixed operating cost. Fixed cost is charged once if any customer is contacted and sits outside the KRW 3,000,000 cap. Full coupon face value is reserved at issuance; expected non-redemption does not justify over-issuance. Reserved budget and redeemed expenditure remain separate.

Success is a defensible decision with uncertainty and an operating plan:

- **Rollout candidate:** sufficient evidence of incremental profit for a fixed policy, with operating and side-effect criteria met.
- **Modify / test further:** a wide effect range or profit limited to some conditions.
- **Hold:** loss versus no contact or customer-experience metrics outside criteria.

Estimators and formal rules are defined in the [analysis plan](ANALYSIS_PLAN.md).

## 7. Planned portfolio deliverables

| Deliverable | Content | Planned completion |
|---|---|---|
| One-page campaign brief | Problem, audience, value, incentive, constraints, criteria | After analysis |
| Segment × message operating table | Eligibility, situation, message, CTA, exclusions | After policy selection |
| 3–6 message mockups | Evidence-linked copy and basic layout | After policy selection |
| Experiment report | Assignment checks, effects, accounting, policies, uncertainty | After final evaluation |
| 10–12-slide portfolio | Problem → findings → alternatives → selection → operations → limits | Final stage |
| GitHub repository | README, reproduction code, settings, tests, references | After publication checks |

This table records planned deliverables, not a claim that every mockup or slide deck has been produced.
