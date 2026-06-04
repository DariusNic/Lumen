import { Fragment, type ReactNode } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const GLOSSARY: Record<string, string> = {
  rsi: "Relative Strength Index — a number between 0 and 100 that shows how strongly the price has risen or fallen over the last 14 days. Below 30 = oversold, above 70 = overbought.",
  oversold:
    "Oversold: the price has dropped so much that a rebound may follow. For RSI, this means a value below 30.",
  overbought:
    "Overbought: the price has risen too fast and a pullback may follow. For RSI, this means a value above 70.",
  macd: "Moving Average Convergence Divergence — the difference between the 12-day and 26-day exponential moving averages. When the histogram turns positive, recent momentum is improving.",
  "bollinger band":
    "Two bands drawn at ±2 standard deviations around the 20-day average. Price above the upper band = possibly overbought; below the lower band = possibly oversold.",
  momentum:
    "How fast the price is moving. “Strong positive momentum” means the price has climbed significantly over the last few weeks.",
  ema: "Exponential Moving Average — a weighted average of the price (50 days in our case) that gives more weight to recent days. Price above EMA50 signals a positive medium-term trend.",
  atr: "Average True Range — a measure of daily volatility. Higher values = wider daily swings. It does not indicate direction.",
};

const TERM_PATTERN = /\[\[([^\]]+)\]\]/g;

function termDefinition(term: string): string | undefined {
  return GLOSSARY[term.trim().toLowerCase()];
}

/**
 * Renders a signal explanation string that may contain `[[Term]]` markers.
 * Each marker becomes a purple, dotted-underlined span with a tooltip
 * containing a one-sentence plain-language definition from the glossary.
 *
 * Unknown terms (no glossary entry) are rendered as plain text — defensive
 * fallback in case the backend introduces a new term before the glossary
 * catches up.
 */
export function ExplanationWithTerms({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  TERM_PATTERN.lastIndex = 0;

  while ((match = TERM_PATTERN.exec(text)) !== null) {
    if (match.index > cursor) {
      parts.push(
        <Fragment key={`t-${cursor}`}>{text.slice(cursor, match.index)}</Fragment>,
      );
    }
    const term = match[1];
    const definition = termDefinition(term);
    if (definition) {
      parts.push(
        <Tooltip key={`m-${match.index}`}>
          <TooltipTrigger asChild>
            <span
              tabIndex={0}
              className="cursor-help font-semibold text-purple-600 underline decoration-purple-400 decoration-dotted underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-purple-400 focus-visible:ring-offset-1"
            >
              {term}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs text-pretty">
            {definition}
          </TooltipContent>
        </Tooltip>,
      );
    } else {
      parts.push(<Fragment key={`m-${match.index}`}>{term}</Fragment>);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    parts.push(<Fragment key={`t-${cursor}`}>{text.slice(cursor)}</Fragment>);
  }

  return (
    <TooltipProvider delayDuration={150}>
      <p className="text-text-primary">{parts}</p>
    </TooltipProvider>
  );
}
