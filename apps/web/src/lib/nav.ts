import {
  Activity,
  Bot,
  CalendarClock,
  CreditCard,
  FlaskConical,
  House,
  MessagesSquare,
  Receipt,
  Scale,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  soon?: boolean;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  { title: "", items: [{ href: "/", label: "Home", icon: House }] },
  {
    title: "Shopping",
    items: [
      { href: "/chat", label: "Shopping assistant", icon: MessagesSquare },
      { href: "/orders", label: "Orders", icon: Receipt },
    ],
  },
  {
    title: "Controls",
    items: [
      { href: "/agents", label: "Agents", icon: Bot },
      { href: "/rules", label: "Spending rules", icon: ShieldCheck },
      { href: "/payment", label: "Payment method", icon: CreditCard },
    ],
  },
  {
    title: "Support",
    items: [{ href: "/disputes", label: "Disputes", icon: Scale }],
  },
  {
    title: "Tools",
    items: [{ href: "/lab", label: "Attack simulator", icon: FlaskConical }],
  },
  {
    title: "In development",
    items: [
      { href: "/schedule", label: "Purchase calendar", icon: CalendarClock, soon: true },
      { href: "/console", label: "Risk insights", icon: Activity, soon: true },
    ],
  },
];

export function findNav(pathname: string): { section: string; item: NavItem } | null {
  for (const s of NAV) {
    for (const item of s.items) {
      if (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)) {
        return { section: s.title, item };
      }
    }
  }
  return null;
}
