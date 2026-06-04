import { Link } from "react-router-dom";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/layout/Logo";
import { cn } from "@/lib/utils";
import {
  ArrowRight,
  Briefcase,
  CalendarClock,
  Check,
  CompassIcon,
  Flag,
  HelpCircle,
  LineChart,
  Receipt,
  Sparkles,
  Target,
  TrendingUp,
  X as XIcon,
} from "lucide-react";

const FEATURES = [
  {
    icon: Receipt,
    title: "Smart transaction import",
    body:
      "Drop in your bank's CSV. Categorization happens automatically — rules first, ML second. Your rent, your Glovo orders, and your Wolt subscriptions land in the right buckets without you lifting a finger.",
  },
  {
    icon: Flag,
    title: "Savings goals with a real plan",
    body:
      "Set a target and a date. We tell you how much to save monthly — and what changes if you invest those savings instead. Honest math, no marketing tricks.",
  },
  {
    icon: TrendingUp,
    title: "Net worth, finally measured",
    body:
      "Track everything you own and owe. Daily snapshots produce a single chart that shows whether you're moving in the right direction, regardless of monthly noise.",
  },
  {
    icon: LineChart,
    title: "AI investment signals",
    body:
      "Buy, Hold, or Sell on US stocks — with a confidence score and a one-sentence reason. Trained on years of historical prices and technical indicators.",
  },
  {
    icon: CalendarClock,
    title: "Recurring payments, surfaced",
    body:
      "Subscriptions, rent, and salaries are detected automatically from your transaction history and laid out on a monthly calendar. No more surprise charges.",
  },
  {
    icon: Briefcase,
    title: "Paper trading portfolio",
    body:
      "Place virtual Buy and Sell orders on US stocks with $10,000 of virtual cash. Track holdings, realized P&L, allocation, and an equity curve — without risking real money.",
  },
];

const STEPS = [
  {
    n: 1,
    title: "Import your transactions",
    body:
      "Upload a CSV from your bank in under thirty seconds. We map your columns, categorize automatically, and build your starting picture.",
  },
  {
    n: 2,
    title: "See the full picture",
    body:
      "Your dashboard shows balance, spending, savings goals, planned payments, and net worth — all in one screen.",
  },
  {
    n: 3,
    title: "Plan and act",
    body:
      "Set goals, paper-trade US stocks, and build clarity into a habit.",
  },
];

const COMPARISON = {
  rows: [
    "Personal budgets and categories",
    "Automatic ML categorization",
    "Savings goals with monthly plan",
    "Planned payments + calendar",
    "Net worth tracking with history",
    "Stock trading on US stocks",
    "AI Buy/Hold/Sell with confidence",
    "Multi-currency RON / EUR / USD",
  ],
  cols: ["Revolut", "eToro", "George", "ING Home'Bank", "Tradeville", "Lumen"],
  // ✓ / ✗ per row × col — calibrated against published features of each app
  // as of May 2026; researched and binary, no half-credit.
  cells: [
    // Personal budgets and categories
    ["✓", "✗", "✓", "✓", "✗", "✓"],
    // Automatic ML categorization
    ["✓", "✗", "✓", "✓", "✗", "✓"],
    // Savings goals with monthly plan
    ["✓", "✗", "✗", "✗", "✗", "✓"],
    // Planned payments + calendar
    ["✗", "✗", "✗", "✗", "✗", "✓"],
    // Net worth tracking with history
    ["✓", "✗", "✗", "✗", "✗", "✓"],
    // Stock trading on US stocks (real or paper)
    ["✓", "✓", "✗", "✗", "✓", "✓"],
    // AI Buy/Hold/Sell with confidence
    ["✗", "✗", "✗", "✗", "✗", "✓"],
    // Multi-currency RON / EUR / USD
    ["✓", "✗", "✓", "✓", "✓", "✓"],
  ],
};

const FAQS = [
  {
    q: "Is my data safe?",
    a: "Your transactions live only in our database, encrypted at rest, accessible only by you.",
  },
  {
    q: "Is this real banking?",
    a: "No. Lumen does not connect to your bank, does not move money, and does not place real trades. You import your transactions manually and your investment portfolio is paper-traded with virtual cash.",
  },
  {
    q: "Will the stock signals tell me what to buy?",
    a: "The signals report direction probabilities from a machine-learning model along with the indicators driving the call. Any decision is yours.",
  },
  {
    q: "Why don't you connect to my bank automatically?",
    a: "Open Banking integrations (PSD2, Plaid, Salt Edge) require regulatory licensing and payment infrastructure that are outside the scope of this release. We plan to add this in a future version — for now, importing your bank's CSV takes under thirty seconds.",
  },
  {
    q: "Does this support my currency?",
    a: "Lumen supports RON, EUR, and USD natively, with daily exchange rates from the European Central Bank. Other currencies are not currently supported.",
  },
];

export default function LandingPage() {
  return (
    <div className="bg-background text-text-primary antialiased">
      {/* Header */}
      <header className="fixed top-0 z-50 w-full border-b border-border/60 bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-md md:px-lg">
          <Link
            to="/"
            className="focus-ring rounded-lg"
            aria-label="Lumen home — scroll to top"
            onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          >
            <Logo />
          </Link>
          <nav className="hidden items-center gap-md md:flex">
            <a href="#features" className="text-body-small text-text-muted transition-colors hover:text-text-primary">
              Features
            </a>
            <a href="#how-it-works" className="text-body-small text-text-muted transition-colors hover:text-text-primary">
              How it works
            </a>
            <a href="#comparison" className="text-body-small text-text-muted transition-colors hover:text-text-primary">
              Comparison
            </a>
            <a href="#faq" className="text-body-small text-text-muted transition-colors hover:text-text-primary">
              FAQ
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link to="/auth">Log in</Link>
            </Button>
            <Button variant="primary" size="sm" asChild>
              <Link to="/auth?mode=register">
                Get started — free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="pt-24">
        {/* Hero */}
        <section className="relative overflow-hidden">
          <div
            aria-hidden="true"
            className="absolute inset-x-0 -top-40 -z-10 h-[500px] bg-gradient-to-b from-primary-tint via-background to-background"
          />
          <div className="mx-auto grid max-w-7xl items-center gap-2xl px-md py-2xl md:grid-cols-2 md:gap-3xl md:px-lg md:py-3xl">
            <div className="animate-blur-up">
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary-tint px-3 py-1 text-uppercase-label uppercase text-primary">
                <Sparkles className="h-3 w-3" /> Personal finance, reimagined
              </span>
              <h1 className="mt-md text-display font-display leading-tight tracking-tight text-text-primary">
                Clarity for your money.{" "}
                <span className="text-primary">From budgets to investments,</span> in one place.
              </h1>
              <p className="mt-md max-w-xl text-body-large text-text-muted">
                Lumen unifies your spending, your savings goals, and AI-assisted stock investing in
                a single dashboard — with the clarity to know where you're actually heading.
              </p>
              <div className="mt-lg flex flex-col gap-2 sm:flex-row">
                <Button variant="primary" size="lg" asChild>
                  <Link to="/auth?mode=register">
                    Get started — free <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </div>

            {/* Hero mockup — stylized dashboard preview */}
            <div className="relative animate-blur-up delay-200">
              <div className="absolute -inset-md rounded-2xl bg-gradient-to-br from-primary/30 via-accent/15 to-transparent blur-3xl" />
              <div className="relative overflow-hidden rounded-2xl border border-border bg-surface shadow-modal">
                <div className="flex items-center gap-1.5 border-b border-border bg-surface-soft px-3 py-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-danger/70" />
                  <span className="h-2.5 w-2.5 rounded-full bg-warning/70" />
                  <span className="h-2.5 w-2.5 rounded-full bg-success/70" />
                  <span className="ml-3 text-uppercase-label uppercase text-text-muted">
                    lumen.app/dashboard
                  </span>
                </div>
                <div className="space-y-3 p-md">
                  <div className="grid grid-cols-3 gap-2">
                    {["Total balance", "Income", "Expenses"].map((l, i) => (
                      <div
                        key={l}
                        className={cn(
                          "rounded-lg border border-border bg-surface p-3 animate-slide-up",
                          `delay-${100 + i * 100}`,
                        )}
                      >
                        <div className="text-uppercase-label uppercase text-text-muted">{l}</div>
                        <div className="mt-1 text-h4 font-semibold tabular">
                          {["8,420", "5,200", "3,150"][i]}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex h-32 items-end justify-between gap-1 rounded-lg border border-border bg-surface p-3">
                    {Array.from({ length: 12 }).map((_, i) => (
                      <div
                        key={i}
                        className="w-full rounded-sm bg-primary/80 animate-slide-up"
                        style={{
                          height: `${30 + Math.sin(i * 0.7) * 30 + i * 4}%`,
                          animationDelay: `${200 + i * 60}ms`,
                        }}
                      />
                    ))}
                  </div>
                  <div className="flex items-center gap-3 rounded-lg border border-primary/20 bg-primary-tint p-3 animate-slide-up delay-500">
                    <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                    <p className="text-body-small text-text-primary">
                      AAPL is a <span className="font-semibold">BUY</span> with 78% confidence —
                      RSI is oversold.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Problem */}
        <section
          id="problem"
          className="bg-primary-tint/40 py-2xl md:py-3xl"
        >
          <div className="mx-auto max-w-7xl px-md md:px-lg">
            <h2 className="text-h1 font-h1 leading-tight tracking-tight text-text-primary">
              The financial fog is real.
            </h2>
            <div className="mt-xl grid gap-lg md:grid-cols-3">
              {[
                {
                  icon: HelpCircle,
                  title: "Where did the money go?",
                  body:
                    "The average person can't account for 30% of their monthly spending. Existing apps give you charts but not answers.",
                },
                {
                  icon: CompassIcon,
                  title: "Will I be okay next month?",
                  body:
                    "Banking apps show what you have today but say nothing about what you'll have on the 22nd, when rent is due and your card declines.",
                },
                {
                  icon: Target,
                  title: "Is this a good investment?",
                  body:
                    "Investment platforms give you charts and indicators, but no one tells you why a stock is a buy in plain English.",
                },
              ].map((p, i) => (
                <div
                  key={p.title}
                  className={cn(
                    "rounded-xl border border-border bg-surface p-lg shadow-card transition-all hover:-translate-y-1 hover:shadow-card-hover animate-slide-up",
                    `delay-${i * 100}`,
                  )}
                >
                  <div className="mb-md flex h-12 w-12 items-center justify-center rounded-lg bg-primary-tint text-primary">
                    <p.icon className="h-6 w-6" />
                  </div>
                  <h3 className="text-h4 font-h4">{p.title}</h3>
                  <p className="mt-2 text-body text-text-muted">{p.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="py-2xl md:py-3xl">
          <div className="mx-auto max-w-7xl px-md md:px-lg">
            <div className="text-center">
              <h2 className="text-h1 font-h1 tracking-tight">Six tools, one dashboard.</h2>
              <p className="mx-auto mt-3 max-w-2xl text-body-large text-text-muted">
                Everything you need to make confident money decisions, without stitching together
                five different apps.
              </p>
            </div>
            <div className="mt-xl grid gap-md md:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((f, i) => (
                <div
                  key={f.title}
                  className={cn(
                    "group rounded-xl border border-border bg-surface p-lg shadow-card transition-all duration-300",
                    "hover:-translate-y-1 hover:border-primary/40 hover:shadow-card-hover",
                    "animate-slide-up",
                  )}
                  style={{ animationDelay: `${i * 60}ms` }}
                >
                  <div className="mb-md flex h-12 w-12 items-center justify-center rounded-lg bg-primary-tint text-primary transition-colors group-hover:bg-primary group-hover:text-on-primary">
                    <f.icon className="h-6 w-6" />
                  </div>
                  <h3 className="text-h4 font-h4 leading-snug">{f.title}</h3>
                  <p className="mt-2 text-body text-text-muted">{f.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="bg-surface-soft py-2xl md:py-3xl">
          <div className="mx-auto max-w-7xl px-md md:px-lg">
            <h2 className="text-center text-h1 font-h1 tracking-tight">Three steps to clarity.</h2>
            <div className="mt-xl grid gap-lg md:grid-cols-3">
              {STEPS.map((s, i) => (
                <div
                  key={s.n}
                  className={cn(
                    "relative rounded-xl border border-border bg-surface p-lg animate-slide-up",
                  )}
                  style={{ animationDelay: `${i * 100}ms` }}
                >
                  <div className="mb-md flex h-10 w-10 items-center justify-center rounded-full bg-primary text-on-primary text-h4 font-bold">
                    {s.n}
                  </div>
                  <h3 className="text-h4 font-h4">{s.title}</h3>
                  <p className="mt-2 text-body text-text-muted">{s.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Showcase blocks */}
        <section id="showcase" className="py-2xl md:py-3xl">
          <div className="mx-auto max-w-7xl space-y-2xl px-md md:px-lg md:space-y-3xl">
            <ShowcaseBlock
              flip={false}
              eyebrow="The signals"
              title="Educated guesses, with the homework attached."
              body="For every Buy or Sell signal, we tell you why — RSI is oversold and MACD turned positive, or price broke below the 200-day moving average. The model learns from five years of historical price data."
              cta={{ to: "/auth?mode=register", label: "Open Markets" }}
              mockup={<SignalMockup />}
            />
          </div>
        </section>

        {/* Comparison */}
        <section id="comparison" className="bg-surface-soft py-2xl md:py-3xl">
          <div className="mx-auto max-w-7xl px-md md:px-lg">
            <h2 className="text-center text-h1 font-h1 tracking-tight">
              Why Lumen versus everything else?
            </h2>
            <div className="mt-xl overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
              <table className="w-full min-w-[680px] text-body-small">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-md py-md text-left text-uppercase-label uppercase text-text-muted">
                      Capability
                    </th>
                    {COMPARISON.cols.map((c) => (
                      <th
                        key={c}
                        className={cn(
                          "px-md py-md text-center text-uppercase-label uppercase",
                          c === "Lumen" ? "bg-primary-tint text-primary" : "text-text-muted",
                        )}
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COMPARISON.rows.map((row, ri) => (
                    <tr key={row} className="border-b border-border last:border-0">
                      <td className="px-md py-md font-medium text-text-primary">{row}</td>
                      {COMPARISON.cells[ri].map((cell, ci) => {
                        const isLumen = COMPARISON.cols[ci] === "Lumen";
                        return (
                          <td
                            key={ci}
                            className={cn(
                              "px-md py-md text-center tabular",
                              isLumen ? "bg-primary-tint/60" : "",
                            )}
                          >
                            {cell === "✓" ? (
                              <Check className={cn("mx-auto h-4 w-4", isLumen ? "text-primary" : "text-success")} />
                            ) : cell === "~" ? (
                              <span className="text-text-muted">—</span>
                            ) : (
                              <XIcon className="mx-auto h-4 w-4 text-text-muted/40" />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="py-2xl md:py-3xl">
          <div className="mx-auto max-w-3xl px-md md:px-lg">
            <h2 className="text-center text-h1 font-h1 tracking-tight">Questions you probably have.</h2>
            <Accordion type="single" collapsible className="mt-xl">
              {FAQS.map((f) => (
                <AccordionItem key={f.q} value={f.q}>
                  <AccordionTrigger>{f.q}</AccordionTrigger>
                  <AccordionContent>{f.a}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </section>

        {/* Final CTA */}
        <section className="bg-primary-tint py-2xl">
          <div className="mx-auto max-w-3xl px-md text-center md:px-lg">
            <h2 className="text-h1 font-h1 tracking-tight">Ready to clear the fog?</h2>
            <Button variant="primary" size="lg" asChild className="mt-lg">
              <Link to="/auth?mode=register">
                Get started — free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-text-primary text-white">
        <div className="mx-auto grid max-w-7xl gap-xl px-md py-xl md:grid-cols-[2fr_1fr_1fr] md:px-lg md:py-2xl">
          <div>
            <Logo />
            <p className="mt-3 max-w-sm text-body-small text-white/60">
              Personal finance, savings goals, and AI-assisted investing — in one app.
            </p>
          </div>
          <div>
            <div className="mb-3 text-uppercase-label uppercase text-white/50">Product</div>
            <ul className="space-y-1.5">
              <li>
                <a href="#features" className="text-body-small text-white/80 transition-colors hover:text-white">
                  Features
                </a>
              </li>
              <li>
                <a href="#how-it-works" className="text-body-small text-white/80 transition-colors hover:text-white">
                  How it works
                </a>
              </li>
              <li>
                <a href="#comparison" className="text-body-small text-white/80 transition-colors hover:text-white">
                  Comparison
                </a>
              </li>
              <li>
                <a href="#faq" className="text-body-small text-white/80 transition-colors hover:text-white">
                  FAQ
                </a>
              </li>
            </ul>
          </div>
          <div>
            <div className="mb-3 text-uppercase-label uppercase text-white/50">Get started</div>
            <ul className="space-y-1.5">
              <li>
                <Link to="/auth?mode=register" className="text-body-small text-white/80 transition-colors hover:text-white">
                  Create account
                </Link>
              </li>
              <li>
                <Link to="/auth" className="text-body-small text-white/80 transition-colors hover:text-white">
                  Log in
                </Link>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/10">
          <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-md py-md text-uppercase-label uppercase text-white/40 md:flex-row md:px-lg">
            <span>© 2026 Lumen. All rights reserved.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

interface ShowcaseProps {
  flip: boolean;
  eyebrow: string;
  title: string;
  body: string;
  cta: { to: string; label: string };
  mockup: React.ReactNode;
}

function ShowcaseBlock({ flip, eyebrow, title, body, cta, mockup }: ShowcaseProps) {
  return (
    <div className={cn("grid items-center gap-lg md:grid-cols-2 md:gap-2xl")}>
      <div className={cn(flip ? "md:order-2" : "")}>
        <span className="text-uppercase-label uppercase text-primary">{eyebrow}</span>
        <h3 className="mt-2 text-h2 font-h2 tracking-tight">{title}</h3>
        <p className="mt-3 text-body-large text-text-muted">{body}</p>
        <Button variant="ghost" asChild className="mt-md text-primary hover:bg-primary-tint">
          <Link to={cta.to}>
            {cta.label} <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
      <div className={cn("relative", flip ? "md:order-1" : "")}>
        <div className="absolute -inset-4 rounded-2xl bg-primary/10 blur-2xl" />
        <div className="relative">{mockup}</div>
      </div>
    </div>
  );
}

function SignalMockup() {
  return (
    <div className="rounded-xl border border-border bg-surface p-md shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-body-large font-semibold">AAPL</span>
        <span className="rounded-full border border-success/30 bg-success/10 px-2 py-1 text-uppercase-label uppercase text-success">
          BUY · 78%
        </span>
      </div>
      <div className="space-y-2 text-body-small text-text-muted">
        <p className="text-text-primary">
          RSI is oversold (28) and MACD histogram turned positive in the last two sessions. Price is
          above the 50-day moving average.
        </p>
        <div className="flex items-center gap-2 text-uppercase-label uppercase">
          <span className="rounded bg-surface-soft px-2 py-0.5">RSI</span>
          <span className="rounded bg-surface-soft px-2 py-0.5">MACD</span>
          <span className="rounded bg-surface-soft px-2 py-0.5">SMA-50</span>
        </div>
      </div>
    </div>
  );
}
