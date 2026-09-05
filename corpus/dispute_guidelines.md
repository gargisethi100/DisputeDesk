# Card dispute guidelines for merchants

Paraphrased for retrieval from public sources: the RBI circular on harmonisation of turn-around
time and customer compensation (RBI/2019-20/67, DPSS.CO.PD No.629/02.01.014/2019-20, 20 Sep 2019),
and publicly documented Visa and Mastercard dispute reason codes and time limits. Source URLs are
listed in the README. This is guidance for the agent's retrieval layer, not legal advice; the
network operating regulations and the acquirer's dispute process are authoritative.

Each `##` section is one retrievable passage. Citations must quote these passages verbatim.

## Dispute lifecycle and stages

A card dispute begins when the cardholder contacts their issuing bank and the issuer raises a
chargeback through the card network against the acquirer. The disputed amount is provisionally
debited from the merchant. The merchant then has a fixed window to respond. There are four stages:
the initial dispute (first chargeback), the merchant response (representment or second
presentment), pre-arbitration, and arbitration. At each stage the party that fails to respond
within the time limit loses by default. A merchant response filed with the network is final and
cannot be withdrawn or amended once submitted.

## Timelines for merchant response

Under Visa rules the cardholder may raise a dispute up to 120 days from the transaction date or
the expected delivery date, and the merchant has 30 days to respond at each phase of the dispute.
Under Mastercard rules the cardholder generally has 120 days from the transaction date, the
merchant has 45 days from the first chargeback to submit a second presentment, and if the case
proceeds to pre-arbitration the merchant has 30 days to challenge it and loses automatically if
no response is filed. Acquirers and payment aggregators commonly set an earlier internal deadline
so that the response can be reviewed and forwarded within the network window. A response that
misses the deadline is treated as acceptance of the dispute.

## Reason code 10.4 fraud card-absent environment

Reason code 10.4 (Visa: Other Fraud, Card-Absent Environment; Mastercard equivalent 4837, No
Cardholder Authorization) means the cardholder claims they did not authorise a card-not-present
transaction. To contest, the merchant must show that the genuine cardholder participated in the
transaction. Compelling evidence includes an AVS match and CVV2 match, 3-D Secure authentication,
the IP address and device fingerprint used, proof that the same device or credentials were used
in earlier undisputed purchases, and delivery confirmation tying the cardholder to the order.
Under Visa Compelling Evidence 3.0 the merchant may also cite two prior undisputed transactions
between 120 and 365 days old that share matching data points with the disputed one.

## Reason code 12.6 duplicate processing

Reason code 12.6 (Visa: Duplicate Processing / Paid by Other Means; Mastercard equivalent 4834,
Point-of-Interaction Error) means the cardholder claims a single purchase was charged more than
once, or was already paid by another method. To contest, the merchant must provide settlement
or batch records proving that the transaction was submitted only once, or receipts showing that
the two charges were for separate purchases. If the merchant's own records show two captures of
the same amount on the same card for the same order within minutes of each other, the charge is
a genuine duplicate and the correct action is to refund or accept the dispute rather than contest.

## Reason code 13.1 merchandise or services not received

Reason code 13.1 (Visa: Merchandise/Services Not Received; Mastercard equivalent 4853, Goods or
Services Not Provided) means the cardholder claims the goods or services were not delivered by
the promised date. To contest, the merchant must provide tracking and signature-confirmed proof
of delivery matching the billing or shipping address on the order. For digital goods or
services, proof of access, download logs, or usage records tied to the cardholder's account serve
the same purpose. A shipment that is still in transit or shows no delivery confirmation does not
satisfy this requirement.

## Reason code 13.2 cancelled recurring transaction

Reason code 13.2 (Visa: Cancelled Recurring Transaction; Mastercard equivalent 4853, Cancelled
Recurring Billing) means the cardholder claims they were charged after cancelling a subscription
or recurring service. To contest, the merchant must provide the subscription terms accepted at
sign-up, the cancellation policy, evidence of any renewal notice sent, and records showing the
customer did not cancel before the billing date. If the merchant's records show the cancellation
request was received before the renewal charge, the charge was made in error and should be
refunded rather than contested.

## Reason code 13.3 not as described or defective merchandise

Reason code 13.3 (Visa: Not as Described or Defective Merchandise/Services; Mastercard equivalent
4853, Goods or Services Not as Described or Defective) means the cardholder claims the item
received differs materially from its description or arrived damaged or defective. To contest,
the merchant must provide the product description shown at checkout compared with what was
delivered, photographs or quality-control records, and the customer communications showing that
the merchant attempted to resolve the complaint, including any return or replacement offer. A
complaint that went unanswered by the merchant weakens the case significantly.

## Reason code 13.6 credit not processed

Reason code 13.6 (Visa: Credit Not Processed; Mastercard equivalent 4853, Credit Not Processed)
means the cardholder claims they were promised a refund or credit that was never applied. To
contest, the merchant must provide the refund confirmation with date, amount, and reference
number showing the credit was already processed to the same card. If a refund was processed,
contesting with that proof prevents the cardholder from being credited twice. If no refund was
processed and the cardholder was entitled to one, the merchant should issue the refund or accept
the dispute.

## Evidence requirements by reason code

The evidence a merchant submits must be specific to the reason code. Evidence that does not
address the cardholder's actual claim is disregarded. For not-received disputes the decisive
evidence is signed proof of delivery. For card-absent fraud it is authentication and device data
proving the cardholder's participation. For not-as-described disputes it is the original product
description together with customer communications. For cancelled recurring transactions it is
the accepted terms and the cancellation timeline. For credit-not-processed disputes it is the
refund record. For duplicate processing it is settlement records showing a single capture. Where
the required evidence is missing the merchant should not contest on the remaining material.

## Accepting a dispute

A merchant may accept a dispute either explicitly or by not responding before the deadline. On
acceptance the provisional debit becomes final and the case closes with no further fees. A
merchant should consider accepting when the required evidence for the reason code is not
available, when the merchant's own records confirm the cardholder's claim, or when the disputed
amount is small relative to the cost and risk of contesting. Accepting a dispute is not an
admission of fraud and does not by itself affect the merchant's standing, but a high ratio of
disputes to transactions can trigger network monitoring programmes.

## RBI harmonisation of turn-around time and customer compensation

The Reserve Bank of India circular on harmonisation of turn-around time (TAT) and customer
compensation for failed transactions applies to all operators and participants of authorised
payment systems. For point-of-sale and e-commerce card transactions where the customer's account
is debited but confirmation is not received at the merchant, the framework requires auto-reversal
within T + 5 days, where T is the calendar date of the transaction, with compensation of Rs 100
per day of delay beyond T + 5 days. The circular states that where financial compensation is
involved, it shall be effected to the customer's account suo motu, without waiting for a
complaint or claim from the customer. This framework governs failed transactions and is distinct
from the card-network chargeback process, but customers frequently raise disputes for failed
debits that fall under it, and such cases should be resolved by reversal rather than contested.

## Escalation to pre-arbitration and arbitration

If the issuer does not accept the merchant's response it may escalate to pre-arbitration, and if
the parties still disagree the case proceeds to arbitration where the network makes a binding
ruling. Under Mastercard rules the merchant has 30 days to respond to pre-arbitration and the
network rules within 10 days of an arbitration filing. Network fees apply at these stages and are
charged to the losing party. For low-value transactions these fees can exceed the disputed amount,
so a merchant should escalate only when the evidence clearly meets the reason-code requirements.
A case that is uncertain on the evidence, or that is close to a deadline, should be referred to a
human reviewer rather than committed to either contest or accept.
