import { SHOPPING_CATEGORIES } from "@/features/rules/constants";
import { ChatRuleOption } from "./types";

export const SHOPPER_NAME = "Sepilo Shopper";
export const SHOPPER_INTRO =
  "I search real stores through Channel3 and only suggest what your spending rules allow. Add what you like to your cart; nothing is bought until you approve it.";

export const STARTER_PROMPTS: Record<string, string[]> = {
  electronics: ["A USB-C to USB-C cable, about 1 m, under $20", "Wireless earbuds under $50"],
  "home-garden": ["A stainless steel water bottle under $25", "Microfiber cleaning cloths, pack of 12"],
  "health-beauty": ["Unscented shampoo under $15", "SPF 50 sunscreen"],
  "baby-toddler": ["Unscented baby wipes", "A silicone baby bib set"],
  "animals-pet-supplies": ["Durable chew toys for a medium dog", "Cat litter under $20"],
  "office-supplies": ["Gel pens, pack of 12", "A4 notebooks, set of 3"],
  "toys-games": ["A 500-piece jigsaw puzzle", "A beginner LEGO set under $30"],
  "apparel-accessories": ["Running socks, 3 pairs", "A plain black cap"],
};
export const DEFAULT_PROMPTS = ["A USB-C to USB-C cable under $20", "Wireless earbuds under $50", "A stainless steel water bottle"];

export function promptsFor(rules: ChatRuleOption[]): string[] {
  const out: string[] = [];
  for (const rule of rules) {
    for (const category of rule.categories) {
      for (const prompt of STARTER_PROMPTS[category] ?? []) if (!out.includes(prompt)) out.push(prompt);
    }
  }
  return (out.length ? out : DEFAULT_PROMPTS).slice(0, 4);
}

export const categoryName = (slug: string): string => SHOPPING_CATEGORIES[slug] ?? slug.replace(/-/g, " ");

export function ruleName(rule: ChatRuleOption): string {
  const names = rule.categories.map(categoryName);
  return names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", ") || "Any category";
}

export const PERIOD_TEXT: Record<string, string> = { month: "a month", week: "a week", once: "once" };

export const SHOPPING_WORDS = [
  "Rummaging", "Window-shopping", "Haggling", "Bargain-hunting", "Combing the aisles", "Finagling",
  "Coupon-clipping", "Price-sleuthing", "Shelf-scouring", "Sniffing out deals", "Wrangling carts",
  "Squinting at price tags", "Checking your rules",
];
export const THINKING_GLYPHS = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"];

export const IN_PROGRESS_ORDER = new Set(["received", "authorized", "checking"]);

export const PAYPAL_NOTICE: Record<string, string> = {
  cancelled: "The payment wasn't approved in PayPal. Use Pay with PayPal to finish when you're ready.",
  failed: "PayPal couldn't take the payment, so nothing was charged.",
  error: "That PayPal link didn't match this order.",
};
