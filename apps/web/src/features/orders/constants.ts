export interface CheckInfo {
  label: string;
  what: string;
  why: string;
  onFail: string;
}

export interface CheckGroup {
  key: string;
  title: string;
  blurb: string;
  from: number;
  to: number;
}

export interface PipelineStepInfo {
  step: string;
  name: string;
  description: string;
}

export const HELD = "The order is held for your review. Fix the cause, then approve it.";
const HELD_AI = "The order is held with a warning. Read it, and you can still approve; the check then shows as accepted by you.";

export const CHECK_INFO: Record<string, CheckInfo> = {
  P01: {
    label: "Agent signature verified",
    what: "The agent proved who it is with its cryptographic key when it started this checkout.",
    why: "Stops a stolen or forged agent key from placing orders in your name.",
    onFail: HELD,
  },
  P02: {
    label: "Agent is active",
    what: "The agent exists and has not been disconnected from your account.",
    why: "A disconnected agent must never be able to spend your money.",
    onFail: HELD,
  },
  P03: {
    label: "Agent belongs to the buyer",
    what: "The agent that placed the order is connected to your account and nobody else's.",
    why: "Stops one person's agent from charging another person.",
    onFail: HELD,
  },
  P04: {
    label: "Request matches buyer and agent",
    what: "The purchase request behind this order was made by you, for this same agent.",
    why: "Stops an order from being attached to a request it was never made for.",
    onFail: HELD,
  },
  P05: {
    label: "Request is signed",
    what: "Your purchase request carries a valid digital signature that has not been altered.",
    why: "Proves the request really came from you and was not changed on the way.",
    onFail: HELD,
  },
  P06: {
    label: "Request signed within 24 hours",
    what: "The signed request is less than 24 hours old.",
    why: "Stops an old request from being replayed to buy something later.",
    onFail: HELD,
  },
  P07: {
    label: "Spending rule check passed",
    what: "The earlier spending rule step finished with a pass for this order.",
    why: "Makes sure the order was measured against your rules before any money moved.",
    onFail: HELD,
  },
  P08: {
    label: "An active spending rule covers this order",
    what: "A spending rule that is switched on and in date applies to this agent and store.",
    why: "No rule means you never allowed the agent to spend here.",
    onFail: HELD,
  },
  P09: {
    label: "Store allowed by spending rule",
    what: "The store is on the list of stores your rule allows.",
    why: "Stops an agent from being tricked into paying a store you never chose.",
    onFail: HELD,
  },
  P10: {
    label: "Item categories allowed by spending rule",
    what: "Every item in the cart belongs to a category your rule allows.",
    why: "Keeps the agent buying only the kinds of things you agreed to.",
    onFail: HELD,
  },
  P11: {
    label: "Within spending rule budget",
    what: "This order plus what you already spent in the rule's period stays within its budget.",
    why: "Stops overspending, even in small steps.",
    onFail: HELD,
  },
  P12: {
    label: "Currency matches spending rule",
    what: "The order is in the same currency as the rule.",
    why: "Stops a budget from being dodged by switching currency.",
    onFail: HELD,
  },
  P13: {
    label: "Order total within the per-order limit",
    what: "The total is above zero and no more than the 2,500.00 cap on a single order.",
    why: "Limits the damage any single order can do.",
    onFail: HELD,
  },
  P14: {
    label: "Cart is well formed",
    what: "The cart has 1 to 20 lines, each with a quantity of 1 to 20 and a price with two decimals.",
    why: "Malformed carts hide errors and abuse, such as huge quantities or odd prices.",
    onFail: HELD,
  },
  P15: {
    label: "Line totals add up to the order total",
    what: "Unit price times quantity for every line adds up exactly to the order total.",
    why: "Stops hidden extra charges and rounding tricks.",
    onFail: HELD,
  },
  P16: {
    label: "Cart matches what you approved",
    what: "The items, quantities and store match the cart you approved, and no price is higher.",
    why: "Stops a price swap or a different item between your approval and payment.",
    onFail: HELD,
  },
  P17: {
    label: "No other open order for this request",
    what: "No other order for the same request is still open or already paid.",
    why: "Stops one request from being charged twice.",
    onFail: HELD,
  },
  P18: {
    label: "Not a duplicate of a recent payment",
    what: "You did not pay the same amount to the same store in the last 10 minutes.",
    why: "Catches accidental double purchases and agent loops.",
    onFail: HELD,
  },
  P19: {
    label: "Agent under its daily order limit",
    what: "The agent has not gone over its allowed number of orders in the last 24 hours.",
    why: "Stops a runaway or hijacked agent from placing orders in bulk.",
    onFail: HELD,
  },
  P20: {
    label: "Within your daily spending limit",
    what: "Today's paid orders plus this one stay within the 5,000.00 daily limit.",
    why: "Caps how much can leave your account in a single day.",
    onFail: HELD,
  },
  P21: {
    label: "Verified email on file",
    what: "Your account has an email address that you have verified.",
    why: "We need a way to reach you about every payment and a way to confirm it is really you.",
    onFail: HELD,
  },
  P22: {
    label: "Shipping address on file",
    what: "You have saved a shipping address in your account.",
    why: "Without an address nothing can be delivered to you.",
    onFail: `${HELD} Add your address first.`,
  },
  P23: {
    label: "Shipping address is complete",
    what: "The address has a name, street, city, postal code and a 2-letter country code.",
    why: "Incomplete addresses lead to lost parcels.",
    onFail: `${HELD} Complete your address first.`,
  },
  P24: {
    label: "Shipping country matches your country",
    what: "The address is in the same country as the one on your account.",
    why: "A parcel going abroad is a common sign of a hijacked account.",
    onFail: HELD,
  },
  P25: {
    label: "Payment authorization exists",
    what: "PayPal has reserved the money for this order, so it can be charged or released.",
    why: "Sepilo only charges money that PayPal is already holding for this exact order.",
    onFail: HELD,
  },
  P26: {
    label: "No prompt injection found",
    what: "An AI scan of the store pages found no hidden instructions aimed at your agent.",
    why: "Stops a web page from secretly telling your agent to buy something else.",
    onFail: HELD_AI,
  },
  P27: {
    label: "Order matches your request",
    what: "An AI check confirms each item in the cart is something you actually asked for.",
    why: "Stops your agent from buying items you never requested.",
    onFail: HELD_AI,
  },
  P28: {
    label: "Store risk is low",
    what: "The store's risk score in the fraud graph is low.",
    why: "Keeps your money away from stores linked to fraud.",
    onFail: HELD_AI,
  },
  P29: {
    label: "No price anomaly",
    what: "No item is priced far above what the same item normally costs.",
    why: "Catches inflated prices and price tricks.",
    onFail: HELD_AI,
  },
  P30: {
    label: "Store pages use HTTPS",
    what: "Every store page the agent read was loaded over a secure HTTPS connection.",
    why: "Pages loaded insecurely can be changed by someone in between.",
    onFail: HELD,
  },
  P31: {
    label: "Store domain is valid",
    what: "The store name is a proper web domain.",
    why: "Stops look-alike or made-up store names.",
    onFail: HELD,
  },
  P32: {
    label: "Payment notice emailed to you",
    what: "Sepilo sends you an email about the payment once all other checks pass.",
    why: "You always get a written record of money that is about to leave.",
    onFail: "The payment waits until the email can be sent. If other checks failed, the email is not sent.",
  },
};

export const CHECK_GROUPS: CheckGroup[] = [
  { key: "identity", title: "Identity", blurb: "Is this really your agent?", from: 1, to: 3 },
  { key: "request", title: "Request", blurb: "Did you really ask for this?", from: 4, to: 6 },
  { key: "rules", title: "Spending rules", blurb: "Does the order fit the rules you set?", from: 7, to: 12 },
  { key: "cart", title: "Cart", blurb: "Is the cart correct and what you approved?", from: 13, to: 16 },
  { key: "limits", title: "Limits", blurb: "Is this safe against double or runaway spending?", from: 17, to: 20 },
  { key: "account", title: "Account and address", blurb: "Can we reach you and deliver the order?", from: 21, to: 24 },
  { key: "payment", title: "Payment", blurb: "Is the money reserved in PayPal?", from: 25, to: 25 },
  { key: "ai", title: "AI checks", blurb: "Does anything on the pages look wrong?", from: 26, to: 29 },
  { key: "store", title: "Pages and store", blurb: "Are the store and its pages trustworthy?", from: 30, to: 31 },
  { key: "notice", title: "Notice", blurb: "Were you told about the payment?", from: 32, to: 32 },
];

export const PIPELINE_STEPS: PipelineStepInfo[] = [
  { step: "verify_agent", name: "Verify the agent", description: "Confirms the agent is yours and signed this order." },
  { step: "check_mandate", name: "Check your spending rules", description: "Compares the store, items and amount with your rules." },
  { step: "authorize_payment", name: "Hold the funds", description: "Asks PayPal to reserve the money without charging it." },
  { step: "scan_injection", name: "Scan the store pages", description: "Looks for hidden instructions aimed at your agent." },
  { step: "intent_diff", name: "Match your request", description: "Checks the cart contains what you asked for, at a fair price." },
  { step: "graph_risk", name: "Check the fraud graph", description: "Looks up the store's links to known fraud." },
  { step: "decide", name: "Decide", description: "Combines every result into pay, hold for you, or block." },
  { step: "preflight", name: "32 security checks", description: "Runs the final list of payment checks before any charge." },
  { step: "capture_or_void", name: "Pay or hold", description: "Charges the held funds, releases them, or waits for you." },
  { step: "build_proof", name: "Record the proof", description: "Saves a signed record of the request, the rules and every check." },
];

export function checkNumber(id: string): number {
  const n = Number.parseInt(id.slice(1), 10);
  return Number.isNaN(n) ? 0 : n;
}

export function groupOfCheck(id: string): CheckGroup | null {
  const n = checkNumber(id);
  return CHECK_GROUPS.find((g) => n >= g.from && n <= g.to) ?? null;
}

export function checkIdsInGroup(group: CheckGroup): string[] {
  return Array.from({ length: group.to - group.from + 1 }, (_, i) => `P${String(group.from + i).padStart(2, "0")}`);
}
